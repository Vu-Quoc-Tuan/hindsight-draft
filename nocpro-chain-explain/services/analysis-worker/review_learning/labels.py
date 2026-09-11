"""Stable ranker label policy and group weighting.

Policy version: review-label-v1
Frozen per 2026-09-11 implementation plan.
"""

from __future__ import annotations

from typing import Iterable

from .contracts import ReviewDecision, TruthTier

LABEL_POLICY_VERSION = "review-label-v1"


def resolve_candidate_relevance(
    decision: ReviewDecision | str,
    truth_tier: TruthTier | str = TruthTier.PO_ASSERTED,
) -> int | None:
    """Resolve relevance label for grouped ranking.

    Returns:
      - 3: OUTCOME_VERIFIED approval
      - 2: EXPERT_CONSENSUS / APPLIED_CONFIRMED approval
      - 1: PO_ASSERTED / TEST_FIXTURE approval
      - 0: REJECT or OUTCOME_CONTRADICTED
      - None: DEFER, INSUFFICIENT_EVIDENCE, unreviewed (must be excluded from label vector)
    """
    d = ReviewDecision(decision) if isinstance(decision, str) else decision
    t = TruthTier(truth_tier) if isinstance(truth_tier, str) else truth_tier

    if t is TruthTier.OUTCOME_CONTRADICTED:
        return 0

    if d is ReviewDecision.APPROVE:
        if t is TruthTier.OUTCOME_VERIFIED:
            return 3
        if t in {TruthTier.EXPERT_CONSENSUS, TruthTier.APPLIED_CONFIRMED}:
            return 2
        return 1

    if d is ReviewDecision.REJECT:
        return 0

    if d in {ReviewDecision.DEFER, ReviewDecision.INSUFFICIENT_EVIDENCE, ReviewDecision.NONE_ACCEPTABLE}:
        return None

    return None


def resolve_group_weight(truth_tiers: Iterable[TruthTier | str]) -> float:
    """Derive group-level ranking weight from candidate truth tiers.

    Matches XGBRanker group weight API:
      - 1.00 for outcome-verified / contradicted evidence
      - 0.75 for expert consensus / applied confirmation
      - 0.50 for PO-only assertions
    """
    tiers = {TruthTier(t) if isinstance(t, str) else t for t in truth_tiers}
    if not tiers:
        return 0.50

    if TruthTier.OUTCOME_VERIFIED in tiers or TruthTier.OUTCOME_CONTRADICTED in tiers:
        return 1.00
    if TruthTier.EXPERT_CONSENSUS in tiers or TruthTier.APPLIED_CONFIRMED in tiers:
        return 0.75
    return 0.50
