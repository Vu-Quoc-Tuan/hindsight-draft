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


def _payload(snapshot_id: str) -> dict:
    return {
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": snapshot_id,
            "snapshot_version": "1",
            "snapshot_time": "2026-08-29T00:00:00Z",
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

            first_claim = await repository.claim_tier1a(snapshot_id, "1")
            second_claim = await repository.claim_tier1a(snapshot_id, "1")
            assert first_claim == payload
            assert second_claim is None
            await repository.finish_tier1a(
                snapshot_id, "1", result={"chain_count": 1}
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
            assert await repository.claim_tier1a(snapshot_id, "1") is None
        finally:
            await database.close()

    import asyncio

    asyncio.run(exercise())
