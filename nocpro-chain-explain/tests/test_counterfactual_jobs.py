from __future__ import annotations

import asyncio
from threading import Event
from dataclasses import dataclass, replace
from types import MappingProxyType
from types import SimpleNamespace

from configuration import load_analysis_config
from tier2 import JobStatus
from tier2.counterfactual import CounterfactualJobManager, DomainStatus, review_identity
from tier2.counterfactual import artifact_fingerprint
from nocpro_api.workspace import Workspace
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


def test_workspace_latest_review_never_falls_back_to_an_incompatible_job() -> None:
    identity = SimpleNamespace(
        snapshot_id="s1",
        snapshot_version="1",
        cache_tuple=lambda: ("new-config",),
    )

    class ReviewJobs:
        def latest_compatible(self, received_identity):
            assert received_identity is identity
            return None

        def latest(self, *_args):
            raise AssertionError("incompatible in-memory review must not be returned")

    class Repository:
        async def latest_compatible_counterfactual_job(self, **kwargs):
            assert kwargs["snapshot_id"] == "s1"
            return None

        async def latest_counterfactual_job(self, **_kwargs):
            raise AssertionError("incompatible persisted review must not be returned")

    workspace = Workspace.__new__(Workspace)
    workspace.review_jobs = ReviewJobs()
    workspace.repository = Repository()

    async def review_context(_chain_id: str):
        return None, None, None, identity

    workspace._review_context = review_context
    assert asyncio.run(Workspace.latest_review(workspace, "C")) is None


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
