"""Durable, transaction-ordered invalidations for live clients.

Journal rows contain resource identities and invalidation scopes only. Business
payloads remain behind the existing REST resources.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from .models import ChangeEventClockModel, ChangeEventModel


EVENT_TYPES = frozenset(
    {"quality.changed", "snapshot.changed", "topology.changed"}
)
INVALIDATION_SCOPES = frozenset(
    {"catalog", "quality-summary", "chain-list", "chain-detail", "topology", "evolution"}
)
MAX_REPLAY_BATCH = 100
MAX_CLEANUP_BATCH = 1000
DEFAULT_RETENTION = timedelta(hours=24)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ChangeJournalUnavailable(RuntimeError):
    """The migration-seeded clock row is missing or unreadable."""


@dataclass(frozen=True)
class ChangeEvent:
    epoch: UUID
    revision: int
    event_type: str
    snapshot_id: str | None
    snapshot_version: str | None
    chain_id: str | None
    topology_version: str | None
    identity_digest: str | None
    invalidates: tuple[str, ...]
    created_at: datetime

    @property
    def event_id(self) -> str:
        return f"{self.epoch}:{self.revision}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "change-event-v1",
            "event_type": self.event_type,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "chain_id": self.chain_id,
            "topology_version": self.topology_version,
            "identity_digest": self.identity_digest,
            "invalidates": list(self.invalidates),
        }


@dataclass(frozen=True)
class JournalPosition:
    epoch: UUID
    min_revision: int
    revision: int


def _validate_event(
    *,
    event_type: str,
    snapshot_id: str | None,
    snapshot_version: str | None,
    chain_id: str | None,
    topology_version: str | None,
    identity_digest: str | None,
    invalidates: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    if event_type not in EVENT_TYPES:
        raise ValueError("unsupported change event type")
    for name, value in (
        ("snapshot_id", snapshot_id),
        ("snapshot_version", snapshot_version),
        ("chain_id", chain_id),
        ("topology_version", topology_version),
    ):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"invalid {name}")
    if identity_digest is not None and (
        not isinstance(identity_digest, str) or _SHA256_RE.fullmatch(identity_digest) is None
    ):
        raise ValueError("identity_digest must be a lowercase SHA-256 digest")
    if not isinstance(invalidates, (tuple, list)) or not invalidates:
        raise ValueError("at least one invalidation scope is required")
    if any(not isinstance(scope, str) or scope not in INVALIDATION_SCOPES for scope in invalidates):
        raise ValueError("unsupported invalidation scope")
    return tuple(sorted(set(invalidates)))


def _event_from_row(row: ChangeEventModel) -> ChangeEvent:
    return ChangeEvent(
        epoch=row.epoch,
        revision=row.revision,
        event_type=row.event_type,
        snapshot_id=row.snapshot_id,
        snapshot_version=row.snapshot_version,
        chain_id=row.chain_id,
        topology_version=row.topology_version,
        identity_digest=row.identity_digest,
        invalidates=tuple(row.invalidates),
        created_at=row.created_at,
    )


def live_updates_enabled() -> bool:
    """Event publication stays opt-in until isolated acceptance passes."""
    return os.environ.get("NOCPRO_LIVE_UPDATES_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def append_change(
    session,
    *,
    event_type: str,
    snapshot_id: str | None = None,
    snapshot_version: str | None = None,
    chain_id: str | None = None,
    topology_version: str | None = None,
    identity_digest: str | None = None,
    invalidates: tuple[str, ...] | list[str],
) -> ChangeEvent:
    """Append inside the caller's business transaction; never commit here.

    Updating the single clock row both allocates the next revision and holds a
    PostgreSQL row lock until the caller commits. Therefore a later writer
    cannot allocate/commit a greater revision before this transaction finishes.
    See PostgreSQL 16 Explicit Locking, row-level locks:
    https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS
    """
    normalized_scopes = _validate_event(
        event_type=event_type,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        chain_id=chain_id,
        topology_version=topology_version,
        identity_digest=identity_digest,
        invalidates=invalidates,
    )
    # UPDATE's row lock is transaction-scoped in PostgreSQL. The clock and
    # event insert share the business mutation's transaction by contract.
    statement = (
        update(ChangeEventClockModel)
        .where(ChangeEventClockModel.singleton_id == 1)
        .values(revision=ChangeEventClockModel.revision + 1)
        .returning(ChangeEventClockModel.epoch, ChangeEventClockModel.revision)
    )
    position = (await session.execute(statement)).one_or_none()
    if position is None:
        raise ChangeJournalUnavailable("change event clock row is missing")
    epoch, revision = position
    record = ChangeEventModel(
        epoch=epoch,
        revision=revision,
        event_type=event_type,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        chain_id=chain_id,
        topology_version=topology_version,
        identity_digest=identity_digest,
        invalidates=list(normalized_scopes),
    )
    session.add(record)
    await session.flush()
    created_at = record.created_at or datetime.now(timezone.utc)
    return ChangeEvent(
        epoch=epoch,
        revision=revision,
        event_type=event_type,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        chain_id=chain_id,
        topology_version=topology_version,
        identity_digest=identity_digest,
        invalidates=normalized_scopes,
        created_at=created_at,
    )


async def append_change_if_enabled(session, **event_fields) -> ChangeEvent | None:
    """Write-hook adapter; REST remains authoritative while live updates are off."""
    if not live_updates_enabled():
        return None
    return await append_change(session, **event_fields)


async def journal_position(sessions: async_sessionmaker) -> JournalPosition:
    """Return epoch, first retained revision, and current revision in one read."""
    retained_min = (
        select(func.min(ChangeEventModel.revision))
        .where(ChangeEventModel.epoch == ChangeEventClockModel.epoch)
        .scalar_subquery()
    )
    async with sessions() as session:
        row = (
            await session.execute(
                select(
                    ChangeEventClockModel.epoch,
                    ChangeEventClockModel.revision,
                    retained_min,
                ).where(ChangeEventClockModel.singleton_id == 1)
            )
        ).one_or_none()
    if row is None:
        raise ChangeJournalUnavailable("change event clock row is missing")
    epoch, revision, first_retained = row
    return JournalPosition(
        epoch=epoch,
        min_revision=int(first_retained) if first_retained is not None else int(revision) + 1,
        revision=int(revision),
    )


async def read_changes_after(
    sessions: async_sessionmaker,
    epoch: UUID,
    revision: int,
    *,
    limit: int = MAX_REPLAY_BATCH,
) -> list[ChangeEvent]:
    if not isinstance(epoch, UUID) or revision < 0:
        raise ValueError("invalid change journal cursor")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_REPLAY_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_REPLAY_BATCH}")
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(ChangeEventModel)
                .where(
                    ChangeEventModel.epoch == epoch,
                    ChangeEventModel.revision > revision,
                )
                .order_by(ChangeEventModel.revision.asc())
                .limit(limit)
            )
        ).all()
    return [_event_from_row(row) for row in rows]


async def purge_expired_events(
    sessions: async_sessionmaker,
    *,
    retention: timedelta = DEFAULT_RETENTION,
    limit: int = MAX_CLEANUP_BATCH,
    now: datetime | None = None,
) -> int:
    """Delete only bounded old journal rows; business artifacts are untouched."""
    if retention <= timedelta(0):
        raise ValueError("retention must be positive")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_CLEANUP_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_CLEANUP_BATCH}")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    cutoff = current - retention
    async with sessions.begin() as session:
        key_rows = (
            await session.execute(
                select(ChangeEventModel.epoch, ChangeEventModel.revision)
                .where(ChangeEventModel.created_at < cutoff)
                .order_by(
                    ChangeEventModel.created_at.asc(),
                    ChangeEventModel.epoch.asc(),
                    ChangeEventModel.revision.asc(),
                )
                .limit(limit)
            )
        ).all()
        if not key_rows:
            return 0
        keys = [(row[0], row[1]) for row in key_rows]
        result = await session.execute(
            delete(ChangeEventModel).where(
                tuple_(ChangeEventModel.epoch, ChangeEventModel.revision).in_(keys)
            )
        )
        return int(result.rowcount or 0)


async def rotate_journal_epoch(sessions: async_sessionmaker) -> JournalPosition:
    """Invalidate all old cursors after a database restore or journal reset."""
    new_epoch = uuid4()
    async with sessions.begin() as session:
        result = await session.execute(
            update(ChangeEventClockModel)
            .where(ChangeEventClockModel.singleton_id == 1)
            .values(epoch=new_epoch, revision=0)
        )
        if result.rowcount != 1:
            raise ChangeJournalUnavailable("change event clock row is missing")
    return JournalPosition(epoch=new_epoch, min_revision=1, revision=0)
