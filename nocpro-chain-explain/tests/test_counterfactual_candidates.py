from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from audit import Candidate, CandidateSource, ConductanceResult, ScoredCandidate
from audit.conductance import AuditVerdict
from audit.verdict import StructuralAuditResult
from configuration import CalibrationStatus, CounterfactualConfig
from tier2.counterfactual import Operation, ReviewIdentity
from tier2.counterfactual.candidates import (
    generate_remove_candidates,
    generate_split_candidates,
)


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

CONFIG = CounterfactualConfig(
    config_version="synthetic-v1",
    calibration_status=CalibrationStatus.SYNTHETIC_ONLY,
    max_chain_members=100,
    max_remove_candidates=2,
    max_split_candidates=2,
    max_recommendations=2,
    membership_support_below=0.3,
    representativeness_below=0.3,
    adverse_margin_below=0.0,
    minimum_membership_improvement=0.05,
    minimum_coverage_improvement=0.05,
    minimum_conductance_improvement=0.05,
    pareto_tolerance=0.0,
)


def _member(
    *, role="PERIPHERAL", support=0.8, representativeness=0.8, margin=0.2
):
    return SimpleNamespace(
        role=SimpleNamespace(verdict=SimpleNamespace(value=role)),
        support=SimpleNamespace(support=support),
        representativeness=representativeness,
        margins=(SimpleNamespace(margin=margin),),
    )


def _scored(label: str, members: set[str], phi: float, *, feasible=True):
    return ScoredCandidate(
        candidate=Candidate(CandidateSource.ENTITY, frozenset(members), label),
        conductance=ConductanceResult(
            label=label,
            size_s=len(members),
            size_complement=6 - len(members),
            phi=phi,
            feasible=feasible,
        ),
    )


def _audit(*candidates: ScoredCandidate) -> StructuralAuditResult:
    return StructuralAuditResult(
        chain_id="C",
        verdict=AuditVerdict.CANDIDATE_SPLIT,
        best_cut=candidates[0] if candidates else None,
        scored_candidates=candidates,
        epsilon=0.3,
        reason="fixture",
    )


def test_remove_preserves_alarm_as_singleton() -> None:
    batch = generate_remove_candidates(
        IDENTITY,
        chain_id="C",
        members=("A", "B", "C", "X"),
        member_analysis={
            "A": _member(),
            "B": _member(),
            "C": _member(),
            "X": _member(role="WEAK", support=0.1),
        },
        config=CONFIG,
    )

    candidate = batch.candidates[0]
    assert candidate.operation is Operation.REMOVE_MEMBER
    assert candidate.member_ids == ("X",)
    assert candidate.partition_delta.after == (
        ("C", ("A", "B", "C")),
        ("C::singleton::X", ("X",)),
    )


def test_remove_ranking_is_external_then_weak_then_low_metrics_then_id() -> None:
    members = ("external", "weak", "low_support", "low_rep", "bad_margin", "B", "A")
    analyses = {
        "external": _member(),
        "weak": _member(role="WEAK"),
        "low_support": _member(support=0.1),
        "low_rep": _member(representativeness=0.1),
        "bad_margin": _member(margin=-0.5),
        "A": _member(role="WEAK", support=0.1),
        "B": _member(role="WEAK", support=0.1),
    }
    config = replace(CONFIG, max_remove_candidates=7)
    batch = generate_remove_candidates(
        IDENTITY,
        chain_id="C",
        members=members,
        member_analysis=analyses,
        eligible_external_contradictions=frozenset({"external"}),
        config=config,
    )

    assert [candidate.member_ids[0] for candidate in batch.candidates] == [
        "external",
        "A",
        "B",
        "weak",
        "low_support",
        "low_rep",
        "bad_margin",
    ]


def test_remove_limit_is_deterministic_and_reports_counts() -> None:
    analyses = {alarm_id: _member(role="WEAK") for alarm_id in ("C", "A", "B")}
    first = generate_remove_candidates(
        IDENTITY,
        chain_id="C",
        members=("C", "A", "B"),
        member_analysis=analyses,
        config=CONFIG,
    )
    second = generate_remove_candidates(
        IDENTITY,
        chain_id="C",
        members=("B", "C", "A"),
        member_analysis=analyses,
        config=CONFIG,
    )

    assert first == second
    assert first.discovered_count == 3
    assert first.evaluated_count == 2
    assert [candidate.member_ids for candidate in first.candidates] == [("A",), ("B",)]


def test_missing_remove_metric_is_not_treated_as_zero() -> None:
    batch = generate_remove_candidates(
        IDENTITY,
        chain_id="C",
        members=("A", "B"),
        member_analysis={"A": _member(support=None), "B": _member()},
        config=CONFIG,
    )
    assert batch.discovered_count == 0


def test_singleton_audit_cut_is_canonical_remove() -> None:
    batch = generate_split_candidates(
        IDENTITY,
        chain_id="C",
        members=("A", "B", "C", "D", "E", "X"),
        structural_audit=_audit(_scored("singleton", {"X"}, 0.1)),
        config=CONFIG,
    )

    assert batch.candidates == ()
    assert batch.canonical_remove_member_ids == ("X",)


def test_split_reuses_exact_cuts_orders_by_phi_and_deduplicates_complement() -> None:
    audit = _audit(
        _scored("worse", {"A", "B", "C"}, 0.2),
        _scored("best", {"A", "B", "D"}, 0.1),
        _scored("duplicate complement", {"C", "E", "F"}, 0.1),
    )
    batch = generate_split_candidates(
        IDENTITY,
        chain_id="C",
        members=("A", "B", "C", "D", "E", "F"),
        structural_audit=audit,
        config=CONFIG,
    )

    assert batch.discovered_count == 2
    assert batch.evaluated_count == 2
    assert batch.candidates[0].source_ref.startswith("audit-cut:best")
    assert batch.candidates[0].partition_delta.after == (
        ("C::split::0", ("A", "B", "D")),
        ("C::split::1", ("C", "E", "F")),
    )


def test_two_member_chain_has_no_nontrivial_split() -> None:
    batch = generate_split_candidates(
        IDENTITY,
        chain_id="C",
        members=("A", "B"),
        structural_audit=_audit(),
        config=CONFIG,
    )
    assert batch.candidates == ()
