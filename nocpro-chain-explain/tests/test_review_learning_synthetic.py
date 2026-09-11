from review_learning import (
    FeedbackStatus,
    ReviewDecision,
    TruthTier,
    generate_synthetic_review_group,
)


def test_synthetic_factory_standard_scenario():
    session, exposures, feedbacks = generate_synthetic_review_group(
        review_id="rev-syn-1",
        chain_id="chain-syn-10",
        scenario="STANDARD_TOP1_APPROVED",
    )
    assert session.source_kind == "SYNTHETIC_TEST"
    assert session.review_id == "rev-syn-1"
    assert len(exposures) == 4
    assert len(feedbacks) == 4
    # Provenance is TEST_FIXTURE
    assert feedbacks[0].truth_tier == TruthTier.TEST_FIXTURE

    # Top 1 is approved, rest rejected
    assert feedbacks[0].decision is ReviewDecision.APPROVE
    assert feedbacks[0].candidate_id == exposures[0].candidate_id
    assert feedbacks[1].decision is ReviewDecision.REJECT
    assert feedbacks[2].decision is ReviewDecision.REJECT
    assert feedbacks[3].decision is ReviewDecision.REJECT


def test_synthetic_factory_none_acceptable():
    session, exposures, feedbacks = generate_synthetic_review_group(
        review_id="rev-syn-2",
        scenario="NONE_ACCEPTABLE",
    )
    assert session.source_kind == "SYNTHETIC_TEST"
    assert len(exposures) == 3
    assert len(feedbacks) == 1
    assert feedbacks[0].decision is ReviewDecision.NONE_ACCEPTABLE
    assert feedbacks[0].candidate_id is None
    assert feedbacks[0].truth_tier == TruthTier.TEST_FIXTURE


def test_synthetic_factory_manual_correction():
    session, exposures, feedbacks = generate_synthetic_review_group(
        review_id="rev-syn-3",
        scenario="MANUAL_CORRECTION",
    )
    assert len(feedbacks) == 1
    assert feedbacks[0].decision is ReviewDecision.MANUAL_CORRECTION
    assert feedbacks[0].manual_correction is not None
    assert feedbacks[0].manual_correction.operation == "MOVE_MEMBER"
    assert feedbacks[0].truth_tier == TruthTier.TEST_FIXTURE


def test_synthetic_factory_unreviewed_and_superseded():
    session, exposures, feedbacks = generate_synthetic_review_group(
        review_id="rev-syn-4",
        scenario="UNREVIEWED_AND_SUPERSEDED",
    )
    assert len(exposures) == 3
    # Feedbacks: 1 superseded reject for c1, 1 active approve for c1, 1 active reject for c2, none for c3
    assert len(feedbacks) == 3
    superseded = [fb for fb in feedbacks if fb.status is FeedbackStatus.SUPERSEDED]
    active = [fb for fb in feedbacks if fb.status is FeedbackStatus.ACTIVE]
    assert len(superseded) == 1
    assert len(active) == 2


def test_synthetic_factory_duplicate_lineage():
    session, exposures, feedbacks = generate_synthetic_review_group(
        review_id="rev-syn-dup",
        scenario="DUPLICATE_LINEAGE",
    )
    assert len(exposures) == 3
    assert len(feedbacks) == 3
    assert all(fb.truth_tier == TruthTier.TEST_FIXTURE for fb in feedbacks)
def test_synthetic_factory_feature_tampering():
    session, exposures, feedbacks = generate_synthetic_review_group(
        review_id="rev-syn-tamper",
        scenario="FEATURE_TAMPERING",
    )
    assert len(exposures) == 2
    assert exposures[0].feature_fingerprint == "tampered_hash_bad_sha256_deadbeef"


def test_synthetic_factory_retracted_feedback():
    session, exposures, feedbacks = generate_synthetic_review_group(
        review_id="rev-syn-retract",
        scenario="RETRACTED_FEEDBACK",
    )
    assert len(exposures) == 2
    assert len(feedbacks) == 2
    assert feedbacks[0].status == FeedbackStatus.RETRACTED
    assert feedbacks[1].status == FeedbackStatus.ACTIVE


def test_synthetic_factory_all_scenarios_truth_tier_fixture():
    from review_learning import generate_synthetic_review_corpus
    sessions, exposures, feedbacks = generate_synthetic_review_corpus(group_count=50)
    assert len(feedbacks) > 0
    assert all(fb.truth_tier == TruthTier.TEST_FIXTURE for fb in feedbacks)
