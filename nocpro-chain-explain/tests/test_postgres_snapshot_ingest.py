from __future__ import annotations

import base64
import hashlib
import json
import os
from uuid import uuid4

import pytest
import zstandard

from nocpro_api.ingest import parse_snapshot_event
from nocpro_api.persistence import Database, SnapshotRepository


pytestmark = pytest.mark.postgres


def _payload(snapshot_id: str, *, snapshot_time: str = "2026-08-29T00:00:00Z") -> dict:
    return {
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": snapshot_id,
            "snapshot_version": "1",
            "snapshot_time": snapshot_time,
            "status": "COMPLETE",
            "source": "postgres-test",
            "source_kind": "SYNTHETIC_TEST",
            "produced_at": "2026-08-29T00:00:01Z",
        },
        "alarms": [
            {
                "alarm_id": "a1",
                "snapshot_id": snapshot_id,
                "source_kind": "SYNTHETIC_TEST",
                "provenance_class": "SYSTEM_FACT",
                "raw": {},
            },
            {
                "alarm_id": "a2",
                "snapshot_id": snapshot_id,
                "source_kind": "SYNTHETIC_TEST",
                "provenance_class": "SYSTEM_FACT",
                "raw": {},
            },
        ],
        "chains": [
            {
                "chain_id": "c1",
                "snapshot_id": snapshot_id,
                "member_count": 2,
                "source_kind": "SYNTHETIC_TEST",
                "provenance_class": "SYSTEM_FACT",
            }
        ],
        "memberships": [
            {
                "chain_id": "c1",
                "alarm_id": alarm_id,
                "snapshot_id": snapshot_id,
                "source_kind": "SYNTHETIC_TEST",
            }
            for alarm_id in ("a1", "a2")
        ],
    }


def _events(payload: dict, chunk_size: int = 64) -> list[dict]:
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False
    ).encode()
    compressed = zstandard.ZstdCompressor().compress(canonical)
    checksum = hashlib.sha256(canonical).hexdigest()
    parts = [compressed[i : i + chunk_size] for i in range(0, len(compressed), chunk_size)]
    snapshot = payload["snapshot"]
    chunks = [
        {
            "schema_version": "v1",
            "event_type": "SNAPSHOT_CHUNK",
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_version": snapshot["snapshot_version"],
            "chunk_index": index,
            "chunk_count": len(parts),
            "payload_format": "json",
            "compression": "zstd",
            "chunk_checksum": hashlib.sha256(part).hexdigest(),
            "snapshot_checksum": checksum,
            "payload": base64.b64encode(part).decode(),
        }
        for index, part in enumerate(parts)
    ]
    barrier = {
        "schema_version": "v1",
        "event_type": "SNAPSHOT_COMPLETE",
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_version": snapshot["snapshot_version"],
        "expected_chunk_count": len(parts),
        "total_uncompressed_bytes": len(canonical),
        "snapshot_checksum": checksum,
        "produced_at": snapshot["produced_at"],
        "source": "nocpro-mock",
        "source_kind": snapshot["source_kind"],
    }
    return [*chunks, barrier]


def test_postgres_barrier_assembly_is_idempotent_and_claims_tier1a_once():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise():
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        snapshot_id = f"pg-{uuid4().hex}"
        topic = f"test-{uuid4().hex}"
        payload = _payload(snapshot_id)
        events = _events(payload)
        chunks, barrier = events[:-1], events[-1]
        try:
            early = await repository.record_kafka_event(
                parse_snapshot_event(barrier), topic=topic, partition=0, offset=0
            )
            assert early.status == "RECEIVING"
            assert early.completed_now is False

            result = early
            for offset, raw in enumerate(chunks, start=1):
                result = await repository.record_kafka_event(
                    parse_snapshot_event(raw),
                    topic=topic,
                    partition=0,
                    offset=offset,
                )
            assert result.status == "COMPLETE"
            assert result.completed_now is True
            assert result.canonical_payload == payload

            repeated = await repository.record_kafka_event(
                parse_snapshot_event(barrier),
                topic=topic,
                partition=0,
                offset=len(chunks) + 1,
            )
            assert repeated.status == "COMPLETE"
            assert repeated.duplicate is True
            assert repeated.completed_now is False

            direct = await repository.ingest_direct(payload)
            assert direct.duplicate is True

            first_claim = await repository.claim_next_tier1a(
                worker_id="test-worker", lease_seconds=120
            )
            second_claim = await repository.claim_next_tier1a(
                worker_id="test-worker-2", lease_seconds=120
            )
            assert first_claim is not None
            assert first_claim.payload == payload
            assert second_claim is None
            await repository.finish_tier1a(
                snapshot_id,
                "1",
                result={"chain_count": 1},
                worker_id="test-worker",
            )
        finally:
            await database.close()

    import asyncio

    asyncio.run(exercise())


