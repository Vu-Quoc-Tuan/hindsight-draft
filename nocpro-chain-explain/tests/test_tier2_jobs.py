"""Async per-chain Tier-2 execution and cache semantics (ADR-0023)."""

from __future__ import annotations

from threading import Event

import pytest

from configuration import load_analysis_config
from tier1a import CacheTier, Tier1Cache
from tier2 import JobStatus, SimilarityQueryContext, Tier2JobManager
from groups import AuditGraphMode
from similar_chains import (
    CorpusPolicy,
    ModelUpdatePolicy,
    TimedChainFingerprint,
    build_fingerprint,
    materialize_similarity_index,
)
from tests.test_tier1b_analysis import _alarm, _snapshot


def _package():
    alarms = [
        _alarm(
            f"a{i}",
            "C1",
            device_code="D1",
            node_reference="R1",
            alarm_name="DOWN",
            location_code="S1",
            canonical_start_time=f"2026-01-01T00:00:{i:02d}",
        )
        for i in range(10)
    ]
    return _snapshot(
        alarms,
        [{"chain_id": "C1", "snapshot_id": "s1", "member_count": 10}],
        [
            {"chain_id": "C1", "alarm_id": item["alarm_id"], "snapshot_id": "s1"}
            for item in alarms
        ],
    )


@pytest.fixture()
def analysis_config():
    from pathlib import Path

    return load_analysis_config(
        Path(__file__).resolve().parents[1] / "config/thresholds/v1.yaml"
    )


def test_submit_is_non_blocking_and_reports_progress(analysis_config):
    started = Event()
    release = Event()

    def blocking_analyzer(*args, **kwargs):
        started.set()
        assert release.wait(timeout=2)
        return "deep-result"

    manager = Tier2JobManager(analyzer=blocking_analyzer, max_workers=1)
    try:
        submission = manager.submit(_package(), "C1", analysis_config=analysis_config)
        assert submission.cache_hit is False
        assert started.wait(timeout=1)
        view = manager.get(submission.job_id)
        assert view.status is JobStatus.RUNNING
        assert 0 < view.progress_percent < 100
        release.set()
        completed = manager.wait(submission.job_id, timeout=2)
        assert completed.status is JobStatus.SUCCEEDED
        assert completed.progress_percent == 100
        assert completed.result == "deep-result"
    finally:
        release.set()
        manager.shutdown()


def test_success_is_cached_by_tier2_fingerprint_snapshot_and_config(analysis_config):
    calls = 0

    def analyzer(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"run": calls}

    cache = Tier1Cache()
    manager = Tier2JobManager(cache=cache, analyzer=analyzer, max_workers=1)
    try:
        assert manager.cache is cache
        first = manager.submit(_package(), "C1", analysis_config=analysis_config)
        assert manager.wait(first.job_id, timeout=2).result == {"run": 1}

        second = manager.submit(_package(), "C1", analysis_config=analysis_config)
        second_view = manager.get(second.job_id)

        assert second.cache_hit is True
        assert second_view.status is JobStatus.SUCCEEDED
        assert second_view.result == {"run": 1}
        assert calls == 1
        entries = cache.tier_entries(CacheTier.TIER_2)
        assert len(entries) == 1
        assert entries[0].key.snapshot_id == "s1"
        assert entries[0].key.config_version == "v1"
    finally:
        manager.shutdown()


def test_duplicate_inflight_submission_reuses_the_same_job(analysis_config):
    release = Event()

    def analyzer(*args, **kwargs):
        release.wait(timeout=2)
        return "ok"

    manager = Tier2JobManager(analyzer=analyzer, max_workers=1)
    try:
        package = _package()
        first = manager.submit(package, "C1", analysis_config=analysis_config)
        second = manager.submit(package, "C1", analysis_config=analysis_config)
        assert second.job_id == first.job_id
        assert second.deduplicated is True
    finally:
        release.set()
        manager.shutdown()


