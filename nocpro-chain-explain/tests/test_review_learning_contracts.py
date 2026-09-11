import pytest
from review_learning import (
    CandidateExposure,
    FeedbackStatus,
    ReviewDecision,
    ReviewFeedback,
    ReviewSession,
    TruthTier,
    canonical_fingerprint,
    normalize_operation_pattern,
    normalize_review_decision,
)


@pytest.mark.parametrize(
    "legacy,canonical",
    [
        ("APPROVED", ReviewDecision.APPROVE),
        ("ACCEPTED", ReviewDecision.APPROVE),
        ("REJECTED", ReviewDecision.REJECT),
        ("APPROVE", ReviewDecision.APPROVE),
        ("REJECT", ReviewDecision.REJECT),
    ],
)
def test_legacy_decisions_normalize_only_at_ingress(legacy, canonical):
    assert normalize_review_decision(legacy) == canonical


def test_none_acceptable_cannot_name_a_candidate():
    with pytest.raises(ValueError, match="NONE_ACCEPTABLE cannot name a candidate_id"):
        ReviewFeedback(
            feedback_id="fb-1",
            review_id="rev-1",
            decision=ReviewDecision.NONE_ACCEPTABLE,
            confidence=0.9,
            candidate_id="cand-1",
        )


def test_approve_requires_a_candidate_id():
    with pytest.raises(ValueError, match="APPROVE must reference a specific candidate_id"):
        ReviewFeedback(
            feedback_id="fb-1",
            review_id="rev-1",
            decision=ReviewDecision.APPROVE,
            confidence=0.9,
            candidate_id=None,
        )


def test_confidence_out_of_bounds_raises():
    with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
        ReviewFeedback(
            feedback_id="fb-1",
            review_id="rev-1",
            decision=ReviewDecision.APPROVE,
            confidence=1.5,
            candidate_id="cand-1",
        )


def test_canonical_fingerprint_is_stable_under_dict_order():
    d1 = {"b": 2, "a": 1, "nested": {"y": [1, 2], "x": True}}
    d2 = {"nested": {"x": True, "y": [1, 2]}, "a": 1, "b": 2}
    assert canonical_fingerprint(d1) == canonical_fingerprint(d2)


def test_unknown_operation_pattern_is_rejected_not_coerced_to_manual_correction():
    with pytest.raises(ValueError, match="Unsupported review operation pattern"):
        normalize_operation_pattern("RENAME_CHAIN")
