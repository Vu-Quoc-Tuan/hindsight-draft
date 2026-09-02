from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from audit import Candidate, CandidateSource, ConductanceResult, ScoredCandidate
from audit.conductance import AuditVerdict
from audit.verdict import StructuralAuditResult
from configuration import CalibrationStatus, CounterfactualConfig
from descriptor.contrastive import BlockingCandidate
from tier2.counterfactual import Operation, ReviewIdentity
from tier2.counterfactual.candidates import (
    generate_move_candidates,
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


class _Package:
    def __init__(self, memberships: dict[str, tuple[str, ...]]) -> None:
        self.memberships = memberships
        self.chains = {chain_id: object() for chain_id in memberships}

    def members_of(self, chain_id: str) -> tuple[str, ...]:
        return self.memberships[chain_id]


def _blocking(chain_id: str, overlap: int) -> BlockingCandidate:
    return BlockingCandidate(
        chain_id=chain_id,
        shared_key="location_code",
        shared_value="loc-1",
        overlap=overlap,
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


def test_move_uses_all_local_candidates_and_margin_null_does_not_veto() -> None:
    package = _Package(
        {
            "C": ("X",),
            "C1": ("A",),
            "C2": ("B",),
            "C3": ("D",),
            "C4": ("E",),
            "C5": ("F",),
        }
    )
    batch = generate_move_candidates(
        IDENTITY,
        source_chain_id="C",
        source_members=("X",),
        member_analysis={"X": _member(role="WEAK", margin=None)},
        local_candidates=tuple(_blocking(f"C{number}", number) for number in range(1, 6)),
        package=package,
        config=replace(CONFIG, max_move_candidates=5),
    )

    assert batch.discovered_count == 5
    assert [candidate.target_chain_id for candidate in batch.candidates] == [
        "C5",
        "C4",
        "C3",
        "C2",
        "C1",
    ]
    assert all("TARGET_FAVORED_MARGIN" not in item.source_ref for item in batch.candidates)


def test_move_from_singleton_removes_empty_source_and_is_canonical() -> None:
    package = _Package({"C": ("X",), "T": ("A", "B")})
    batch = generate_move_candidates(
        IDENTITY,
        source_chain_id="C",
        source_members=("X",),
        member_analysis={"X": _member(role="WEAK")},
        local_candidates=(_blocking("T", 1),),
        package=package,
        config=replace(CONFIG, max_move_candidates=1),
    )

    candidate = batch.candidates[0]
    assert candidate.operation is Operation.MOVE_MEMBER
    assert candidate.source_chain_id == "C"
    assert candidate.target_chain_id == "T"
    assert candidate.partition_delta.before == (("C", ("X",)), ("T", ("A", "B")))
    assert candidate.partition_delta.after == (("T", ("A", "B", "X")),)


def test_move_pre_ceiling_ranking_uses_frozen_margin_states_then_overlap() -> None:
    package = _Package(
        {
            "C": ("X",),
            "T1": ("A",),
            "T2": ("B",),
            "T3": ("D",),
            "T4": ("E",),
        }
    )
    base = _member(role="WEAK")
    analysis = SimpleNamespace(
        role=base.role,
        support=base.support,
        representativeness=base.representativeness,
        margins=(
            SimpleNamespace(compared_chain_id="T1", margin=-0.42),
            SimpleNamespace(compared_chain_id="T2", margin=-0.18),
            SimpleNamespace(compared_chain_id="T3", margin=None),
            SimpleNamespace(compared_chain_id="T4", margin=0.05),
        ),
    )
    batch = generate_move_candidates(
        IDENTITY,
        source_chain_id="C",
        source_members=("X",),
        member_analysis={"X": analysis},
        local_candidates=(
            _blocking("T4", 100),
            _blocking("T3", 1),
            _blocking("T2", 1),
            _blocking("T1", 1),
        ),
        package=package,
        config=replace(CONFIG, max_move_candidates=4),
    )

    assert [candidate.target_chain_id for candidate in batch.candidates] == [
        "T1",
        "T2",
        "T3",
        "T4",
    ]
