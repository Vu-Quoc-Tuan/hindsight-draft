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
from history import (
    HistoricalChainState,
    HistoricalEpisode,
    HistoricalEvidenceConfig,
    HistoricalTaxonomy,
    TaxonomyTokens,
    build_historical_model,
)
from temporal_delay import (
    DelayEstimator,
    DelayModelConfig,
    DelayObservation,
    DelayRelationKey,
    build_delay_model,
)
from history import TaxonomyLevel
from similar_chains import build_fingerprint, find_similar_chains
from sqlalchemy import func, select
from nocpro_api.persistence.models import SnapshotChunk, SnapshotIngest


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


def _historical_model():
    taxonomy = HistoricalTaxonomy(
        "synthetic-taxonomy", "v1", {"A": TaxonomyTokens(type="A"), "B": TaxonomyTokens(type="B")}
    )
    a, b, x, y = (TaxonomyTokens(type=value) for value in "ABXY")
    episodes = (
        HistoricalEpisode("e1", (HistoricalChainState("s1", "1", "2026-01-01T00:00:00Z", ((a, b),)),)),
        HistoricalEpisode("e2", (HistoricalChainState("s2", "1", "2026-01-01T00:01:00Z", ((a, b),)),)),
        HistoricalEpisode("e3", (HistoricalChainState("s3", "1", "2026-01-01T00:02:00Z", ((a, b),)),)),
        HistoricalEpisode("e4", (HistoricalChainState("s4", "1", "2026-01-01T00:03:00Z", ((a, x),)),)),
        HistoricalEpisode("e5", (HistoricalChainState("s5", "1", "2026-01-01T00:04:00Z", ((b, y),)),)),
        HistoricalEpisode("e6", (HistoricalChainState("s6", "1", "2026-01-01T00:05:00Z", ((x, y),)),)),
        HistoricalEpisode("e7", (HistoricalChainState("s7", "1", "2026-01-01T00:06:00Z", ((x, y),)),)),
    )
    return (
        build_historical_model(
            episodes,
            training_cutoff="2026-08-29T00:00:00Z",
            lineage_prefix_fingerprint="test-prefix",
            taxonomy=taxonomy,
            config=HistoricalEvidenceConfig("synthetic-history", 3, 4.0, 4.0),
        ),
        taxonomy,
    )


def test_historical_model_persists_and_hydrates_after_workspace_restart():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise():
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        snapshot_id = f"pg-history-{uuid4().hex}"
        payload = _payload(snapshot_id)
        payload["alarms"][0]["alarm_name"] = "A"
        payload["alarms"][1]["alarm_name"] = "B"
        try:
            await repository.ingest_direct(payload)
            first_workspace = Workspace()
            first_coordinator = Tier1ACoordinator(repository, first_workspace)
            assert await first_coordinator.run(snapshot_id, "1") is not None
            model, taxonomy = _historical_model()
            await repository.persist_historical_evidence_model(
                snapshot_id=snapshot_id,
                snapshot_version="1",
                model=model,
                taxonomy=taxonomy,
            )
            # A fresh workspace simulates API/process restart: no in-memory H.
            restarted_workspace = Workspace()
            restarted_coordinator = Tier1ACoordinator(repository, restarted_workspace)
            assert await restarted_coordinator.hydrate_active() is not None
            values = restarted_workspace.pair_why("c1", "a1", "a2")
            history = next(value for value in values if value.channel_id == "H")
            assert history.availability is True
            assert history.supports is True
            assert history.source_ref == model.model_version
            assert history.evidence_metadata["training_cutoff"] == model.training_cutoff
            first_workspace.close()
            restarted_workspace.close()
        finally:
            await database.close()

    import asyncio

    asyncio.run(exercise())


