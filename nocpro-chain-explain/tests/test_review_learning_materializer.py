from review_learning import (
    generate_synthetic_review_group,
    materialize_training_corpus,
)


def test_materializer_filters_cutoff_strictly():
    # Session 1 at 2026-09-01
    s1, e1, f1 = generate_synthetic_review_group(
        review_id="rev-1",
        review_time="2026-09-01T10:00:00Z",
        scenario="STANDARD_TOP1_APPROVED",
    )
    # Session 2 at 2026-09-10 (future relative to cutoff 2026-09-05)
    s2, e2, f2 = generate_synthetic_review_group(
        review_id="rev-2",
        review_time="2026-09-10T10:00:00Z",
        scenario="STANDARD_TOP1_APPROVED",
    )

    corpus = materialize_training_corpus(
        sessions=[s1, s2],
        exposures=e1 + e2,
        feedbacks=f1 + f2,
        cutoff="2026-09-05T00:00:00Z",
    )

    # rev-2 must be excluded because it's after cutoff
    assert corpus.train.num_groups == 1
    assert corpus.train.review_ids == ["rev-1"]
    excluded_rids = [x.review_id for x in corpus.excluded_groups]
    assert "rev-2" in excluded_rids


def test_materializer_unreviewed_and_superseded_resolution():
    # rev-3 has c1 (superseded reject -> active approve), c2 (active reject), c3 (unreviewed)
    s, e, f = generate_synthetic_review_group(
        review_id="rev-3",
        review_time="2026-09-01T10:00:00Z",
        scenario="UNREVIEWED_AND_SUPERSEDED",
    )

    corpus = materialize_training_corpus(
        sessions=[s],
        exposures=e,
        feedbacks=f,
        cutoff="2026-09-05T00:00:00Z",
    )

    assert corpus.train.num_groups == 1
    # Only 2 labeled candidates (c1 and c2). c3 is unreviewed and excluded!
    assert corpus.train.num_candidates == 2
    assert corpus.train.y == [1, 0]  # c1 is approved (relevance 1), c2 is rejected (relevance 0)


def test_materializer_drops_groups_without_preference_gradient():
    s, e, f = generate_synthetic_review_group(
        review_id="rev-uniform",
        review_time="2026-09-01T10:00:00Z",
        scenario="UNIFORM_LABELS",
    )

    corpus = materialize_training_corpus(
        sessions=[s],
        exposures=e,
        feedbacks=f,
        cutoff="2026-09-05T00:00:00Z",
    )

    assert corpus.train.num_groups == 0
    assert len(corpus.excluded_groups) == 1
    assert corpus.excluded_groups[0].reason == "NO_PREFERENCE_GRADIENT"


def test_materializer_lineage_holdout_prevents_leakage():
    # Create 6 review groups across time
    # Groups 1, 2, 3 in early time
    # Groups 4, 5, 6 in later time
    # Group 1 and Group 5 share lineage "lineage-SHARED"!
    sessions = []
    exposures = []
    feedbacks = []

    for i in range(1, 7):
        lin = "lineage-SHARED" if i in {1, 5} else f"lineage-{i}"
        dt = f"2026-09-0{i}T10:00:00Z"
        s, e, f = generate_synthetic_review_group(
            review_id=f"rev-leak-{i}",
            lineage_component_id=lin,
            review_time=dt,
            scenario="STANDARD_TOP1_APPROVED",
        )
        sessions.append(s)
        exposures.extend(e)
        feedbacks.extend(f)

    corpus = materialize_training_corpus(
        sessions=sessions,
        exposures=exposures,
        feedbacks=feedbacks,
        cutoff="2026-09-10T00:00:00Z",
        val_ratio=0.2,
        test_ratio=0.2,
    )

    # rev-leak-1 is in train. rev-leak-5 shares lineage with it, so rev-leak-5 MUST be in train, not in val/test!
    train_qids = set(corpus.train.review_ids)
    val_qids = set(corpus.val.review_ids)
    test_qids = set(corpus.test.review_ids)

    assert "rev-leak-1" in train_qids
    assert "rev-leak-5" in train_qids
    assert "rev-leak-5" not in val_qids
    assert "rev-leak-5" not in test_qids


def test_materializer_strict_temporal_holdout_embargoes_straddling_lineage():
    sessions = []
    exposures = []
    feedbacks = []

    for i in range(1, 7):
        lin = "lineage-SHARED" if i in {1, 5} else f"lineage-{i}"
        dt = f"2026-09-0{i}T10:00:00Z"
        s, e, f = generate_synthetic_review_group(
            review_id=f"rev-strict-{i}",
            lineage_component_id=lin,
            review_time=dt,
            scenario="STANDARD_TOP1_APPROVED",
        )
        sessions.append(s)
        exposures.extend(e)
        feedbacks.extend(f)

    corpus = materialize_training_corpus(
        sessions=sessions,
        exposures=exposures,
        feedbacks=feedbacks,
        cutoff="2026-09-10T00:00:00Z",
        val_ratio=0.2,
        test_ratio=0.2,
        strict_temporal_holdout=True,
    )

    # In strict mode, lineage-SHARED straddles the train-val boundary (day 1 vs day 5).
    # To prevent BOTH lineage leakage and temporal inversion, it must be embargoed!
    train_qids = set(corpus.train.review_ids)
    val_qids = set(corpus.val.review_ids)
    test_qids = set(corpus.test.review_ids)

    assert "rev-strict-1" not in train_qids
    assert "rev-strict-5" not in train_qids
    assert "rev-strict-1" not in val_qids
    assert "rev-strict-5" not in val_qids
    assert "rev-strict-1" not in test_qids
    assert "rev-strict-5" not in test_qids

    embargoed = [g for g in corpus.excluded_groups if g.reason == "STRADDLING_LINEAGE_EMBARGO"]
    assert len(embargoed) == 2
    embargoed_rids = {g.review_id for g in embargoed}
    assert embargoed_rids == {"rev-strict-1", "rev-strict-5"}

    # Verify zero temporal inversion
    from review_learning import build_data_profile
    profile = build_data_profile(corpus, sessions)
    assert profile.lineage_overlap_detected is False
    assert profile.temporal_inversion_detected is False
