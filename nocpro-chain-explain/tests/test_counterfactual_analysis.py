from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from configuration import CalibrationStatus
from groups import AuditGraphMode
from tier2.counterfactual import (
    CandidateStatus,
    DomainStatus,
    RecommendationStatus,
    ReviewIdentity,
    analyze_counterfactual_review,
)
from tier2.audit_artifact import build_review_audit_artifact
from tests.test_counterfactual_candidates import CONFIG, _audit, _member, _scored
from tests.test_counterfactual_evaluator import _metrics, _package


IDENTITY = ReviewIdentity(
    snapshot_id="s1",
    snapshot_version="1",
    chain_id="C",
    alarm_universe_fingerprint="alarms-v1",
    analysis_version="analysis-v1",
    engine_version="counterfactual-v1",
    config_version="synthetic-v1",
    tier1b_artifact_fingerprint="tier1b-v1",
    structural_audit_artifact_fingerprint="audit-v1",
)


def _tier1b():
    return SimpleNamespace(
        members={
            "A": _member(),
            "B": _member(),
            "C": _member(),
            "X": _member(role="WEAK", support=0.1, representativeness=0.1),
        }
    )


def _metric_computer(package, chain_ids):
    if any("singleton" in chain_id or "split" in chain_id for chain_id in chain_ids):
        return _metrics(
            weak=0,
            membership=0.7,
            coverage=0.8,
            components=1,
            conductance=0.8,
            severity=0,
        )
    return _metrics(
        weak=1,
        membership=0.1,
        coverage=0.4,
        components=2,
        conductance=0.1,
        severity=1,
    )


def test_missing_audit_only_disables_split() -> None:
    result = analyze_counterfactual_review(
        _package(),
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_metric_computer,
    )

    assert result.status is DomainStatus.AVAILABLE
    assert result.remove.status is DomainStatus.AVAILABLE
    assert result.remove.evaluated_candidate_count == 1
    assert result.split.status is DomainStatus.UNAVAILABLE
    assert result.split.reason == "STRUCTURAL_AUDIT_UNAVAILABLE"
    assert result.recommendation_status is RecommendationStatus.AVAILABLE


def test_exact_audit_enables_split_and_singleton_cut_is_not_duplicated() -> None:
    audit = SimpleNamespace(
        audit_graph_mode=AuditGraphMode.EXACT_FULL,
        structural_audit=_audit(
            _scored("split", {"A", "B"}, 0.1),
            _scored("singleton", {"X"}, 0.05),
        ),
    )
    result = analyze_counterfactual_review(
        _package(),
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=audit,
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_metric_computer,
    )

    assert result.split.status is DomainStatus.AVAILABLE
    assert result.split.evaluated_candidate_count == 1
    remove_ids = [
        evaluation.candidate.member_ids
        for evaluation in result.remove.candidates
    ]
    assert remove_ids.count(("X",)) == 1


def test_persistable_exact_audit_artifact_enables_split_after_restart() -> None:
    artifact = build_review_audit_artifact(
        snapshot_id="s1",
        snapshot_version="1",
        chain_id="C",
        members=("A", "B", "C", "X"),
        structural_audit=_audit(_scored("split", {"A", "B"}, 0.1)),
        analysis_version="tier2-audit-v1",
        analysis_config_version="analysis-v1",
        artifact_id="persisted-audit",
        created_at="2026-09-02T10:00:00+00:00",
    )
    result = analyze_counterfactual_review(
        _package(),
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=artifact,
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_metric_computer,
    )

    assert result.remove.status is DomainStatus.AVAILABLE
    assert result.split.status is DomainStatus.AVAILABLE


def test_synthetic_policy_cannot_recommend_on_real_source() -> None:
    package = _package()
    package.snapshot = replace(package.snapshot, source_kind="REAL_EXPORT_REPLAY")
    result = analyze_counterfactual_review(
        package,
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_metric_computer,
    )

    assert result.recommendation_status is RecommendationStatus.UNAVAILABLE
    assert result.reason == "COUNTERFACTUAL_POLICY_NOT_CALIBRATED"
    assert result.remove.candidates[0].status is CandidateStatus.EVALUATED
    assert result.remove.candidates[0].before is not None
    assert result.remove.candidates[0].after is not None


def test_missing_config_is_domain_unavailable_not_exception() -> None:
    result = analyze_counterfactual_review(
        _package(),
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=object(),
        config=None,
        config_reason="COUNTERFACTUAL_CONFIG_INCOMPLETE",
        metric_computer=_metric_computer,
    )
    assert result.status is DomainStatus.UNAVAILABLE
    assert result.remove.status is DomainStatus.UNAVAILABLE
    assert result.split.status is DomainStatus.UNAVAILABLE


def test_chain_over_ceiling_returns_partial_domain_result() -> None:
    result = analyze_counterfactual_review(
        _package(),
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=object(),
        config=replace(CONFIG, max_chain_members=3),
        metric_computer=_metric_computer,
    )
    assert result.status is DomainStatus.AVAILABLE
    assert result.remove.reason == "COUNTERFACTUAL_LIMIT_EXCEEDED"
    assert result.split.reason == "COUNTERFACTUAL_LIMIT_EXCEEDED"


def test_two_member_split_is_not_applicable() -> None:
    package = _package()
    package.chains["C"] = replace(package.chains["C"], member_count=2)
    package.memberships["C"] = ["A", "X"]
    tier1b = SimpleNamespace(
        members={"A": _member(), "X": _member(role="WEAK", support=0.1)}
    )
    result = analyze_counterfactual_review(
        package,
        "C",
        identity=IDENTITY,
        tier1b_artifact=tier1b,
        audit_artifact=None,
        analysis_config=object(),
        config=CONFIG,
        metric_computer=_metric_computer,
    )
    assert result.split.status is DomainStatus.NOT_APPLICABLE
    assert result.split.reason == "NO_NONTRIVIAL_SPLIT"


def test_production_calibrated_policy_can_recommend_real_source() -> None:
    package = _package()
    package.snapshot = replace(package.snapshot, source_kind="REAL_EXPORT_REPLAY")
    result = analyze_counterfactual_review(
        package,
        "C",
        identity=IDENTITY,
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=object(),
        config=replace(
            CONFIG, calibration_status=CalibrationStatus.PRODUCTION_CALIBRATED
        ),
        metric_computer=_metric_computer,
    )
    assert result.recommendation_status is RecommendationStatus.AVAILABLE