def test_conflicting_duplicate_chunk_marks_snapshot_invalid():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise():
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        snapshot_id = f"pg-conflict-{uuid4().hex}"
        topic = f"test-{uuid4().hex}"
        raw = _events(_payload(snapshot_id))[0]
        try:
            first = await repository.record_kafka_event(
                parse_snapshot_event(raw), topic=topic, partition=0, offset=0
            )
            assert first.status == "RECEIVING"

            conflicting = dict(raw)
            changed_payload = base64.b64decode(raw["payload"]) + b"changed"
            conflicting["payload"] = base64.b64encode(changed_payload).decode()
            conflicting["chunk_checksum"] = hashlib.sha256(changed_payload).hexdigest()
            result = await repository.record_kafka_event(
                parse_snapshot_event(conflicting),
                topic=topic,
                partition=0,
                offset=1,
            )
            assert result.status == "INVALID"
            assert "conflicting duplicate chunk" in (result.invalid_reason or "")
            assert (
                await repository.claim_next_tier1a(
                    worker_id="test-worker", lease_seconds=120
                )
                is None
            )
        finally:
            await database.close()

    import asyncio

    asyncio.run(exercise())


def test_tier1a_claim_and_active_selection_follow_logical_snapshot_time():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise():
        from datetime import datetime, timedelta, timezone

        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        suffix = uuid4().hex
        newer_id = f"logical-new-{suffix}"
        older_id = f"logical-old-{suffix}"
        replay_id = f"logical-replay-{suffix}"
        try:
            # Deliberately ingest the newer snapshot first; claim order remains logical.
            await repository.ingest_direct(
                _payload(newer_id, snapshot_time="2026-08-29T10:00:00Z")
            )
            await repository.ingest_direct(
                _payload(older_id, snapshot_time="2026-08-29T09:55:00Z")
            )

            base = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc)
            first = await repository.claim_next_tier1a(
                worker_id="worker-a", lease_seconds=60, now=base
            )
            assert first is not None and first.snapshot_id == older_id

            # A live lease cannot be stolen; it becomes claimable only after expiry.
            assert (
                await repository.claim_next_tier1a(
                    worker_id="worker-b", lease_seconds=60, now=base + timedelta(seconds=30)
                )
            ).snapshot_id == newer_id
            reclaimed = await repository.claim_next_tier1a(
                worker_id="worker-c", lease_seconds=60, now=base + timedelta(seconds=61)
            )
            assert reclaimed is not None and reclaimed.snapshot_id == older_id
            await repository.finish_tier1a(
                older_id, "1", result={}, worker_id="worker-c"
            )

            # Finish the already claimed newer job and verify it becomes derived ACTIVE.
            await repository.finish_tier1a(
                newer_id, "1", result={}, worker_id="worker-b"
            )
            active = await repository.latest_ready_payload()
            assert active is not None
            assert active["snapshot"]["snapshot_id"] == newer_id

            # A logically older replay completed later must not replace ACTIVE.
            await repository.ingest_direct(
                _payload(replay_id, snapshot_time="2026-08-29T09:58:00Z")
            )
            replay = await repository.claim_next_tier1a(
                worker_id="worker-r", lease_seconds=60, now=base + timedelta(minutes=2)
            )
            assert replay is not None and replay.snapshot_id == replay_id
            await repository.finish_tier1a(
                replay_id, "1", result={}, worker_id="worker-r"
            )
            active = await repository.latest_ready_payload()
            assert active is not None
            assert active["snapshot"]["snapshot_id"] == newer_id
        finally:
            await database.close()

    import asyncio

    asyncio.run(exercise())


def test_tier1a_failure_backoff_becomes_terminal_on_fifth_attempt():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise():
        from datetime import datetime, timedelta, timezone

        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        snapshot_id = f"retry-{uuid4().hex}"
        base = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        try:
            await repository.ingest_direct(_payload(snapshot_id))
            elapsed = 0
            for attempt, delay in enumerate((2, 4, 8, 16), start=1):
                claim = await repository.claim_next_tier1a(
                    worker_id=f"worker-{attempt}",
                    lease_seconds=60,
                    now=base + timedelta(seconds=elapsed),
                )
                assert claim is not None and claim.attempt_count == attempt
                status = await repository.record_tier1a_failure(
                    snapshot_id,
                    "1",
                    error=f"failure-{attempt}",
                    worker_id=f"worker-{attempt}",
                    max_attempts=5,
                    backoff_base_seconds=2,
                    now=base + timedelta(seconds=elapsed),
                )
                assert status == "PENDING"
                assert (
                    await repository.claim_next_tier1a(
                        worker_id="too-early",
                        lease_seconds=60,
                        now=base + timedelta(seconds=elapsed + delay - 1),
                    )
                    is None
                )
                elapsed += delay

            fifth = await repository.claim_next_tier1a(
                worker_id="worker-5",
                lease_seconds=60,
                now=base + timedelta(seconds=elapsed),
            )
            assert fifth is not None and fifth.attempt_count == 5
            status = await repository.record_tier1a_failure(
                snapshot_id,
                "1",
                error="failure-5",
                worker_id="worker-5",
                max_attempts=5,
                backoff_base_seconds=2,
                now=base + timedelta(seconds=elapsed),
            )
            assert status == "FAILED"
            assert (
                await repository.claim_next_tier1a(
                    worker_id="worker-6",
                    lease_seconds=60,
                    now=base + timedelta(days=1),
                )
                is None
            )
        finally:
            await database.close()

    import asyncio

    asyncio.run(exercise())
