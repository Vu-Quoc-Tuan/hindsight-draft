from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import zstandard
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from libs.contracts import IngestedPackage, load_validated_package

from ..ingest.wire import SnapshotChunkEvent, SnapshotCompleteEvent, SnapshotWireEvent
from .models import (
    Alarm,
    Chain,
    KafkaInbox,
    Membership,
    Snapshot,
    SnapshotChunk,
    SnapshotIngest,
)


@dataclass(frozen=True)
class IngestResult:
    snapshot_id: str
    snapshot_version: str
    status: str
    duplicate: bool = False
    completed_now: bool = False
    invalid_reason: str | None = None
    canonical_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class Tier1AClaim:
    snapshot_id: str
    snapshot_version: str
    payload: dict[str, Any]
    worker_id: str
    attempt_count: int


def _logical_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class SnapshotRepository:
    """Transactional chunk assembly and relational snapshot persistence."""

    def __init__(
        self,
        sessions: async_sessionmaker,
        *,
        max_compressed_snapshot_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self.sessions = sessions
        self.max_compressed_snapshot_bytes = max_compressed_snapshot_bytes

    async def record_kafka_event(
        self,
        event: SnapshotWireEvent,
        *,
        topic: str,
        partition: int,
        offset: int,
    ) -> IngestResult:
        async with self.sessions.begin() as session:
            seen = await session.scalar(
                select(KafkaInbox.id).where(
                    KafkaInbox.topic == topic,
                    KafkaInbox.partition == partition,
                    KafkaInbox.offset == offset,
                )
            )
            if seen is not None:
                row = await session.get(
                    SnapshotIngest, (event.snapshot_id, event.snapshot_version)
                )
                return self._result(row, duplicate=True)

            row = await session.get(
                SnapshotIngest,
                (event.snapshot_id, event.snapshot_version),
                with_for_update=True,
            )
            if row is None:
                row = SnapshotIngest(
                    snapshot_id=event.snapshot_id,
                    snapshot_version=event.snapshot_version,
                    status="RECEIVING",
                )
                session.add(row)
                await session.flush()

            session.add(
                KafkaInbox(
                    topic=topic,
                    partition=partition,
                    offset=offset,
                    snapshot_id=event.snapshot_id,
                    snapshot_version=event.snapshot_version,
                    event_type=event.event_type,
                )
            )
            if row.status in {"INVALID", "EXPIRED"}:
                return self._result(row)
            if row.status == "COMPLETE":
                duplicate = await self._verify_completed_event(session, row, event)
                return self._result(row, duplicate=duplicate)

            if isinstance(event, SnapshotChunkEvent):
                duplicate = await self._record_chunk(session, row, event)
            else:
                duplicate = self._record_barrier(row, event)

            if row.status == "INVALID":
                return self._result(row, duplicate=duplicate)
            payload = await self._try_complete(session, row)
            return self._result(
                row,
                duplicate=duplicate,
                completed_now=payload is not None,
                canonical_payload=payload,
            )

    async def _verify_completed_event(self, session, row, event) -> bool:
        if isinstance(event, SnapshotCompleteEvent):
            expected = {
                "expected_chunk_count": event.expected_chunk_count,
                "snapshot_checksum": event.snapshot_checksum,
                "total_uncompressed_bytes": event.total_uncompressed_bytes,
                "produced_at": event.produced_at,
                "source": event.source,
                "source_kind": event.source_kind,
            }
            if all(getattr(row, name) == value for name, value in expected.items()):
                return True
            self._invalidate(row, "conflicting replay of completed barrier")
            return False

        existing = await session.get(
            SnapshotChunk,
            (event.snapshot_id, event.snapshot_version, event.chunk_index),
        )
        if existing is not None and (
            existing.checksum == event.chunk_checksum
            and existing.payload_bytes == event.payload
            and existing.chunk_count == event.chunk_count
            and existing.snapshot_checksum == event.snapshot_checksum
        ):
            return True
        self._invalidate(row, f"conflicting replay of completed chunk {event.chunk_index}")
        return False

    async def _record_chunk(self, session, row, event: SnapshotChunkEvent) -> bool:
        if row.expected_chunk_count not in (None, event.chunk_count):
            self._invalidate(row, "conflicting chunk_count")
            return False
        if row.snapshot_checksum not in (None, event.snapshot_checksum):
            self._invalidate(row, "conflicting snapshot checksum")
            return False
        row.expected_chunk_count = event.chunk_count
        row.snapshot_checksum = event.snapshot_checksum

        existing = await session.get(
            SnapshotChunk,
            (event.snapshot_id, event.snapshot_version, event.chunk_index),
        )
        if existing is not None:
            if (
                existing.checksum == event.chunk_checksum
                and existing.payload_bytes == event.payload
            ):
                return True
            self._invalidate(row, f"conflicting duplicate chunk {event.chunk_index}")
            return False

        retained_bytes = int(
            await session.scalar(
                select(
                    func.coalesce(
                        func.sum(func.octet_length(SnapshotChunk.payload_bytes)), 0
                    )
                ).where(
                    SnapshotChunk.snapshot_id == event.snapshot_id,
                    SnapshotChunk.snapshot_version == event.snapshot_version,
                )
            )
            or 0
        )
        if retained_bytes + len(event.payload) > self.max_compressed_snapshot_bytes:
            self._invalidate(row, "compressed snapshot exceeds configured limit")
            return False

        session.add(
            SnapshotChunk(
                snapshot_id=event.snapshot_id,
                snapshot_version=event.snapshot_version,
                chunk_index=event.chunk_index,
                chunk_count=event.chunk_count,
                checksum=event.chunk_checksum,
                snapshot_checksum=event.snapshot_checksum,
                payload_bytes=event.payload,
            )
        )
        await session.flush()
        row.received_chunk_count = int(
            await session.scalar(
                select(func.count(SnapshotChunk.chunk_index)).where(
                    SnapshotChunk.snapshot_id == event.snapshot_id,
                    SnapshotChunk.snapshot_version == event.snapshot_version,
                )
            )
            or 0
        )
        return False

    def _record_barrier(
        self, row: SnapshotIngest, event: SnapshotCompleteEvent
    ) -> bool:
        fields = (
            ("expected_chunk_count", event.expected_chunk_count),
            ("snapshot_checksum", event.snapshot_checksum),
            ("total_uncompressed_bytes", event.total_uncompressed_bytes),
            ("produced_at", event.produced_at),
            ("source", event.source),
            ("source_kind", event.source_kind),
        )
        duplicate = all(getattr(row, name) == value for name, value in fields)
        for name, value in fields:
            current = getattr(row, name)
            if current is not None and current != value:
                self._invalidate(row, f"conflicting barrier field {name}")
                return False
            setattr(row, name, value)
        return duplicate

    async def _try_complete(
        self, session, row: SnapshotIngest
    ) -> dict[str, Any] | None:
        if (
            row.produced_at is None
            or row.expected_chunk_count is None
            or row.received_chunk_count != row.expected_chunk_count
        ):
            return None
        chunks = list(
            (
                await session.scalars(
                    select(SnapshotChunk)
                    .where(
                        SnapshotChunk.snapshot_id == row.snapshot_id,
                        SnapshotChunk.snapshot_version == row.snapshot_version,
                    )
                    .order_by(SnapshotChunk.chunk_index)
                )
            ).all()
        )
        if [chunk.chunk_index for chunk in chunks] != list(
            range(row.expected_chunk_count)
        ):
            return None
        try:
            compressed_stream = io.BytesIO(
                b"".join(chunk.payload_bytes for chunk in chunks)
            )
            with zstandard.ZstdDecompressor().stream_reader(compressed_stream) as reader:
                canonical = reader.read((row.total_uncompressed_bytes or 0) + 1)
        except (zstandard.ZstdError, OSError) as exc:
            self._invalidate(row, f"zstd decompression failed: {exc}")
            return None
        if len(canonical) != row.total_uncompressed_bytes:
            self._invalidate(row, "uncompressed size mismatch")
            return None
        checksum = hashlib.sha256(canonical).hexdigest()
        if checksum != row.snapshot_checksum:
            self._invalidate(row, "whole snapshot checksum mismatch")
            return None
        try:
            payload = json.loads(canonical)
            package = load_validated_package(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._invalidate(row, f"canonical contract validation failed: {exc}")
            return None
        if (
            package.snapshot.snapshot_id != row.snapshot_id
            or package.snapshot.snapshot_version != row.snapshot_version
        ):
            self._invalidate(row, "envelope identity does not match canonical snapshot")
            return None
        if not package.snapshot.is_complete:
            self._invalidate(row, "canonical snapshot status is not COMPLETE")
            return None

        await self._persist_canonical(session, package, payload, checksum)
        row.canonical_payload = payload
        row.logical_snapshot_time = _logical_time(package.snapshot.snapshot_time)
        row.status = "COMPLETE"
        row.tier1a_status = "PENDING"
        row.completed_at = func.now()
        return payload

    async def ingest_direct(self, payload: dict[str, Any]) -> IngestResult:
        package = load_validated_package(payload)
        if not package.snapshot.is_complete:
            raise ValueError("Direct Snapshot ingest requires status COMPLETE")
        canonical = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        checksum = hashlib.sha256(canonical).hexdigest()
        identity = (package.snapshot.snapshot_id, package.snapshot.snapshot_version)
        async with self.sessions.begin() as session:
            row = await session.get(SnapshotIngest, identity, with_for_update=True)
            if row is not None:
                if row.status == "COMPLETE" and row.canonical_payload == payload:
                    return self._result(row, duplicate=True)
                raise ValueError("snapshot identity already exists with different content")
            row = SnapshotIngest(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                status="COMPLETE",
                expected_chunk_count=0,
                received_chunk_count=0,
                snapshot_checksum=checksum,
                total_uncompressed_bytes=len(canonical),
                produced_at=package.snapshot.produced_at,
                source=package.snapshot.source,
                source_kind=package.snapshot.source_kind,
                canonical_payload=payload,
                logical_snapshot_time=_logical_time(package.snapshot.snapshot_time),
                tier1a_status="PENDING",
                completed_at=func.now(),
            )
            session.add(row)
            await self._persist_canonical(session, package, payload, checksum)
            return self._result(row, completed_now=True, canonical_payload=payload)

    async def _persist_canonical(
        self,
        session,
        package: IngestedPackage,
        payload: dict[str, Any],
        checksum: str,
    ) -> None:
        identity = (package.snapshot.snapshot_id, package.snapshot.snapshot_version)
        existing = await session.get(Snapshot, identity)
        if existing is not None:
            if existing.raw_payload != payload:
                raise ValueError("canonical snapshot identity conflict")
            return
        session.add(
            Snapshot(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                snapshot_time=package.snapshot.snapshot_time,
                status=package.snapshot.status,
                source=package.snapshot.source,
                source_kind=package.snapshot.source_kind,
                produced_at=package.snapshot.produced_at,
                config_version=package.snapshot.config_version,
                topology_version=package.snapshot.topology_version,
                raw_payload=payload,
                payload_checksum=checksum,
            )
        )
        # These models intentionally avoid ORM relationships.  Flush each FK
        # layer explicitly so SQLAlchemy does not need relationship metadata to
        # infer parent-before-child ordering.
        await session.flush()
        session.add_all(
            Alarm(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                alarm_id=alarm.alarm_id,
                alarm_name=alarm.alarm_name,
                device_code=alarm.device_code,
                node_reference=alarm.node_reference,
                severity_name=alarm.severity_name,
                canonical_start_time=alarm.canonical_start_time,
                canonical_end_time=alarm.canonical_end_time,
                quality_flags=list(alarm.quality_flags),
                raw=alarm.raw,
            )
            for alarm in package.alarms.values()
        )
        session.add_all(
            Chain(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                chain_id=chain.chain_id,
                member_count=chain.member_count,
                chain_name=chain.chain_name,
                event_span_seconds=chain.event_span_seconds,
            )
            for chain in package.chains.values()
        )
        await session.flush()
        session.add_all(
            Membership(
                snapshot_id=identity[0],
                snapshot_version=identity[1],
                chain_id=chain_id,
                alarm_id=alarm_id,
            )
            for chain_id, alarms in package.memberships.items()
            for alarm_id in alarms
        )

    async def claim_next_tier1a(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int = 5,
        now: datetime | None = None,
    ) -> Tier1AClaim | None:
        """Claim the oldest logical pending/stale job without blocking peers."""
        current = now or datetime.now(timezone.utc)
        lease_until = current + timedelta(seconds=lease_seconds)
        async with self.sessions.begin() as session:
            while True:
                row = await session.scalar(
                    select(SnapshotIngest)
                    .where(
                        SnapshotIngest.status == "COMPLETE",
                        or_(
                            SnapshotIngest.tier1a_status == "PENDING",
                            (
                                (SnapshotIngest.tier1a_status == "RUNNING")
                                & or_(
                                    SnapshotIngest.lease_expires_at.is_(None),
                                    SnapshotIngest.lease_expires_at <= current,
                                )
                            ),
                        ),
                    )
                    .order_by(
                        SnapshotIngest.logical_snapshot_time.asc().nulls_last(),
                        SnapshotIngest.completed_at.asc().nulls_last(),
                        SnapshotIngest.snapshot_id.asc(),
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if row is None or row.canonical_payload is None:
                    return None
                if row.next_attempt_at is not None and row.next_attempt_at > current:
                    return None
                if row.attempt_count >= max_attempts:
                    row.tier1a_status = "FAILED"
                    row.worker_id = None
                    row.lease_expires_at = None
                    row.heartbeat_at = None
                    row.next_attempt_at = None
                    await session.flush()
                    continue
                break
            row.tier1a_status = "RUNNING"
            row.worker_id = worker_id
            row.lease_expires_at = lease_until
            row.started_at = current
            row.heartbeat_at = current
            row.next_attempt_at = None
            row.attempt_count += 1
            await session.flush()
            return Tier1AClaim(
                snapshot_id=row.snapshot_id,
                snapshot_version=row.snapshot_version,
                payload=row.canonical_payload,
                worker_id=worker_id,
                attempt_count=row.attempt_count,
            )

    async def heartbeat_tier1a(
        self,
        snapshot_id: str,
        snapshot_version: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(SnapshotIngest)
                .where(
                    SnapshotIngest.snapshot_id == snapshot_id,
                    SnapshotIngest.snapshot_version == snapshot_version,
                    SnapshotIngest.tier1a_status == "RUNNING",
                    SnapshotIngest.worker_id == worker_id,
                )
                .values(
                    heartbeat_at=current,
                    lease_expires_at=current + timedelta(seconds=lease_seconds),
                )
            )
            return bool(result.rowcount)

    async def latest_ready_payload(self) -> dict[str, Any] | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(SnapshotIngest.canonical_payload)
                .where(
                    SnapshotIngest.status == "COMPLETE",
                    SnapshotIngest.tier1a_status == "READY",
                )
                .order_by(
                    SnapshotIngest.logical_snapshot_time.desc().nulls_last(),
                    SnapshotIngest.completed_at.desc().nulls_last(),
                    SnapshotIngest.snapshot_id.desc(),
                )
                .limit(1)
            )

    async def finish_tier1a(
        self,
        snapshot_id: str,
        snapshot_version: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            statement = update(SnapshotIngest).where(
                    SnapshotIngest.snapshot_id == snapshot_id,
                    SnapshotIngest.snapshot_version == snapshot_version,
                    SnapshotIngest.tier1a_status == "RUNNING",
                )
            if worker_id is not None:
                statement = statement.where(SnapshotIngest.worker_id == worker_id)
            await session.execute(
                statement.values(
                    tier1a_status="FAILED" if error else "READY",
                    tier1a_result=result if error is None else {"error": error},
                    worker_id=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                    next_attempt_at=None,
                )
            )

    async def record_tier1a_failure(
        self,
        snapshot_id: str,
        snapshot_version: str,
        *,
        error: str,
        worker_id: str,
        max_attempts: int,
        backoff_base_seconds: int,
        now: datetime | None = None,
    ) -> str | None:
        """Back off a failed claim or make it terminal after max attempts."""
        current = now or datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(SnapshotIngest)
                .where(
                    SnapshotIngest.snapshot_id == snapshot_id,
                    SnapshotIngest.snapshot_version == snapshot_version,
                    SnapshotIngest.tier1a_status == "RUNNING",
                    SnapshotIngest.worker_id == worker_id,
                )
                .with_for_update()
            )
            if row is None:
                return None
            terminal = row.attempt_count >= max_attempts
            row.tier1a_status = "FAILED" if terminal else "PENDING"
            row.tier1a_result = {
                "last_error": error,
                "attempt_count": row.attempt_count,
            }
            row.worker_id = None
            row.lease_expires_at = None
            row.heartbeat_at = None
            row.next_attempt_at = (
                None
                if terminal
                else current
                + timedelta(
                    seconds=backoff_base_seconds * (2 ** (row.attempt_count - 1))
                )
            )
            return row.tier1a_status

    async def invalidate(
        self, snapshot_id: str, snapshot_version: str, reason: str
    ) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(
                SnapshotIngest,
                (snapshot_id, snapshot_version),
                with_for_update=True,
            )
            if row is None:
                row = SnapshotIngest(
                    snapshot_id=snapshot_id,
                    snapshot_version=snapshot_version,
                    status="INVALID",
                    invalid_reason=reason,
                )
                session.add(row)
            elif row.status != "COMPLETE":
                self._invalidate(row, reason)

    async def cleanup_chunks(self, snapshot_id: str, snapshot_version: str) -> int:
        async with self.sessions.begin() as session:
            result = await session.execute(
                delete(SnapshotChunk).where(
                    SnapshotChunk.snapshot_id == snapshot_id,
                    SnapshotChunk.snapshot_version == snapshot_version,
                )
            )
            return int(result.rowcount or 0)

    async def expire_receiving(
        self,
        *,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> int:
        """Expire incomplete assemblies and release their retained payload bytes."""
        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(seconds=ttl_seconds)
        async with self.sessions.begin() as session:
            rows = list(
                (
                    await session.scalars(
                        select(SnapshotIngest)
                        .where(
                            SnapshotIngest.status == "RECEIVING",
                            SnapshotIngest.updated_at < cutoff,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for row in rows:
                row.status = "EXPIRED"
                row.invalid_reason = "snapshot assembly exceeded receiving TTL"
                row.tier1a_status = None
                await session.execute(
                    delete(SnapshotChunk).where(
                        SnapshotChunk.snapshot_id == row.snapshot_id,
                        SnapshotChunk.snapshot_version == row.snapshot_version,
                    )
                )
                row.received_chunk_count = 0
            return len(rows)

    @staticmethod
    def _invalidate(row: SnapshotIngest, reason: str) -> None:
        row.status = "INVALID"
        row.invalid_reason = reason
        row.tier1a_status = None

    @staticmethod
    def _result(
        row: SnapshotIngest | None,
        *,
        duplicate: bool = False,
        completed_now: bool = False,
        canonical_payload: dict[str, Any] | None = None,
    ) -> IngestResult:
        if row is None:
            raise RuntimeError("snapshot ingest row is unavailable")
        return IngestResult(
            snapshot_id=row.snapshot_id,
            snapshot_version=row.snapshot_version,
            status=row.status,
            duplicate=duplicate,
            completed_now=completed_now,
            invalid_reason=row.invalid_reason,
            canonical_payload=canonical_payload,
        )
