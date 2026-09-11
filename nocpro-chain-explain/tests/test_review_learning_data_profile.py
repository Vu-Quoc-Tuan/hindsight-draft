from review_learning import (
    build_data_profile,
    generate_synthetic_review_group,
    materialize_training_corpus,
)


def test_data_profile_generation_and_metrics():
    sessions = []
    exposures = []
    feedbacks = []

    for i in range(1, 7):
        lin = "lineage-SHARED" if i in {1, 5} else f"lineage-{i}"
        dt = f"2026-09-0{i}T10:00:00Z"
        s, e, f = generate_synthetic_review_group(
            review_id=f"rev-prof-{i}",
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
    )

    report = build_data_profile(corpus, sessions)
    assert report.total_groups == 6
    assert report.total_candidates == 24
    assert report.total_positives == 6
    assert report.total_negatives == 18
    assert report.lineage_overlap_detected is False
    assert report.lineage_overlap_count == 0

    # Markdown rendering check
    md = report.to_markdown()
    assert "# Training Corpus Data Profile" in md
    assert "**Lineage Overlap Detected:** `NO (VERIFIED)`" in md
    assert "REMOVE_MEMBER" in md
