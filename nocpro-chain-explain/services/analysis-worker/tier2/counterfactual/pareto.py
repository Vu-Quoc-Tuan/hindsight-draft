"""Deterministic Pareto frontier selection for evaluated alternatives."""

from __future__ import annotations

from dataclasses import dataclass

from .config import CounterfactualConfig
from .evaluator import metric_delta, required_metric_names
from .models import CandidateEvaluation, CandidateStatus, Operation


@dataclass(frozen=True)
class FrontierResult:
    items: tuple[CandidateEvaluation, ...]
    all_items: tuple[CandidateEvaluation, ...]
    count_before_limit: int
    truncated: bool


def dominates(
    left: CandidateEvaluation,
    right: CandidateEvaluation,
    config: CounterfactualConfig,
) -> bool:
    if left.after is None or right.after is None:
        return False
    deltas = [
        metric_delta(name, left.after, right.after)
        for name in required_metric_names()
    ]
    if any(delta is None for delta in deltas):
        return False
    numeric = [float(delta) for delta in deltas if delta is not None]
    return all(delta >= -config.pareto_tolerance for delta in numeric) and any(
        delta > config.pareto_tolerance for delta in numeric
    )


def _frontier_order(evaluation: CandidateEvaluation):
    return (
        evaluation.status is not CandidateStatus.EXTERNALLY_SUPPORTED,
        -len(evaluation.materially_improved_metrics),
        evaluation.candidate.edit_cost,
        0 if evaluation.candidate.operation is Operation.REMOVE_MEMBER else 1,
        evaluation.candidate.candidate_id,
    )


def select_frontier(
    evaluations: tuple[CandidateEvaluation, ...],
    config: CounterfactualConfig,
) -> FrontierResult:
    eligible = tuple(
        evaluation
        for evaluation in evaluations
        if evaluation.status
        in {CandidateStatus.BETTER_SUPPORTED, CandidateStatus.EXTERNALLY_SUPPORTED}
    )
    frontier = tuple(
        candidate
        for candidate in eligible
        if not any(
            other.candidate.candidate_id != candidate.candidate.candidate_id
            and dominates(other, candidate, config)
            for other in eligible
        )
    )
    ordered = tuple(sorted(frontier, key=_frontier_order))
    return FrontierResult(
        items=ordered[: config.max_recommendations],
        all_items=ordered,
        count_before_limit=len(ordered),
        truncated=len(ordered) > config.max_recommendations,
    )
