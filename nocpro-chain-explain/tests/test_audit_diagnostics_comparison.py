from __future__ import annotations

import pytest

from audit import AuditEdge, AuditGraph, Candidate, CandidateSource
from audit_diagnostics.comparison import (
    compare_candidates,
    freeze_candidates,
    production_baseline_winner,
    score_frozen_candidates,
)
from audit_diagnostics.contracts import (
    CandidateScore,
    CandidateScoreStatus,
    MaterialityPolicy,
    MaterialityStatus,
    WinnerStatus,
)


def _candidate(members, label, source=CandidateSource.ENTITY):
    return Candidate(source=source, members=frozenset(members), label=label)


def _score(partition_id, phi, *, status=CandidateScoreStatus.SCORABLE):
    scorable = status is CandidateScoreStatus.SCORABLE
    return CandidateScore(
        partition_id=partition_id,
        status=status,
        cut_weight=phi * 2.0 if scorable else (0.0 if status is CandidateScoreStatus.ZERO_SIDE_VOLUME else None),
        volume_a=1.0 if scorable else (0.0 if status is CandidateScoreStatus.ZERO_SIDE_VOLUME else None),
        volume_b=1.0 if scorable else (1.0 if status is CandidateScoreStatus.ZERO_SIDE_VOLUME else None),
        phi=phi if scorable else None,
    )


def test_frozen_candidates_canonicalize_complementary_cuts_and_keep_origins():
    members = tuple(f"a{i}" for i in range(10))
    left = frozenset(members[:5])
    right = frozenset(members[5:])
    candidates = freeze_candidates(
        (
            _candidate(left, "left block"),
            _candidate(right, "right block", CandidateSource.DESCRIPTOR),
        ),
        members,
        max_candidates=2,
    )

    assert len(candidates) == 1
    assert candidates[0].side_a == tuple(sorted(min((left, right), key=lambda side: tuple(sorted(side)))))
    assert [origin.label for origin in candidates[0].origins] == ["left block", "right block"]


def test_candidate_cap_fails_without_silent_truncation():
    members = tuple(f"a{i}" for i in range(10))
    with __import__("pytest").raises(ValueError, match="exceeding max_candidates"):
        freeze_candidates(
            (_candidate(members[:5], "a"), _candidate((*members[:4], members[5]), "b")),
            members,
            max_candidates=1,
        )


def test_production_baseline_maps_a_complement_oriented_candidate_to_frozen_partition():
    members = tuple(f"a{i}" for i in range(10))
    original_side = frozenset(members[5:])
    frozen = freeze_candidates(
        (_candidate(original_side, "right-block"),),
        members,
        max_candidates=2,
    )
    adjacency = {node: {} for node in members}
    edges = []
    for side in (members[:5], members[5:]):
        for left, right in zip(side, side[1:]):
            adjacency[left][right] = adjacency[right][left] = 1.0
            edges.append(AuditEdge(left, right, 1.0, ("g1", "g2")))
    adjacency[members[0]][members[5]] = adjacency[members[5]][members[0]] = 0.1
    edges.append(AuditEdge(members[0], members[5], 0.1, ("g1", "g2")))
    graph = AuditGraph(members=members, edges=tuple(edges), adjacency=adjacency)

    winner_id, verdict = production_baseline_winner(
        "c1", graph, frozen, epsilon_phi=0.2, rho=0.2,
        min_side_size=5, small_chain_threshold=10,
    )

    assert winner_id == frozen[0].partition_id
    assert verdict == "CANDIDATE_SPLIT"


def test_canonical_scorer_keeps_infeasible_and_small_chain_states_distinct():
    members = tuple(f"a{i}" for i in range(10))
    candidate = freeze_candidates((_candidate(members[:5], "split"),), members, max_candidates=2)
    graph = AuditGraph(members=members, edges=(), adjacency={node: {} for node in members})

    small_scores = score_frozen_candidates(
        graph, candidate, rho=0.2, min_side_size=5, small_chain_threshold=11
    )
    assert small_scores[0].status is CandidateScoreStatus.SKIPPED_SMALL_CHAIN
    assert small_scores[0].phi is None

    empty_scores = score_frozen_candidates(
        graph, candidate, rho=0.2, min_side_size=5, small_chain_threshold=10
    )
    assert empty_scores[0].status is CandidateScoreStatus.EMPTY_GRAPH
    assert empty_scores[0].phi is None


