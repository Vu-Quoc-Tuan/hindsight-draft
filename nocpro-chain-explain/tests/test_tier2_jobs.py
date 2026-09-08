"""Async per-chain Tier-2 execution and cache semantics (ADR-0023)."""

from __future__ import annotations

from threading import Event
from dataclasses import replace
from types import SimpleNamespace

import pytest

from configuration import (
    ConfiguredValue,
    DependencyScopeConfig,
    ParameterSource,
    P2TopologyConfig,
    PropagationConfig,
    load_analysis_config,
)
from tier1a import CacheTier, Tier1Cache
from tier2 import JobStatus, SimilarityQueryContext, Tier2JobManager
from groups import AuditGraphMode
from similar_chains import (
    CorpusPolicy,
    ModelUpdatePolicy,
    TimedChainFingerprint,
    TaxonomyStatus,
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


def test_state_listener_observes_durable_lifecycle_transitions(analysis_config):
    started = Event()
    release = Event()
    observed = []

    def blocking_analyzer(*args, **kwargs):
        started.set()
        assert release.wait(timeout=2)
        return "deep-result"

    manager = Tier2JobManager(
        analyzer=blocking_analyzer,
        max_workers=1,
        state_listener=observed.append,
    )
    try:
        submission = manager.submit(_package(), "C1", analysis_config=analysis_config)
        assert started.wait(timeout=1)
        release.set()
        manager.wait(submission.job_id, timeout=2)
    finally:
        release.set()
        manager.shutdown()

    statuses = [view.status for view in observed]
    assert statuses[0] is JobStatus.QUEUED
    assert JobStatus.RUNNING in statuses
    assert statuses[-1] is JobStatus.SUCCEEDED
    assert observed[-1].result == "deep-result"


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
        assert entries[0].key.config_version.startswith(
            "v1|attribution-evaluation:"
        )
        assert "SPLITMIX64_FISHER_YATES_V1" in entries[0].key.config_version
        assert "seed=42" in entries[0].key.config_version
        assert "repetitions=100" in entries[0].key.config_version
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


def test_non_exact_or_failed_deep_dive_never_emits_a_review_audit_artifact(
    analysis_config,
):
    artifacts = []

    def unavailable_audit(*args, **kwargs):
        return SimpleNamespace(audit_graph_mode=AuditGraphMode.NOT_COMPUTED)

    with Tier2JobManager(
        analyzer=unavailable_audit, max_workers=1, artifact_listener=artifacts.append
    ) as manager:
        submission = manager.submit(_package(), "C1", analysis_config=analysis_config)
        completed = manager.wait(submission.job_id, timeout=2)

    assert completed.status is JobStatus.SUCCEEDED
    assert completed.audit_artifact is None
    assert artifacts == []


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
    assert received["delay_threshold"] == analysis_config.value(
        "temporal.delay.support_threshold"
    )
    assert received["d_max"] == analysis_config.value("dependency.max_hop")
    assert received["lambda_dep"] == analysis_config.value("dependency.lambda_dep")
    assert received["common_dependency_threshold"] == analysis_config.value(
        "dependency.common_support_threshold"
    )
    assert received["silent_gap_seconds"] == analysis_config.value(
        "temporal.burst.gap_seconds"
    )


def test_unknown_chain_fails_before_scheduling(analysis_config):
    manager = Tier2JobManager(max_workers=1)
    try:
        with pytest.raises(KeyError, match="unknown chain_id"):
            manager.submit(_package(), "missing", analysis_config=analysis_config)
    finally:
        manager.shutdown()


def test_default_worker_runs_real_per_chain_audit(analysis_config):
    artifacts = []
    with Tier2JobManager(max_workers=1) as manager:
        manager.set_artifact_listener(artifacts.append)
        submission = manager.submit(_package(), "C1", analysis_config=analysis_config)
        completed = manager.wait(submission.job_id, timeout=5)

    assert completed.status is JobStatus.SUCCEEDED
    assert completed.result.chain_id == "C1"
    assert completed.result.audit_graph_mode is AuditGraphMode.EXACT_FULL
    assert completed.audit_artifact is artifacts[0]
    assert len(artifacts) == 1
    assert completed.audit_artifact.mode == "EXACT"
    assert completed.audit_artifact.artifact_version == "review-audit-v2"
    assert completed.audit_artifact.visualization == completed.result.audit_visualization
    assert completed.audit_artifact.snapshot_id == "s1"
    assert completed.audit_artifact.snapshot_version == "1"
    assert completed.result.config_version == "v1"
    assert completed.result.parameter_provenance["audit.rho"] == "DOCUMENTED_DEFAULT"
    assert completed.result.similar_chains == ()
    assert completed.result.similarity_status == "UNAVAILABLE"
    assert completed.result.similarity_unavailable_reason == "LINEAGE_NOT_READY"
    assert completed.result.topology_hypotheses.dominator.status.value == "UNAVAILABLE"
    assert completed.result.topology_hypotheses.dominator.reason is not None
    assert completed.result.topology_hypotheses.propagation.status.value == "UNAVAILABLE"
    assert (
        completed.result.topology_hypotheses.propagation.reason.value
        == "PROPAGATION_CONFIG_INCOMPLETE"
    )
    assert (
        completed.result.topology_hypotheses.dependency_scope.status.value
        == "UNAVAILABLE"
    )


def test_domain_limits_return_a_successful_job_with_partial_results(analysis_config):
    parameters = dict(analysis_config.parameters)
    parameters["audit.exact_max_members"] = replace(
        parameters["audit.exact_max_members"], value=5
    )
    limited = replace(analysis_config, parameters=parameters)

    with Tier2JobManager(max_workers=1) as manager:
        submission = manager.submit(_package(), "C1", analysis_config=limited)
        completed = manager.wait(submission.job_id, timeout=5)

    assert completed.status is JobStatus.SUCCEEDED
    assert completed.error is None
    assert completed.result.audit_graph_mode is AuditGraphMode.NOT_COMPUTED
    assert completed.result.structural_audit.verdict.value == "UNAVAILABLE"
    assert completed.result.structural_audit.reason == "AUDIT_LIMIT_EXCEEDED"
    assert completed.result.evidence_attribution.status.value == "UNAVAILABLE"
    assert (
        completed.result.evidence_attribution.reason.value
        == "ATTRIBUTION_LIMIT_EXCEEDED"
    )
    assert completed.result.similarity_unavailable_reason == "LINEAGE_NOT_READY"
    assert completed.result.topology_hypotheses is not None


def test_p2_config_versions_and_scope_values_are_part_of_cache_stamp(analysis_config):
    calls = 0

    def analyzer(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"run": calls}

    def cv(path, value):
        return ConfiguredValue(
            path=path, value=value, source=ParameterSource.FROZEN_SPEC
        )

    propagation = PropagationConfig(
        config_version="propagation-test-v1",
        restart_probability=cv("propagation.rwr.restart_probability", 0.2),
        convergence_tolerance=cv("propagation.rwr.convergence_tolerance", 0.001),
        max_iterations=cv("propagation.rwr.max_iterations", 10),
        decay_type="exponential",
        decay_parameter=cv("propagation.temporal.decay_parameter", 30.0),
        score_threshold=cv("propagation.acceptance.score_threshold", 0.5),
        max_candidate_edges=cv("propagation.limits.max_candidate_edges", 20),
    )
    scope = DependencyScopeConfig(
        max_scope_resources=cv("dependency_scope.limits.max_scope_resources", 20),
        max_materialized_resources=cv(
            "dependency_scope.limits.max_materialized_resources", 10
        ),
    )
    config_a = replace(
        analysis_config,
        p2_topology=P2TopologyConfig(propagation, None, scope, None),
    )
    config_b = replace(
        config_a,
        p2_topology=replace(
            config_a.p2_topology,
            propagation=replace(propagation, config_version="propagation-test-v2"),
        ),
    )
    config_c = replace(
        config_a,
        p2_topology=replace(
            config_a.p2_topology,
            dependency_scope=replace(
                scope,
                max_scope_resources=cv(
                    "dependency_scope.limits.max_scope_resources", 21
                ),
            ),
        ),
    )
    config_d = replace(
        config_a,
        p2_topology=replace(
            config_a.p2_topology,
            propagation=replace(
                propagation,
                restart_probability=cv(
                    "propagation.rwr.restart_probability", 0.3
                ),
            ),
        ),
    )
    config_e = replace(
        config_a,
        p2_topology=replace(
            config_a.p2_topology,
            propagation=replace(
                propagation,
                restart_probability=ConfiguredValue(
                    path="propagation.rwr.restart_probability",
                    value=0.2,
                    source=ParameterSource.DATA_DRIVEN,
                ),
            ),
        ),
    )
    config_f = replace(
        config_a,
        p2_topology=replace(
            config_a.p2_topology,
            dependency_scope=replace(
                scope,
                max_scope_resources=cv(
                    "dependency_scope.limits.max_scope_resources.alias", 20
                ),
            ),
        ),
    )

    cache = Tier1Cache()
    with Tier2JobManager(cache=cache, analyzer=analyzer, max_workers=1) as manager:
        submissions = [
            manager.submit(_package(), "C1", analysis_config=config)
            for config in (config_a, config_b, config_c, config_d, config_e, config_f)
        ]
        for submission in submissions:
            assert manager.wait(submission.job_id, timeout=2).status is JobStatus.SUCCEEDED

    keys = [
        cache.tier_entries(CacheTier.TIER_2)[index].key.config_version
        for index in range(6)
    ]
    assert calls == 6
    assert all(key != "v1" for key in keys)
    assert "version='propagation-test-v1'" in keys[0]
    assert "version='propagation-test-v2'" in keys[1]
    assert "max_scope_resources=21" in keys[2]
    assert "restart_probability" in keys[3]
    assert "value=0.3" in keys[3]
    assert "source='DATA_DRIVEN'" in keys[4]
    assert "path='dependency_scope.limits.max_scope_resources'" in keys[0]
    assert "source='FROZEN_SPEC'" in keys[0]
    assert "path='dependency_scope.limits.max_scope_resources.alias'" in keys[5]
    assert keys[0] != keys[5]


def test_incomplete_or_unsupported_p2_cannot_reuse_available_cache(analysis_config):
    calls = 0

    def analyzer(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"run": calls}

    def cv(path, value, source=ParameterSource.FROZEN_SPEC):
        return ConfiguredValue(path=path, value=value, source=source)

    propagation = PropagationConfig(
        config_version="propagation-test-v1",
        restart_probability=cv("propagation.rwr.restart_probability", 0.2),
        convergence_tolerance=cv("propagation.rwr.convergence_tolerance", 0.001),
        max_iterations=cv("propagation.rwr.max_iterations", 10),
        decay_type="exponential",
        decay_parameter=cv("propagation.temporal.decay_parameter", 30.0),
        score_threshold=cv("propagation.acceptance.score_threshold", 0.5),
        max_candidate_edges=cv("propagation.limits.max_candidate_edges", 20),
    )
    scope = DependencyScopeConfig(
        max_scope_resources=cv("dependency_scope.limits.max_scope_resources", 20),
        max_materialized_resources=cv(
            "dependency_scope.limits.max_materialized_resources", 10
        ),
    )
    available = replace(
        analysis_config,
        p2_topology=P2TopologyConfig(propagation, None, scope, None),
    )
    unsupported = replace(
        available,
        p2_topology=replace(
            available.p2_topology,
            propagation=replace(propagation, decay_type="linear"),
        ),
    )
    incomplete = replace(
        available,
        p2_topology=replace(
            available.p2_topology,
            propagation=None,
            propagation_reason="PROPAGATION_CONFIG_INCOMPLETE",
        ),
    )
    malformed_propagation = replace(
        available,
        p2_topology=replace(
            available.p2_topology,
            propagation=replace(
                propagation,
                restart_probability=ConfiguredValue(
                    path="propagation.rwr.restart_probability",
                    value=0.2,
                    source="FROZEN_SPEC",
                ),
            ),
        ),
    )
    malformed_scope = replace(
        available,
        p2_topology=replace(
            available.p2_topology,
            dependency_scope=replace(
                scope,
                max_scope_resources=ConfiguredValue(
                    path="dependency_scope.limits.max_scope_resources",
                    value=20,
                    source="FROZEN_SPEC",
                ),
            ),
        ),
    )

    for variant in (
        unsupported,
        incomplete,
        malformed_propagation,
        malformed_scope,
    ):
        cache = Tier1Cache()
        with Tier2JobManager(cache=cache, analyzer=analyzer, max_workers=1) as manager:
            available_submission = manager.submit(
                _package(), "C1", analysis_config=available
            )
            variant_submission = manager.submit(
                _package(), "C1", analysis_config=variant
            )
            assert available_submission.cache_hit is False
            assert variant_submission.cache_hit is False
            assert (
                manager.wait(available_submission.job_id, timeout=2).status
                is JobStatus.SUCCEEDED
            )
            assert (
                manager.wait(variant_submission.job_id, timeout=2).status
                is JobStatus.SUCCEEDED
            )

    assert calls == 8


def test_invalid_present_scope_cannot_collide_with_absent_scope(analysis_config):
    def cv(path, value, source=ParameterSource.FROZEN_SPEC):
        return ConfiguredValue(path=path, value=value, source=source)

    propagation = PropagationConfig(
        config_version="propagation-test-v1",
        restart_probability=cv("propagation.rwr.restart_probability", 0.2),
        convergence_tolerance=cv("propagation.rwr.convergence_tolerance", 0.001),
        max_iterations=cv("propagation.rwr.max_iterations", 10),
        decay_type="exponential",
        decay_parameter=cv("propagation.temporal.decay_parameter", 30.0),
        score_threshold=cv("propagation.acceptance.score_threshold", 0.5),
        max_candidate_edges=cv("propagation.limits.max_candidate_edges", 20),
    )
    malformed_scope = DependencyScopeConfig(
        max_scope_resources=ConfiguredValue(
            path="dependency_scope.limits.max_scope_resources",
            value=20,
            source="FROZEN_SPEC",
        ),
        max_materialized_resources=cv(
            "dependency_scope.limits.max_materialized_resources", 10
        ),
    )
    propagation_only = replace(
        analysis_config,
        p2_topology=P2TopologyConfig(
            propagation=propagation,
            propagation_reason=None,
            dependency_scope=None,
            dependency_scope_reason="DEPENDENCY_SCOPE_CONFIG_INCOMPLETE",
        ),
    )
    invalid_scope = replace(
        propagation_only,
        p2_topology=replace(
            propagation_only.p2_topology,
            dependency_scope=malformed_scope,
            dependency_scope_reason=None,
        ),
    )

    with Tier2JobManager(max_workers=1) as manager:
        first = manager.submit(_package(), "C1", analysis_config=propagation_only)
        first_view = manager.wait(first.job_id, timeout=5)
        second = manager.submit(_package(), "C1", analysis_config=invalid_scope)
        second_view = manager.wait(second.job_id, timeout=5)

    assert first.cache_hit is False
    assert second.cache_hit is False
    assert first_view.status is JobStatus.SUCCEEDED
    assert second_view.status is JobStatus.SUCCEEDED
    assert first_view.cache_key.config_version != second_view.cache_key.config_version
    assert (
        first_view.result.topology_hypotheses.dependency_scope.reason.value
        == "DEPENDENCY_SCOPE_UNAVAILABLE"
    )
    assert (
        second_view.result.topology_hypotheses.dependency_scope.reason.value
        == "DEPENDENCY_SCOPE_UNAVAILABLE"
    )


def test_topology_results_are_not_inputs_to_audit_graph(monkeypatch, analysis_config):
    import tier2.audit_analysis as audit_module

    original = audit_module.build_audit_graph
    observed = {}

    def recording_build_audit_graph(members, pair_values):
        observed["members"] = members
        observed["pair_values"] = pair_values
        return original(members, pair_values)

    monkeypatch.setattr(audit_module, "build_audit_graph", recording_build_audit_graph)
    with Tier2JobManager(max_workers=1) as manager:
        submission = manager.submit(_package(), "C1", analysis_config=analysis_config)
        completed = manager.wait(submission.job_id, timeout=5)

    assert completed.status is JobStatus.SUCCEEDED
    assert observed["members"]
    assert not any(
        type(value).__name__ == "TopologyHypothesesResult"
        for value in (*observed["members"], observed["pair_values"])
    )


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
            TimedChainFingerprint(
                same_lineage, "2025-12-31T23:58:00Z", "s0", "v1"
            ),
            TimedChainFingerprint(
                different_incident, "2025-12-31T23:59:00Z", "s0", "v1"
            ),
        ],
        model_version="sim-test-v1",
        trained_until_exclusive=package.snapshot.snapshot_time,
        corpus_policy=CorpusPolicy.HISTORY_BEFORE_SNAPSHOT,
        model_update_policy=ModelUpdatePolicy.SNAPSHOT_VERSIONED,
        taxonomy_policy="TEST_EMPTY",
        taxonomy_status=TaxonomyStatus.UNAVAILABLE,
        taxonomy_reason="ALARM_TAXONOMY_NOT_USED_BY_SOURCE",
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
    assert (
        completed.result.similarity_trained_until_exclusive
        == package.snapshot.snapshot_time
    )
    assert completed.result.similarity_corpus_policy == "HISTORY_BEFORE_SNAPSHOT"
    assert completed.result.similarity_model_update_policy == "SNAPSHOT_VERSIONED"
    assert completed.result.similarity_status == "AVAILABLE"
    assert completed.result.taxonomy_status == "UNAVAILABLE"
    assert (
        completed.result.taxonomy_reason
        == "ALARM_TAXONOMY_NOT_USED_BY_SOURCE"
    )
    assert "alarm_taxonomy" not in completed.result.active_fingerprint_blocks
    assert "size_bin" in completed.result.active_fingerprint_blocks
    assert "duration_bin" in completed.result.active_fingerprint_blocks
    assert completed.cache_key.config_version.startswith(
        "v1|similarity:sim-test-v1|attribution-evaluation:"
    )
