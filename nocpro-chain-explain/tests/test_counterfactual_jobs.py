from __future__ import annotations

from threading import Event
from dataclasses import dataclass, replace
from types import MappingProxyType

from configuration import load_analysis_config
from tier2 import JobStatus
from tier2.counterfactual import CounterfactualJobManager, DomainStatus, review_identity
from tier2.counterfactual import artifact_fingerprint
from tier2.audit_artifact import build_review_audit_artifact
from tests.test_audit_artifact import _audit
from tests.test_counterfactual_analysis import _metric_computer, _tier1b
from tests.test_counterfactual_evaluator import _package


def _config():
    return load_analysis_config("config/thresholds/e2e-counterfactual.yaml")


def test_success_is_cached_by_full_identity() -> None:
    package = _package()
    with_manager = CounterfactualJobManager(metric_computer=_metric_computer)
    try:
        first = with_manager.submit(
            package,
            "C",
            tier1b_artifact=_tier1b(),
            audit_artifact=None,
            analysis_config=_config(),
        )
        assert with_manager.wait(first.job_id).status is JobStatus.SUCCEEDED
        second = with_manager.submit(
            package,
            "C",
            tier1b_artifact=_tier1b(),
            audit_artifact=None,
            analysis_config=_config(),
        )
        assert second.cache_hit is True
        assert with_manager.get(second.job_id).result is not None
    finally:
        with_manager.shutdown()


def test_same_pinned_identity_deduplicates_inflight() -> None:
    entered = Event()
    release = Event()

    def blocking_analyzer(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return "done"

    manager = CounterfactualJobManager(analyzer=blocking_analyzer)
    try:
        first = manager.submit(
            _package(), "C", tier1b_artifact=_tier1b(), audit_artifact=None,
            analysis_config=_config(),
        )
        assert entered.wait(1)
        second = manager.submit(
            _package(), "C", tier1b_artifact=_tier1b(), audit_artifact=None,
            analysis_config=_config(),
        )
        assert second.job_id == first.job_id
        assert second.deduplicated is True
        release.set()
        assert manager.wait(first.job_id).status is JobStatus.SUCCEEDED
    finally:
        release.set()
        manager.shutdown()


def test_artifact_fingerprint_change_misses_cache() -> None:
    manager = CounterfactualJobManager(metric_computer=_metric_computer)
    try:
        first = manager.submit(
            _package(), "C", tier1b_artifact=_tier1b(), audit_artifact=None,
            analysis_config=_config(),
        )
        manager.wait(first.job_id)
        changed = _tier1b()
        changed.members["X"].representativeness = 0.2
        second = manager.submit(
            _package(), "C", tier1b_artifact=changed, audit_artifact=None,
            analysis_config=_config(),
        )
        assert second.cache_hit is False
        assert second.job_id != first.job_id
    finally:
        manager.shutdown()


def test_review_identity_uses_persisted_audit_fingerprint_verbatim() -> None:
    package = _package()
    artifact = build_review_audit_artifact(
        snapshot_id="s1",
        snapshot_version="1",
        chain_id="C",
        members=("A", "B", "C", "X"),
        structural_audit=replace(_audit(), chain_id="C"),
        analysis_version="tier2-audit-v1",
        analysis_config_version="synthetic-v1",
        artifact_id="audit-identity",
        created_at="2026-09-02T10:00:00+00:00",
    )
    identity = review_identity(
        package,
        "C",
        analysis_version="analysis-v1",
        config_version="synthetic-v1",
        tier1b_artifact=_tier1b(),
        audit_artifact=artifact,
        external_artifact=None,
    )

    assert identity.structural_audit_artifact_fingerprint == artifact.artifact_fingerprint


def test_domain_unavailable_is_succeeded_job() -> None:
    config = load_analysis_config("config/thresholds/v1.yaml")
    manager = CounterfactualJobManager(metric_computer=_metric_computer)
    try:
        submission = manager.submit(
            _package(), "C", tier1b_artifact=_tier1b(), audit_artifact=None,
            analysis_config=config,
        )
        view = manager.wait(submission.job_id)
        assert view.status is JobStatus.SUCCEEDED
        assert view.result.status is DomainStatus.UNAVAILABLE
        assert view.result.reason == "COUNTERFACTUAL_CONFIG_INCOMPLETE"
    finally:
        manager.shutdown()


def test_latest_is_snapshot_version_bound() -> None:
    manager = CounterfactualJobManager(metric_computer=_metric_computer)
    package = _package()
    try:
        submission = manager.submit(
            package, "C", tier1b_artifact=_tier1b(), audit_artifact=None,
            analysis_config=_config(),
        )
        manager.wait(submission.job_id)
        assert manager.latest("s1", "1", "C") is not None
        assert manager.latest("s1", "2", "C") is None
    finally:
        manager.shutdown()


def test_unexpected_exception_is_failed_job() -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    manager = CounterfactualJobManager(analyzer=broken)
    try:
        submission = manager.submit(
            _package(), "C", tier1b_artifact=_tier1b(), audit_artifact=None,
            analysis_config=_config(),
        )
        view = manager.wait(submission.job_id)
        assert view.status is JobStatus.FAILED
        assert view.error == "RuntimeError: boom"
    finally:
        manager.shutdown()


def test_execution_timings_do_not_change_artifact_identity() -> None:
    assert artifact_fingerprint(
        {"members": ["A"], "phase_durations": {"fit": 0.01}}
    ) == artifact_fingerprint(
        {"members": ["A"], "phase_durations": {"fit": 9.99}}
    )


def test_artifact_identity_accepts_immutable_mapping_fields() -> None:
    @dataclass(frozen=True)
    class Artifact:
        provenance: object

    assert len(
        artifact_fingerprint(
            Artifact(MappingProxyType({"source": "FROZEN_SPEC"}))
        )
    ) == 64
