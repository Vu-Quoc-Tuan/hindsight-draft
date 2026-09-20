from review_learning import (
    ReviewDecision,
    TruthTier,
    resolve_candidate_relevance,
    resolve_group_weight,
)


def test_relevance_label_resolution_by_truth_tier():
    # APPROVE
    assert resolve_candidate_relevance(ReviewDecision.APPROVE, TruthTier.OUTCOME_VERIFIED) == 3
    assert resolve_candidate_relevance(ReviewDecision.APPROVE, TruthTier.EXPERT_CONSENSUS) == 2
    assert resolve_candidate_relevance(ReviewDecision.APPROVE, TruthTier.APPLIED_CONFIRMED) == 2
    assert resolve_candidate_relevance(ReviewDecision.APPROVE, TruthTier.PO_ASSERTED) == 1

    # REJECT / OUTCOME_CONTRADICTED
    assert resolve_candidate_relevance(ReviewDecision.REJECT, TruthTier.PO_ASSERTED) == 0
    assert resolve_candidate_relevance(ReviewDecision.REJECT, TruthTier.OUTCOME_VERIFIED) == 0
    assert resolve_candidate_relevance(ReviewDecision.APPROVE, TruthTier.OUTCOME_CONTRADICTED) == 0

    # DEFER / INSUFFICIENT / NONE_ACCEPTABLE
    assert resolve_candidate_relevance(ReviewDecision.DEFER, TruthTier.PO_ASSERTED) is None
    assert resolve_candidate_relevance(ReviewDecision.INSUFFICIENT_EVIDENCE, TruthTier.PO_ASSERTED) is None
    assert resolve_candidate_relevance(ReviewDecision.NONE_ACCEPTABLE, TruthTier.PO_ASSERTED) is None


def test_group_weight_resolution():
    # Outcome verified / contradicted
    assert resolve_group_weight([TruthTier.OUTCOME_VERIFIED, TruthTier.PO_ASSERTED]) == 1.00
    assert resolve_group_weight([TruthTier.OUTCOME_CONTRADICTED]) == 1.00

    # Expert consensus / applied confirmed
    assert resolve_group_weight([TruthTier.EXPERT_CONSENSUS, TruthTier.PO_ASSERTED]) == 0.75
    assert resolve_group_weight([TruthTier.APPLIED_CONFIRMED]) == 0.75

    # PO-only
    assert resolve_group_weight([TruthTier.PO_ASSERTED, TruthTier.PO_ASSERTED]) == 0.50
    assert resolve_group_weight([]) == 0.50
