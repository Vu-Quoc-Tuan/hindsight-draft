from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from audit import Candidate, CandidateSource, ConductanceResult, ScoredCandidate
from audit.conductance import AuditVerdict
from audit.verdict import StructuralAuditResult
from configuration import CalibrationStatus, CounterfactualConfig
from descriptor.contrastive import BlockingCandidate
from channels.cross_chain import CrossChainEvidence
from tier2.counterfactual import Operation, ReviewIdentity
from tier2.counterfactual.candidates import (
    generate_merge_candidates,
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


def _cross_evidence(*, edges: int, union_pairs: int, pair_count: int) -> CrossChainEvidence:
    return CrossChainEvidence(
        left_chain_id="C",
        right_chain_id="T",
        cross_pair_count=pair_count,
        groups=(),
        cross_audit_edge_count=edges,
        cross_evidence_union_pair_count=union_pairs,
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
    assert batch.candidates[0].edit_cost.operation_count == 1
    assert batch.candidates[0].edit_cost.membership_reassignments == 0
    assert batch.candidates[0].edit_cost.affected_member_count == 6


def test_unbalanced_split_is_structural_not_member_reassignments() -> None:
    batch = generate_split_candidates(
        IDENTITY,
        chain_id="C",
        members=("A", "B", "C", "D", "E", "F"),
        structural_audit=_audit(_scored("two-four", {"A", "B"}, 0.1)),
        config=CONFIG,
    )

    assert len(batch.candidates) == 1
    candidate = batch.candidates[0]
    assert candidate.partition_delta.after == (
        ("C::split::0", ("A", "B")),
        ("C::split::1", ("C", "D", "E", "F")),
    )
    assert candidate.edit_cost.operation_count == 1
    assert candidate.edit_cost.membership_reassignments == 0
    assert candidate.edit_cost.affected_member_count == 6


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
            "C1": ("A", "A1"),
            "C2": ("B", "B1"),
            "C3": ("D", "D1"),
            "C4": ("E", "E1"),
            "C5": ("F", "F1"),
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


def test_singleton_pair_move_only_allows_stable_max_source_to_stable_min_target() -> None:
    package = _Package({"C10": ("A",), "C20": ("B",)})
    batch = generate_move_candidates(
        IDENTITY,
        source_chain_id="C20",
        source_members=("B",),
        member_analysis={"B": _member(role="WEAK")},
        local_candidates=(_blocking("C10", 1),),
        package=package,
        config=replace(CONFIG, max_move_candidates=1),
    )

    assert len(batch.candidates) == 1
    candidate = batch.candidates[0]
    assert candidate.operation is Operation.MOVE_MEMBER
    assert candidate.source_chain_id == "C20"
    assert candidate.target_chain_id == "C10"
    assert candidate.member_ids == ("B",)
    assert candidate.partition_delta.after == (("C10", ("A", "B")),)


def test_singleton_pair_reviewed_from_stable_min_suppresses_reverse_move() -> None:
    package = _Package({"C10": ("A",), "C20": ("B",)})
    batch = generate_move_candidates(
        IDENTITY,
        source_chain_id="C10",
        source_members=("A",),
        member_analysis={"A": _member(role="WEAK", support=0.0)},
        local_candidates=(_blocking("C20", 999),),
        package=package,
        config=replace(CONFIG, max_move_candidates=1),
    )

    assert batch.candidates == ()


def test_singleton_non_singleton_move_only_allows_singleton_source() -> None:
    package = _Package({"C1": ("A", "B"), "C2": ("X",)})
    allowed = generate_move_candidates(
        IDENTITY,
        source_chain_id="C2",
        source_members=("X",),
        member_analysis={"X": _member(role="WEAK")},
        local_candidates=(_blocking("C1", 1),),
        package=package,
        config=replace(CONFIG, max_move_candidates=1),
    )
    suppressed = generate_move_candidates(
        IDENTITY,
        source_chain_id="C1",
        source_members=("A", "B"),
        member_analysis={"A": _member(role="WEAK"), "B": _member()},
        local_candidates=(_blocking("C2", 999),),
        package=package,
        config=replace(CONFIG, max_move_candidates=1),
    )

    assert len(allowed.candidates) == 1
    assert allowed.candidates[0].source_chain_id == "C2"
    assert allowed.candidates[0].target_chain_id == "C1"
    assert suppressed.candidates == ()


def test_move_pre_ceiling_ranking_uses_frozen_margin_states_then_overlap() -> None:
    package = _Package(
        {
            "C": ("X",),
            "T1": ("A", "A1"),
            "T2": ("B", "B1"),
            "T3": ("D", "D1"),
            "T4": ("E", "E1"),
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


def test_merge_uses_local_candidates_exact_cross_edges_and_block_level_cost(
    monkeypatch,
) -> None:
    package = _Package(
        {
            "C": ("A", "B"),
            "T1": ("C", "D"),
            "T2": ("E", "F"),
            "S": ("X",),
        }
    )

    def cross(_package, left, right):
        assert tuple(sorted((left, right))) in {("C", "T1"), ("C", "T2")}
        return _cross_evidence(
            edges=2 if right == "T1" else 1,
            union_pairs=4,
            pair_count=4,
        )

    monkeypatch.setattr("tier2.counterfactual.candidates.exact_cross_chain_evidence", cross)
    batch = generate_merge_candidates(
        IDENTITY,
        review_chain_id="C",
        local_candidates=(_blocking("T2", 50), _blocking("S", 99), _blocking("T1", 1)),
        package=package,
        config=replace(CONFIG, max_merge_candidates=2),
    )

    assert batch.discovered_count == 2
    assert [candidate.merged_chain_ids for candidate in batch.candidates] == [
        ("C", "T1"),
        ("C", "T2"),
    ]
    candidate = batch.candidates[0]
    assert candidate.operation is Operation.MERGE_CHAINS
    assert candidate.source_chain_id is None and candidate.target_chain_id is None
    assert candidate.edit_cost.operation_count == 1
    assert candidate.edit_cost.membership_reassignments == 0
    assert candidate.edit_cost.affected_member_count == 4
    assert candidate.partition_delta.after[0][0].startswith("CF-MERGE-")
    assert candidate.partition_delta.after[0][1] == ("A", "B", "C", "D")


def test_merge_requires_at_least_one_cross_audit_edge_and_never_falls_back_to_singleton_move(
    monkeypatch,
) -> None:
    package = _Package({"C": ("A", "B"), "T": ("C", "D"), "S": ("X",)})
    monkeypatch.setattr(
        "tier2.counterfactual.candidates.exact_cross_chain_evidence",
        lambda *_args, **_kwargs: _cross_evidence(edges=0, union_pairs=4, pair_count=4),
    )
    batch = generate_merge_candidates(
        IDENTITY,
        review_chain_id="C",
        local_candidates=(_blocking("T", 4), _blocking("S", 4)),
        package=package,
        config=replace(CONFIG, max_merge_candidates=2),
    )

    assert batch.candidates == ()
    assert batch.discovered_count == 0


def test_singleton_pair_never_generates_merge_candidate(monkeypatch) -> None:
    package = _Package({"C10": ("A",), "C20": ("B",)})

    def unexpected_cross_evidence(*_args, **_kwargs):
        raise AssertionError("singleton pair must be filtered before cross evidence")

    monkeypatch.setattr(
        "tier2.counterfactual.candidates.exact_cross_chain_evidence",
        unexpected_cross_evidence,
    )
    batch = generate_merge_candidates(
        IDENTITY,
        review_chain_id="C20",
        local_candidates=(_blocking("C10", 1),),
        package=package,
        config=replace(CONFIG, max_merge_candidates=1),
    )

    assert batch.candidates == ()
    assert batch.discovered_count == 0