def test_production_baseline_winner_uses_canonical_audit_order_and_comparator():
    members = tuple(f"a{i}" for i in range(10))
    left = frozenset(members[:5])
    right = frozenset(members[5:])
    frozen = freeze_candidates(
        (_candidate(left, "left"), _candidate(right, "right")),
        members,
        max_candidates=4,
    )
    adjacency = {node: {} for node in members}
    adjacency[members[0]][members[1]] = 1.0
    adjacency[members[1]][members[0]] = 1.0
    adjacency[members[5]][members[6]] = 1.0
    adjacency[members[6]][members[5]] = 1.0
    adjacency[members[0]][members[5]] = 0.2
    adjacency[members[5]][members[0]] = 0.2
    graph = AuditGraph(
        members=members,
        edges=(
            AuditEdge(members[0], members[1], 1.0, ("g1", "g2")),
            AuditEdge(members[5], members[6], 1.0, ("g1", "g2")),
            AuditEdge(members[0], members[5], 0.2, ("g1", "g2")),
        ),
        adjacency=adjacency,
    )

    scores = score_frozen_candidates(
        graph, frozen, rho=0.2, min_side_size=5, small_chain_threshold=10
    )
    winner_id, verdict = production_baseline_winner(
        "c1", graph, frozen, epsilon_phi=0.2, rho=0.2,
        min_side_size=5, small_chain_threshold=10,
    )

    assert winner_id == scores[0].partition_id
    assert verdict == "CANDIDATE_SPLIT"


def test_winner_regret_and_materiality_are_separate_from_verdict_flip():
    c0, c1 = "a" * 64, "b" * 64
    baseline = (_score(c0, 0.200), _score(c1, 0.201))
    near_tie = (_score(c0, 0.210), _score(c1, 0.209))
    comparison = compare_candidates(
        baseline, near_tie,
        production_baseline_winner_id=c0,
        epsilon_phi=0.2,
        materiality=MaterialityPolicy(delta_phi=0.005),
    )
    assert comparison.winner_status is WinnerStatus.NEAR_TIE_REORDER
    assert comparison.regret == pytest.approx(0.001)
    assert comparison.verdict_flip is True
    assert comparison.materiality_status is MaterialityStatus.CONFIGURED

    material = compare_candidates(
        baseline, (_score(c0, 0.230), _score(c1, 0.210)),
        production_baseline_winner_id=c0,
        epsilon_phi=0.2,
        materiality=MaterialityPolicy(delta_phi=0.005),
    )
    assert material.winner_status is WinnerStatus.MATERIAL_WINNER_CHANGE
    assert material.regret == pytest.approx(0.02)


def test_unconfigured_materiality_reports_regret_but_no_material_claim():
    c0, c1 = "a" * 64, "b" * 64
    result = compare_candidates(
        (_score(c0, 0.2), _score(c1, 0.25)),
        (_score(c0, 0.3), _score(c1, 0.25)),
        production_baseline_winner_id=c0,
        epsilon_phi=0.2,
        materiality=MaterialityPolicy(delta_phi=None),
    )
    assert result.winner_status is WinnerStatus.WINNER_CHANGED
    assert result.regret == pytest.approx(0.05)
    assert result.materiality_status is MaterialityStatus.NOT_CONFIGURED


def test_numerical_tie_and_unscorable_baseline_are_not_ranked_as_material():
    c0, c1 = "a" * 64, "b" * 64
    numerical = compare_candidates(
        (_score(c0, 0.2000000000005), _score(c1, 0.2)),
        (_score(c0, 0.2), _score(c1, 0.2)),
        production_baseline_winner_id=c1,
        epsilon_phi=0.3,
        materiality=MaterialityPolicy(delta_phi=0.01),
    )
    assert numerical.winner_status is WinnerStatus.NUMERICAL_TIE
    assert numerical.regret == 0.0
    assert numerical.verdict_flip is False

    baseline_unscorable = compare_candidates(
        (_score(c0, 0.2), _score(c1, 0.3)),
        (_score(c0, 0.2, status=CandidateScoreStatus.ZERO_SIDE_VOLUME), _score(c1, 0.3)),
        production_baseline_winner_id=c0,
        epsilon_phi=0.3,
        materiality=MaterialityPolicy(delta_phi=None),
    )
    no_scorable = compare_candidates(
        (_score(c0, 0.2), _score(c1, 0.3)),
        (_score(c0, 0.2, status=CandidateScoreStatus.ZERO_SIDE_VOLUME),
         _score(c1, 0.3, status=CandidateScoreStatus.ZERO_SIDE_VOLUME)),
        production_baseline_winner_id=c0,
        epsilon_phi=0.3,
        materiality=MaterialityPolicy(delta_phi=None),
    )
    assert baseline_unscorable.winner_status is WinnerStatus.BASELINE_WINNER_UNSCORABLE
    assert baseline_unscorable.regret is None
    assert no_scorable.winner_status is WinnerStatus.NO_SCORABLE_CANDIDATE
    assert no_scorable.regret is None


def test_verdict_flip_tracks_variant_best_candidate_not_only_baseline_winner():
    c0, c1 = "a" * 64, "b" * 64
    result = compare_candidates(
        (_score(c0, 0.25), _score(c1, 0.30)),
        (_score(c0, 0.40), _score(c1, 0.10)),
        production_baseline_winner_id=c0,
        epsilon_phi=0.2,
        materiality=MaterialityPolicy(delta_phi=None),
    )
    assert result.variant_best_id == c1
    assert result.verdict_flip is True
