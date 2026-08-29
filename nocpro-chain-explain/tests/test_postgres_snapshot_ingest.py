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
from nocpro_api.tier1a_coordinator import Tier1ACoordinator
from nocpro_api.workspace import Workspace
from evolution import LineageNodeKey
from similar_chains import build_fingerprint, find_similar_chains
from sqlalchemy import func, select
from nocpro_api.persistence.models import SnapshotIngest


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


def _lineage_payload(
    snapshot_id: str, snapshot_time: str, chains: dict[str, list[str]]
) -> dict:
    alarms = []
    memberships = []
    seen = set()
    for chain_id, members in chains.items():
        for alarm_id in members:
            if alarm_id not in seen:
                alarms.append(
                    {
                        "alarm_id": alarm_id,
                        "snapshot_id": snapshot_id,
                        "source_kind": "SYNTHETIC_TEST",
                        "provenance_class": "SYSTEM_FACT",
                        "device_code": chain_id,
                        "raw": {"device_type_name": chain_id},
                    }
                )
                seen.add(alarm_id)
            memberships.append(
                {
                    "snapshot_id": snapshot_id,
                    "chain_id": chain_id,
                    "alarm_id": alarm_id,
                    "source_kind": "SYNTHETIC_TEST",
                }
            )
    return {
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": snapshot_id,
            "snapshot_version": "1",
            "snapshot_time": snapshot_time,
            "status": "COMPLETE",
            "source": "lineage-test",
            "source_kind": "SYNTHETIC_TEST",
            "produced_at": snapshot_time,
        },
        "alarms": alarms,
        "chains": [
            {
                "snapshot_id": snapshot_id,
                "chain_id": chain_id,
                "member_count": len(members),
                "source_kind": "SYNTHETIC_TEST",
                "provenance_class": "SYSTEM_FACT",
            }
            for chain_id, members in chains.items()
        ],
        "memberships": memberships,
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
            async with database.sessions() as session:
                latest_time = await session.scalar(
                    select(func.max(SnapshotIngest.logical_snapshot_time))
                )
            oldest_time = (latest_time or datetime.now(timezone.utc)) + timedelta(
                minutes=1
            )
            replay_time = oldest_time + timedelta(minutes=1)
            newest_time = oldest_time + timedelta(minutes=2)
            # Deliberately ingest the newer snapshot first; claim order remains logical.
            await repository.ingest_direct(
                _payload(newer_id, snapshot_time=newest_time.isoformat())
            )
            await repository.ingest_direct(
                _payload(older_id, snapshot_time=oldest_time.isoformat())
            )

            base = datetime.now(timezone.utc)
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
                _payload(replay_id, snapshot_time=replay_time.isoformat())
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


def test_global_lineage_and_similarity_survive_restart_and_exclude_same_episode():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise():
        from datetime import datetime, timedelta, timezone

        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        suffix = uuid4().hex
        s1, s2 = f"episode-1-{suffix}", f"episode-2-{suffix}"
        async with database.sessions() as session:
            latest_time = await session.scalar(
                select(func.max(SnapshotIngest.logical_snapshot_time))
            )
        base_time = (latest_time or datetime.now(timezone.utc)) + timedelta(minutes=1)
        first = _lineage_payload(
            s1,
            base_time.isoformat(),
            {
                "A": ["a1", "a2", "a3", "a4"],
                "X": ["x1", "x2", "x3", "x4"],
            },
        )
        second = _lineage_payload(
            s2,
            (base_time + timedelta(minutes=1)).isoformat(),
            {
                "B": ["a1", "a2", "a3", "a4"],
                "Y": ["x1", "x2", "x3", "x4"],
            },
        )
        workspace = Workspace()
        coordinator = Tier1ACoordinator(repository, workspace, worker_id="lineage-test")
        workspace.attach_persistence(repository, coordinator)
        try:
            for payload in (first, second):
                result = await repository.ingest_direct(payload)
                await coordinator.run(result.snapshot_id, result.snapshot_version)
                while True:
                    completed_lineage = await coordinator.run_lineage_pending_once()
                    assert completed_lineage is not None
                    if completed_lineage == (
                        result.snapshot_id,
                        result.snapshot_version,
                    ):
                        break
                while True:
                    completed_similarity = await coordinator.run_similarity_pending_once()
                    assert completed_similarity is not None
                    if completed_similarity == (
                        result.snapshot_id,
                        result.snapshot_version,
                    ):
                        break

            dag = await repository.load_episode_dag()
            assert dag.canonical_lineage(LineageNodeKey(s1, "A")) == dag.canonical_lineage(
                LineageNodeKey(s2, "B")
            )
            assert dag.canonical_lineage(LineageNodeKey(s1, "X")) != dag.canonical_lineage(
                LineageNodeKey(s2, "B")
            )
            counts = (len(dag.nodes), len(dag.edges), len(dag.components))
            assert await coordinator.run_lineage_pending_once() is None
            restarted_dag = await repository.load_episode_dag()
            assert (len(restarted_dag.nodes), len(restarted_dag.edges), len(restarted_dag.components)) == counts

            restarted_workspace = Workspace()
            restarted = Tier1ACoordinator(
                repository, restarted_workspace, worker_id="restart-test"
            )
            restarted_workspace.attach_persistence(repository, restarted)
            await restarted.hydrate_active()
            assert restarted_workspace.similarity_index is not None
            submission = restarted_workspace.submit_deep_dive("B")
            completed = restarted_workspace.jobs.wait(submission.job_id, timeout=5)
            assert completed.result.similarity_status == "AVAILABLE"
            package = restarted_workspace.require_package()
            summary = restarted_workspace.precompute.chains["B"]
            target = build_fingerprint(
                "B",
                package.alarms_of("B"),
                lineage_component_id=restarted_workspace.lineage_by_chain["B"],
                identity_descriptors=summary.descriptors.identity,
                duration_seconds=package.chains["B"].event_span_seconds,
            )
            result_ids = {
                item.chain_id
                for item in find_similar_chains(
                    target,
                    list(restarted_workspace.similarity_index.corpus),
                    model=restarted_workspace.similarity_index.model,
                    top_k=len(restarted_workspace.similarity_index.corpus),
                    exclude_same_lineage=True,
                )
            }
            assert f"{s1}::A" not in result_ids
            assert f"{s1}::X" in result_ids
            restarted_workspace.close()
        finally:
            workspace.close()
            await database.close()

    import asyncio

    asyncio.run(exercise())