def test_temporal_delay_model_persists_and_hydrates_pair_why_after_restart():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise():
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        snapshot_id = f"pg-delay-{uuid4().hex}"
        payload = _payload(snapshot_id)
        payload["alarms"][0].update({"alarm_name": "A", "canonical_start_time": "2026-08-29T00:00:00Z"})
        payload["alarms"][1].update({"alarm_name": "B", "canonical_start_time": "2026-08-29T00:00:05Z"})
        try:
            await repository.ingest_direct(payload)
            first_workspace = Workspace()
            first_coordinator = Tier1ACoordinator(repository, first_workspace)
            assert await first_coordinator.run(snapshot_id, "1") is not None
            taxonomy = HistoricalTaxonomy(
                "synthetic-temporal-taxonomy", "v1",
                {"A": TaxonomyTokens(type="A"), "B": TaxonomyTokens(type="B")},
            )
            config = DelayModelConfig(
                "synthetic-delay", 2, 4, 0.4, 42, (2.0,), (2.0,), (1.0,),
                DelayEstimator.HISTOGRAM, 2.0,
                fallback_histogram_bin_width_seconds=2.0,
            )
            key = DelayRelationKey(TaxonomyLevel.TYPE, "A", "B")
            model = build_delay_model(
                [DelayObservation(f"e{i}", f"a{i}", f"b{i}", key, 5.0) for i in range(4)],
                training_cutoff="2026-08-29T00:00:00Z",
                lineage_prefix_fingerprint="temporal-prefix",
                taxonomy_source_id=taxonomy.source_id,
                taxonomy_source_version=taxonomy.source_version,
                config=config,
            )
            await repository.persist_temporal_delay_model(
                snapshot_id=snapshot_id, snapshot_version="1", model=model, taxonomy=taxonomy,
            )
            # Fresh process/workspace: it must hydrate the immutable artifact,
            # not refit it from whatever data happens to exist at restart time.
            restarted_workspace = Workspace()
            restarted_coordinator = Tier1ACoordinator(repository, restarted_workspace)
            assert await restarted_coordinator.hydrate_active() is not None
            values = restarted_workspace.pair_why("c1", "a1", "a2")
            delay = next(value for value in values if value.channel_id == "T_delay")
            assert delay.availability is True
            assert delay.supports is True
            assert delay.source_ref == model.model_version
            assert delay.evidence_metadata["training_cutoff"] == model.training_cutoff
            assert delay.evidence_metadata["direction"] == "A->B"
            first_workspace.close()
            restarted_workspace.close()
        finally:
            await database.close()

    import asyncio

    asyncio.run(exercise())


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


def test_chunk_cleanup_requires_ready_and_preserves_canonical_snapshot():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def chunk_count(database, snapshot_id: str) -> int:
        async with database.sessions() as session:
            return int(
                await session.scalar(
                    select(func.count(SnapshotChunk.chunk_index)).where(
                        SnapshotChunk.snapshot_id == snapshot_id,
                        SnapshotChunk.snapshot_version == "1",
                    )
                )
                or 0
            )

    async def canonical_payload(database, snapshot_id: str) -> dict:
        async with database.sessions() as session:
            payload = await session.scalar(
                select(SnapshotIngest.canonical_payload).where(
                    SnapshotIngest.snapshot_id == snapshot_id,
                    SnapshotIngest.snapshot_version == "1",
                )
            )
            assert payload is not None
            return payload

    async def exercise():
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        snapshot_id = f"pg-cleanup-{uuid4().hex}"
        topic = f"test-cleanup-{uuid4().hex}"
        payload = _payload(snapshot_id)
        events = _events(payload, chunk_size=16)
        try:
            for offset, raw in enumerate(events):
                await repository.record_kafka_event(
                    parse_snapshot_event(raw), topic=topic, partition=0, offset=offset
                )

            retained = await chunk_count(database, snapshot_id)
            assert retained > 1
            # COMPLETE alone is intentionally insufficient for cleanup.
            assert await repository.cleanup_chunks(snapshot_id, "1") == 0
            assert await chunk_count(database, snapshot_id) == retained

            claim = await repository.claim_next_tier1a(
                worker_id="cleanup-worker", lease_seconds=120
            )
            assert claim is not None
            deleted = await repository.finish_tier1a(
                snapshot_id,
                "1",
                result={"chain_count": 1},
                worker_id="cleanup-worker",
                delete_chunks_after_ready=True,
            )
            assert deleted == retained
            assert await chunk_count(database, snapshot_id) == 0
            # Replays of cleanup are harmless, and the durable canonical payload
            # remains the source used by restart hydration.
            assert await repository.cleanup_chunks(snapshot_id, "1") == 0
            assert await canonical_payload(database, snapshot_id) == payload
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


def test_reused_kafka_offset_after_broker_reset_processes_new_snapshot():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise():
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        first_id = f"before-reset-{uuid4().hex}"
        second_id = f"after-reset-{uuid4().hex}"
        topic = f"test-reset-{uuid4().hex}"
        first = parse_snapshot_event(_events(_payload(first_id))[0])
        second = parse_snapshot_event(_events(_payload(second_id))[0])
        try:
            initial = await repository.record_kafka_event(
                first, topic=topic, partition=2, offset=0
            )
            replayed_coordinate = await repository.record_kafka_event(
                second, topic=topic, partition=2, offset=0
            )

            assert initial.snapshot_id == first_id
            assert replayed_coordinate.snapshot_id == second_id
            assert replayed_coordinate.status == "RECEIVING"
            assert replayed_coordinate.duplicate is False
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
            assert dag.canonical_lineage(LineageNodeKey(s1, "1", "A")) == dag.canonical_lineage(
                LineageNodeKey(s2, "1", "B")
            )
            assert dag.canonical_lineage(LineageNodeKey(s1, "1", "X")) != dag.canonical_lineage(
                LineageNodeKey(s2, "1", "B")
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
