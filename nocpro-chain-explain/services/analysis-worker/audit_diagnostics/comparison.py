"""Frozen candidate partitions, canonical scoring, and materiality comparison."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Sequence

from audit import (
    Candidate,
    CandidateSource,
    ConductanceResult,
    AuditGraph,
    run_structural_audit,
    score_candidates,
    is_chain_too_small_for_audit,
)
from audit_diagnostics.contracts import (
    CandidateOrigin,
    CandidateComparison,
    CandidateScore,
    CandidateScoreStatus,
    FrozenCandidate,
    MaterialityPolicy,
    MaterialityStatus,
    WinnerStatus,
)


class CandidateSetError(ValueError):
    """Candidate output is invalid or exceeds a declared resource bound."""


def freeze_candidates(
    candidates: Sequence[Candidate],
    members: Sequence[str],
    *,
    max_candidates: int,
) -> tuple[FrozenCandidate, ...]:
    """Canonicalize complementary cuts and merge source provenance without loss."""
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")
    member_tuple = tuple(sorted(members))
    universe = set(member_tuple)
    grouped: dict[tuple[tuple[str, ...], tuple[str, ...]], list[CandidateOrigin]] = defaultdict(list)
    for order, candidate in enumerate(candidates):
        if not candidate.members <= universe:
            raise CandidateSetError(f"candidate {candidate.label!r} contains non-chain members")
        side = tuple(sorted(candidate.members))
        complement = tuple(sorted(universe - set(side)))
        side_a, side_b = (side, complement) if side <= complement else (complement, side)
        grouped[(side_a, side_b)].append(
            CandidateOrigin(
                source=candidate.source.value,
                label=candidate.label,
                baseline_order=order,
            )
        )
    if len(grouped) > max_candidates:
        raise CandidateSetError(
            f"candidate set has {len(grouped)} canonical partitions, exceeding max_candidates={max_candidates}"
        )
    frozen: list[FrozenCandidate] = []
    for (side_a, side_b), origins in sorted(
        grouped.items(),
        key=lambda item: (
            min(origin.baseline_order for origin in item[1]),
            _partition_digest(member_tuple, item[0][0], item[0][1]),
        ),
    ):
        partition_id = _partition_digest(member_tuple, side_a, side_b)
        frozen.append(
            FrozenCandidate(
                partition_id=partition_id,
                members=member_tuple,
                side_a=side_a,
                side_b=side_b,
                side_a_fingerprint=_digest(side_a),
                side_b_fingerprint=_digest(side_b),
                origins=tuple(sorted(origins, key=lambda origin: (origin.baseline_order, origin.source, origin.label))),
            )
        )
    return tuple(frozen)


def score_frozen_candidates(
    graph: AuditGraph,
    candidates: Sequence[FrozenCandidate],
    *,
    rho: float,
    min_side_size: int,
    small_chain_threshold: int,
) -> tuple[CandidateScore, ...]:
    """Re-score one fixed partition set by the canonical conductance scorer."""
    candidate_models = [
        Candidate(
            source=_source(candidate.origins[0].source),
            members=frozenset(candidate.side_a),
            label=candidate.origins[0].label,
        )
        for candidate in candidates
    ]
    score_map: dict[tuple[frozenset[str], str], ConductanceResult] = {}
    if not is_chain_too_small_for_audit(
        len(graph.members), small_chain_threshold=small_chain_threshold
    ):
        scored = score_candidates(
            graph,
            candidate_models,
            chain_size=len(graph.members),
            rho=rho,
            min_side_size=min_side_size,
        )
        score_map = {
            (item.candidate.members, item.candidate.label): item.conductance
            for item in scored
        }
    result_by_id: dict[str, CandidateScore] = {}
    provisional: list[CandidateScore] = []
    for frozen, model in zip(candidates, candidate_models):
        if is_chain_too_small_for_audit(
            len(graph.members), small_chain_threshold=small_chain_threshold
        ):
            provisional.append(
                CandidateScore(
                    partition_id=frozen.partition_id,
                    status=CandidateScoreStatus.SKIPPED_SMALL_CHAIN,
                    edge_count=len(graph.edges),
                    isolate_count=sum(1 for node in graph.members if not graph.neighbours(node)),
                    reason="chain is below canonical small-chain audit threshold",
                )
            )
            continue
        result = score_map[(model.members, model.label)]
        cut_weight = _cut_weight(graph, set(frozen.side_a), set(frozen.side_b))
        volume_a = graph.volume(set(frozen.side_a))
        volume_b = graph.volume(set(frozen.side_b))
        if not frozen.side_a or not frozen.side_b:
            status = CandidateScoreStatus.EMPTY_CANDIDATE
        elif not graph.edges:
            status = CandidateScoreStatus.EMPTY_GRAPH
        elif not result.feasible:
            status = CandidateScoreStatus.INFEASIBLE
        elif result.phi is None:
            status = CandidateScoreStatus.ZERO_SIDE_VOLUME
        else:
            status = CandidateScoreStatus.SCORABLE
        provisional.append(
            CandidateScore(
                partition_id=frozen.partition_id,
                status=status,
                edge_count=len(graph.edges),
                isolate_count=sum(1 for node in graph.members if not graph.neighbours(node)),
                cut_weight=cut_weight,
                volume_a=volume_a,
                volume_b=volume_b,
                phi=result.phi if status is CandidateScoreStatus.SCORABLE else None,
                reason=result.reason if result.phi is None or not result.feasible else None,
            )
        )

    scorable = sorted(
        (item for item in provisional if item.status is CandidateScoreStatus.SCORABLE),
        key=lambda item: (item.phi, item.partition_id),
    )
    ranks = {item.partition_id: rank for rank, item in enumerate(scorable, 1)}
    return tuple(
        item.model_copy(update={"rank": ranks[item.partition_id]})
        if item.partition_id in ranks else item
        for item in provisional
    )


def production_baseline_winner(
    chain_id: str,
    graph: AuditGraph,
    candidates: Sequence[FrozenCandidate],
    *,
    epsilon_phi: float,
    rho: float,
    min_side_size: int,
    small_chain_threshold: int,
) -> tuple[str | None, str]:
    """Get baseline winner and verdict through the existing structural audit."""
    candidate_models = [
        Candidate(
            source=_source(candidate.origins[0].source),
            members=frozenset(candidate.side_a),
            label=candidate.origins[0].label,
        )
        for candidate in candidates
    ]
    result = run_structural_audit(
        chain_id,
        graph,
        candidate_models,
        epsilon=epsilon_phi,
        rho=rho,
        min_side_size=min_side_size,
        small_chain_threshold=small_chain_threshold,
    )
    if result.best_cut is None:
        return None, result.verdict.value
    winner_members = result.best_cut.candidate.members
    for frozen in candidates:
        if winner_members in {frozenset(frozen.side_a), frozenset(frozen.side_b)}:
            return frozen.partition_id, result.verdict.value
    raise CandidateSetError("canonical baseline winner is absent from frozen candidate set")


def compare_candidates(
    baseline_scores: Sequence[CandidateScore],
    variant_scores: Sequence[CandidateScore],
    *,
    production_baseline_winner_id: str | None,
    epsilon_phi: float,
    materiality: MaterialityPolicy,
) -> CandidateComparison:
    """Compare fixed-candidate winners and report regret/materiality separately."""
    baseline_by_id = {item.partition_id: item for item in baseline_scores}
    variant_by_id = {item.partition_id: item for item in variant_scores}
    if len(baseline_by_id) != len(baseline_scores) or len(variant_by_id) != len(variant_scores):
        raise CandidateSetError("duplicate partition ID in candidate scores")
    if set(baseline_by_id) != set(variant_by_id):
        raise CandidateSetError("baseline and variant candidate sets differ")
    baseline_scorable = _ranked(baseline_scores)
    variant_scorable = _ranked(variant_scores)
    baseline_diag_winner = baseline_scorable[0].partition_id if baseline_scorable else None
    variant_best = variant_scorable[0] if variant_scorable else None
    if variant_best is None:
        return CandidateComparison(
            production_baseline_winner_id=production_baseline_winner_id,
            diagnostic_tie_winner_id=baseline_diag_winner,
            variant_best_id=None,
            winner_status=WinnerStatus.NO_SCORABLE_CANDIDATE,
            regret=None,
            absolute_phi_drift=None,
            materiality_status=MaterialityStatus.NOT_COMPUTABLE,
            verdict_flip=None,
        )
    if production_baseline_winner_id is None:
        return CandidateComparison(
            production_baseline_winner_id=None,
            diagnostic_tie_winner_id=baseline_diag_winner,
            variant_best_id=variant_best.partition_id,
            winner_status=WinnerStatus.BASELINE_WINNER_UNSCORABLE,
            regret=None,
            materiality_status=MaterialityStatus.NOT_COMPUTABLE,
            verdict_flip=None,
        )
    baseline_score = baseline_by_id.get(production_baseline_winner_id)
    variant_baseline_score = variant_by_id.get(production_baseline_winner_id)
    if (
        baseline_score is None
        or baseline_score.status is not CandidateScoreStatus.SCORABLE
        or variant_baseline_score is None
        or variant_baseline_score.status is not CandidateScoreStatus.SCORABLE
    ):
        return CandidateComparison(
            production_baseline_winner_id=production_baseline_winner_id,
            diagnostic_tie_winner_id=baseline_diag_winner,
            variant_best_id=variant_best.partition_id,
            winner_status=WinnerStatus.BASELINE_WINNER_UNSCORABLE,
            regret=None,
            absolute_phi_drift=None,
            materiality_status=MaterialityStatus.NOT_COMPUTABLE,
            verdict_flip=(
                (baseline_score.phi <= epsilon_phi) != (variant_best.phi <= epsilon_phi)
                if baseline_score is not None
                and baseline_score.status is CandidateScoreStatus.SCORABLE
                and variant_best.phi is not None
                else None
            ),
        )

    assert baseline_score.phi is not None and variant_baseline_score.phi is not None
    assert variant_best.phi is not None
    raw_regret = variant_baseline_score.phi - variant_best.phi
    if raw_regret < -materiality.epsilon_num:
        raise CandidateSetError("production baseline winner scores better than selected variant best")
    regret = max(0.0, raw_regret)
    winner_changed = variant_best.partition_id != production_baseline_winner_id
    if not winner_changed:
        status = WinnerStatus.WINNER_UNCHANGED
    elif regret <= materiality.epsilon_num:
        status = WinnerStatus.NUMERICAL_TIE
    elif materiality.delta_phi is None:
        status = WinnerStatus.WINNER_CHANGED
    elif regret < materiality.delta_phi:
        status = WinnerStatus.NEAR_TIE_REORDER
    else:
        status = WinnerStatus.MATERIAL_WINNER_CHANGE
    base_verdict = baseline_score.phi <= epsilon_phi
    variant_verdict = variant_best.phi <= epsilon_phi
    return CandidateComparison(
        production_baseline_winner_id=production_baseline_winner_id,
        diagnostic_tie_winner_id=baseline_diag_winner,
        variant_best_id=variant_best.partition_id,
        winner_status=status,
        regret=regret,
        absolute_phi_drift=abs(variant_baseline_score.phi - baseline_score.phi),
        materiality_status=(
            MaterialityStatus.NOT_CONFIGURED
            if materiality.delta_phi is None
            else MaterialityStatus.CONFIGURED
        ),
        verdict_flip=base_verdict != variant_verdict,
    )


def _ranked(scores: Sequence[CandidateScore]) -> list[CandidateScore]:
    return sorted(
        (item for item in scores if item.status is CandidateScoreStatus.SCORABLE),
        key=lambda item: (item.phi, item.partition_id),
    )


def _cut_weight(graph: AuditGraph, side_a: set[str], side_b: set[str]) -> float:
    # Read canonical edge weights only. Conductance itself always comes from
    # audit.conductance.conductance via score_candidates/run_structural_audit.
    return sum(
        graph.weight(left, right)
        for left in side_a
        for right in graph.neighbours(left)
        if right in side_b
    )


def _source(value: str) -> CandidateSource:
    try:
        return CandidateSource(value)
    except ValueError as exc:
        raise CandidateSetError(f"unknown candidate source {value!r}") from exc


def _partition_digest(
    members: tuple[str, ...], side_a: tuple[str, ...], side_b: tuple[str, ...]
) -> str:
    return _digest({"members": members, "side_a": side_a, "side_b": side_b})


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