def test_worker_failure_is_a_failed_job_not_a_submit_error(analysis_config):
    def analyzer(*args, **kwargs):
        raise RuntimeError("audit exploded")

    manager = Tier2JobManager(analyzer=analyzer, max_workers=1)
    try:
        submission = manager.submit(_package(), "C1", analysis_config=analysis_config)
        failed = manager.wait(submission.job_id, timeout=2)
        assert failed.status is JobStatus.FAILED
        assert failed.result is None
        assert failed.error == "RuntimeError: audit exploded"
    finally:
        manager.shutdown()


def test_worker_passes_versioned_audit_balance_parameters(analysis_config):
    received = {}

    def analyzer(*args, **kwargs):
        received.update(kwargs)
        return "ok"

    with Tier2JobManager(analyzer=analyzer, max_workers=1) as manager:
        submission = manager.submit(_package(), "C1", analysis_config=analysis_config)
        completed = manager.wait(submission.job_id, timeout=2)

    assert completed.status is JobStatus.SUCCEEDED
    assert received["rho"] == analysis_config.value("audit.rho")
    assert received["min_side_size"] == analysis_config.value("audit.min_side_size")
    assert received["small_chain_threshold"] == analysis_config.value(
        "audit.small_chain_threshold"
    )


def test_unknown_chain_fails_before_scheduling(analysis_config):
    manager = Tier2JobManager(max_workers=1)
    try:
        with pytest.raises(KeyError, match="unknown chain_id"):
            manager.submit(_package(), "missing", analysis_config=analysis_config)
    finally:
        manager.shutdown()


def test_default_worker_runs_real_per_chain_audit(analysis_config):
    with Tier2JobManager(max_workers=1) as manager:
        submission = manager.submit(_package(), "C1", analysis_config=analysis_config)
        completed = manager.wait(submission.job_id, timeout=5)

    assert completed.status is JobStatus.SUCCEEDED
    assert completed.result.chain_id == "C1"
    assert completed.result.audit_graph_mode is AuditGraphMode.EXACT_FULL
    assert completed.result.config_version == "v1"
    assert completed.result.parameter_provenance["audit.rho"] == "DOCUMENTED_DEFAULT"
    assert completed.result.similar_chains == ()
    assert "caller-supplied" in completed.result.similarity_unavailable_reason


def test_versioned_similarity_context_is_used_and_part_of_cache_key(analysis_config):
    package = _package()
    alarms = package.alarms_of("C1")
    same_lineage = build_fingerprint(
        "OLD-C1", alarms, lineage_component_id="L1", duration_seconds=10
    )
    different_incident = build_fingerprint(
        "C2", alarms, lineage_component_id="L2", duration_seconds=10
    )
    index = materialize_similarity_index(
        [
            TimedChainFingerprint(same_lineage, "2025-12-31T23:58:00Z"),
            TimedChainFingerprint(different_incident, "2025-12-31T23:59:00Z"),
        ],
        model_version="sim-test-v1",
        trained_until_exclusive=package.snapshot.snapshot_time,
        corpus_policy=CorpusPolicy.HISTORY_BEFORE_SNAPSHOT,
        model_update_policy=ModelUpdatePolicy.SNAPSHOT_VERSIONED,
        taxonomy_policy="TEST_EMPTY",
    )
    context = SimilarityQueryContext(
        index=index,
        target_lineage_component_id="L1",
    )

    with Tier2JobManager(max_workers=1) as manager:
        submission = manager.submit(
            package,
            "C1",
            analysis_config=analysis_config,
            similarity_context=context,
        )
        completed = manager.wait(submission.job_id, timeout=5)

    assert [item.chain_id for item in completed.result.similar_chains] == ["C2"]
    assert completed.result.similarity_model_version == "sim-test-v1"
    assert completed.cache_key.config_version == "v1|similarity:sim-test-v1"
