"""Integration tests verifying materializer compatibility with real PostgreSQL repository outputs."""

from __future__ import annotations

import datetime
import pytest

from review_learning import (
    CandidateExposure,
    FeedbackStatus,
    ReviewDecision,
    ReviewFeedback,
    ReviewSession,
    TruthTier,
    materialize_training_corpus,
    materialize_training_corpus_from_repository_groups,
)


def test_materializer_handles_native_datetimes():
    """Verify materializer processes native datetime objects without crash."""
    now = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
    fb_time = datetime.datetime(2026, 9, 1, 10, 5, 0, tzinfo=datetime.timezone.utc)
    cutoff = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)

    session = ReviewSession(
        review_id="rev-native-dt-1",
        job_id="job-1",
        snapshot_id="snap-1",
        snapshot_version="v1",
        chain_id="chain-1",
        review_time=now,  # Native datetime
        source_kind="OPERATOR_REVIEW",
        lineage_component_id="lineage-native-1",
        candidate_set_fingerprint="fp-1",
        generator_version="v1",
        config_version="v1",
        created_at=now,  # Native datetime
    )

    exp1 = CandidateExposure(
        review_id="rev-native-dt-1",
        candidate_id="c1",
        candidate_fingerprint="c-fp-1",
        operation="REMOVE_MEMBER",
        original_rank=1,
        displayed_rank=1,
        shown_to_reviewer=True,
        deterministic_eligibility=True,
        hard_gate_status="PASSED",
        pareto_state="FRONTIER_SELECTED",
        feature_schema_version="cf-features-v1",
        feature_payload={},  # Missing payload!
        feature_fingerprint="f-fp-1",
        created_at=now,  # Native datetime
        deterministic_context={
            "metric_deltas": {"weak_member_count": -1.0},
            "edit_cost": {"members_moved": 1},
        },
    )

    exp2 = CandidateExposure(
        review_id="rev-native-dt-1",
        candidate_id="c2",
        candidate_fingerprint="c-fp-2",
        operation="SPLIT_CHAIN",
        original_rank=2,
        displayed_rank=2,
        shown_to_reviewer=True,
        deterministic_eligibility=True,
        hard_gate_status="PASSED",
        pareto_state="DOMINATED",
        feature_schema_version="cf-features-v1",
        feature_payload={},  # Missing payload!
        feature_fingerprint="f-fp-2",
        created_at=now,  # Native datetime
        deterministic_context={
            "metric_deltas": {"weak_member_count": 0.0},
            "edit_cost": {"members_moved": 2},
        },
    )

    fb1 = ReviewFeedback(
        feedback_id="fb-1",
        review_id="rev-native-dt-1",
        candidate_id="c1",
        decision=ReviewDecision.APPROVE,
        confidence=0.9,
        truth_tier=TruthTier.PO_ASSERTED,
        status=FeedbackStatus.ACTIVE,
        created_at=fb_time,  # Native datetime
    )

    fb2 = ReviewFeedback(
        feedback_id="fb-2",
        review_id="rev-native-dt-1",
        candidate_id="c2",
        decision=ReviewDecision.REJECT,
        confidence=0.8,
        truth_tier=TruthTier.PO_ASSERTED,
        status=FeedbackStatus.ACTIVE,
        created_at=fb_time,  # Native datetime
    )

    corpus = materialize_training_corpus(
        sessions=[session],
        exposures=[exp1, exp2],
        feedbacks=[fb1, fb2],
        cutoff=cutoff,
    )

    assert corpus.train.num_groups == 1
    assert corpus.train.num_candidates == 2
    assert corpus.train.y == [1, 0]

    # Dynamic re-materialization must produce real features, not 43 zeros!
    row0 = corpus.train.X[0]
    row1 = corpus.train.X[1]
    assert len(row0) == 43
    assert any(val != 0.0 for val in row0), "Features should not be all zeros!"
    # One-hot op features: REMOVE_MEMBER is index 0
    assert row0[0] == 1.0
    # One-hot op features: SPLIT_CHAIN is index 1
    assert row1[1] == 1.0


def test_materialize_training_corpus_from_repository_groups():
    """Verify repository group adapter format matches repository.training_review_groups_before()."""
    dt = datetime.datetime(2026, 9, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
    cutoff = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)

    repo_groups = []
    for i in range(1, 15):
        sess = ReviewSession(
            review_id=f"rev-repo-{i:02d}",
            job_id=f"job-{i}",
            snapshot_id=f"snap-{i}",
            snapshot_version="v1",
            chain_id=f"chain-{i}",
            review_time=dt + datetime.timedelta(hours=i * 4),
            source_kind="OPERATOR_REVIEW",
            lineage_component_id=f"lineage-repo-{i:02d}",
            candidate_set_fingerprint=f"cs-fp-{i}",
            generator_version="v1",
            config_version="v1",
            created_at=dt + datetime.timedelta(hours=i * 4),
        )

        exps = [
            CandidateExposure(
                review_id=sess.review_id,
                candidate_id=f"{sess.review_id}-c1",
                candidate_fingerprint=f"cfp-{i}-1",
                operation="REMOVE_MEMBER",
                original_rank=1,
                displayed_rank=1,
                shown_to_reviewer=True,
                deterministic_eligibility=True,
                hard_gate_status="PASSED",
                pareto_state="FRONTIER_SELECTED",
                feature_schema_version="cf-features-v1",
                feature_payload={},
                feature_fingerprint="ffp-1",
                created_at=sess.created_at,
                deterministic_context={"metric_deltas": {"weak_member_count": -1.0}},
            ),
            CandidateExposure(
                review_id=sess.review_id,
                candidate_id=f"{sess.review_id}-c2",
                candidate_fingerprint=f"cfp-{i}-2",
                operation="MOVE_MEMBER",
                original_rank=2,
                displayed_rank=2,
                shown_to_reviewer=True,
                deterministic_eligibility=True,
                hard_gate_status="PASSED",
                pareto_state="DOMINATED",
                feature_schema_version="cf-features-v1",
                feature_payload={},
                feature_fingerprint="ffp-2",
                created_at=sess.created_at,
                deterministic_context={"metric_deltas": {"weak_member_count": 0.0}},
            ),
        ]

        fbs = [
            ReviewFeedback(
                feedback_id=f"fb-{i}-1",
                review_id=sess.review_id,
                candidate_id=f"{sess.review_id}-c1",
                decision=ReviewDecision.APPROVE,
                confidence=0.9,
                truth_tier=TruthTier.PO_ASSERTED,
                status=FeedbackStatus.ACTIVE,
                created_at=sess.created_at,
            ),
            ReviewFeedback(
                feedback_id=f"fb-{i}-2",
                review_id=sess.review_id,
                candidate_id=f"{sess.review_id}-c2",
                decision=ReviewDecision.REJECT,
                confidence=0.8,
                truth_tier=TruthTier.PO_ASSERTED,
                status=FeedbackStatus.ACTIVE,
                created_at=sess.created_at,
            ),
        ]

        repo_groups.append(
            {
                "review_session": sess,
                "candidate_exposures": exps,
                "active_feedbacks": fbs,
            }
        )

    corpus = materialize_training_corpus_from_repository_groups(
        groups=repo_groups,
        cutoff=cutoff,
    )

    assert corpus.train.num_groups >= 8
    assert corpus.val.num_groups >= 2
    assert corpus.test.num_groups >= 2
    assert corpus.corpus_fingerprint != ""

    # Verify data profile directly from repository groups without raw_sessions
    from review_learning import build_data_profile
    profile = build_data_profile(corpus, raw_sessions=None)
    assert profile.lineage_overlap_detected is False
    assert profile.total_groups >= 12
    assert len(profile.operation_coverage) >= 2
    assert profile.time_span["min"] != "N/A"
    assert profile.time_span["max"] != "N/A"


def test_materializer_rejects_missing_lineage():
    """Verify that sessions with missing or UNAVAILABLE lineage are excluded fail-closed."""
    now = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
    cutoff = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)

    # Session with NO lineage
    session_no_lin = ReviewSession(
        review_id="rev-no-lin",
        job_id="job-no-lin",
        snapshot_id="snap-1",
        snapshot_version="v1",
        chain_id="chain-1",
        review_time=now,
        source_kind="OPERATOR_REVIEW",
        lineage_component_id=None,  # Missing!
        candidate_set_fingerprint="fp-1",
        generator_version="v1",
        config_version="v1",
        created_at=now,
    )

    exp1 = CandidateExposure(
        review_id="rev-no-lin",
        candidate_id="c1",
        candidate_fingerprint="c-fp-1",
        operation="REMOVE_MEMBER",
        original_rank=1,
        displayed_rank=1,
        deterministic_eligibility=True,
        hard_gate_status="PASSED",
        pareto_state="FRONTIER_SELECTED",
        created_at=now,
    )
    exp2 = CandidateExposure(
        review_id="rev-no-lin",
        candidate_id="c2",
        candidate_fingerprint="c-fp-2",
        operation="SPLIT_CHAIN",
        original_rank=2,
        displayed_rank=2,
        deterministic_eligibility=True,
        hard_gate_status="PASSED",
        pareto_state="DOMINATED",
        created_at=now,
    )

    fb1 = ReviewFeedback(
        feedback_id="fb-1",
        review_id="rev-no-lin",
        candidate_id="c1",
        decision=ReviewDecision.APPROVE,
        confidence=0.9,
        truth_tier=TruthTier.PO_ASSERTED,
        created_at=now,
    )
    fb2 = ReviewFeedback(
        feedback_id="fb-2",
        review_id="rev-no-lin",
        candidate_id="c2",
        decision=ReviewDecision.REJECT,
        confidence=0.8,
        truth_tier=TruthTier.PO_ASSERTED,
        created_at=now,
    )

    corpus = materialize_training_corpus(
        sessions=[session_no_lin],
        exposures=[exp1, exp2],
        feedbacks=[fb1, fb2],
        cutoff=cutoff,
    )

    assert corpus.train.num_groups == 0
    assert len(corpus.excluded_groups) == 1
    assert corpus.excluded_groups[0].reason == "LINEAGE_UNAVAILABLE"


def test_materializer_detects_feature_fingerprint_tampering():
    """Verify that feature payload tampering is detected and fails closed."""
    from review_learning import canonical_fingerprint
    now = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
    cutoff = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)

    session = ReviewSession(
        review_id="rev-tamper",
        job_id="job-1",
        snapshot_id="snap-1",
        snapshot_version="v1",
        chain_id="chain-1",
        review_time=now,
        source_kind="OPERATOR_REVIEW",
        lineage_component_id="lineage-tamper-1",
        candidate_set_fingerprint="fp-1",
        generator_version="v1",
        config_version="v1",
        created_at=now,
    )

    orig_features = {"op__remove": 1.0, "delta__weak_member_count": -1.0}
    orig_fp = canonical_fingerprint(orig_features)

    # Tampered payload (different from orig_fp!)
    tampered_features = {"op__remove": 0.0, "delta__weak_member_count": 999.0}

    exp1 = CandidateExposure(
        review_id="rev-tamper",
        candidate_id="c1",
        candidate_fingerprint="c-fp-1",
        operation="REMOVE_MEMBER",
        original_rank=1,
        displayed_rank=1,
        deterministic_eligibility=True,
        hard_gate_status="PASSED",
        pareto_state="FRONTIER_SELECTED",
        feature_payload=tampered_features,
        feature_fingerprint=orig_fp,  # Fingerprint does NOT match payload!
        created_at=now,
    )
    exp2 = CandidateExposure(
        review_id="rev-tamper",
        candidate_id="c2",
        candidate_fingerprint="c-fp-2",
        operation="SPLIT_CHAIN",
        original_rank=2,
        displayed_rank=2,
        deterministic_eligibility=True,
        hard_gate_status="PASSED",
        pareto_state="DOMINATED",
        created_at=now,
    )

    fb1 = ReviewFeedback(
        feedback_id="fb-1",
        review_id="rev-tamper",
        candidate_id="c1",
        decision=ReviewDecision.APPROVE,
        created_at=now,
    )
    fb2 = ReviewFeedback(
        feedback_id="fb-2",
        review_id="rev-tamper",
        candidate_id="c2",
        decision=ReviewDecision.REJECT,
        created_at=now,
    )

    corpus = materialize_training_corpus(
        sessions=[session],
        exposures=[exp1, exp2],
        feedbacks=[fb1, fb2],
        cutoff=cutoff,
    )

    assert corpus.train.num_groups == 0
    assert len(corpus.excluded_groups) == 1
    assert corpus.excluded_groups[0].reason == "FEATURE_FINGERPRINT_MISMATCH"


def test_materializer_manual_correction_candidate_matching():
    """Verify manual correction matching: matching candidate is approved; non-matching leaves no positive."""
    from review_learning import ManualCorrection
    now = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
    cutoff = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)

    session = ReviewSession(
        review_id="rev-mc",
        job_id="job-mc",
        snapshot_id="snap-1",
        snapshot_version="v1",
        chain_id="chain-1",
        review_time=now,
        source_kind="OPERATOR_REVIEW",
        lineage_component_id="lineage-mc-1",
        candidate_set_fingerprint="fp-1",
        generator_version="v1",
        config_version="v1",
        created_at=now,
    )

    exp1 = CandidateExposure(
        review_id="rev-mc",
        candidate_id="c1",
        candidate_fingerprint="c-fp-1",
        operation="MOVE_MEMBER",
        original_rank=1,
        displayed_rank=1,
        deterministic_eligibility=True,
        hard_gate_status="PASSED",
        pareto_state="FRONTIER_SELECTED",
        created_at=now,
        deterministic_context={
            "partition_delta": {"before": [("ch1", ["alm-1"])], "after": [("ch2", ["alm-1"])]}
        },
    )
    exp2 = CandidateExposure(
        review_id="rev-mc",
        candidate_id="c2",
        candidate_fingerprint="c-fp-2",
        operation="SPLIT_CHAIN",
        original_rank=2,
        displayed_rank=2,
        deterministic_eligibility=True,
        hard_gate_status="PASSED",
        pareto_state="DOMINATED",
        created_at=now,
        deterministic_context={
            "partition_delta": {"before": [("ch1", ["alm-1"])], "after": [("ch1", []), ("ch1b", ["alm-1"])]}
        },
    )

    # Operator created manual correction that matches c1's delta
    mc_matching = ManualCorrection(
        correction_id="mc-1",
        feedback_id="fb-mc",
        operation="MOVE_MEMBER",
        partition_delta={"before": [("ch1", ["alm-1"])], "after": [("ch2", ["alm-1"])]},
        correction_fingerprint="cfp-1",
        created_at=now,
    )

    fb_mc = ReviewFeedback(
        feedback_id="fb-mc",
        review_id="rev-mc",
        candidate_id=None,
        decision=ReviewDecision.MANUAL_CORRECTION,
        manual_correction=mc_matching,
        truth_tier=TruthTier.PO_ASSERTED,
        created_at=now,
    )

    corpus = materialize_training_corpus(
        sessions=[session],
        exposures=[exp1, exp2],
        feedbacks=[fb_mc],
        cutoff=cutoff,
    )

    assert corpus.train.num_groups == 1
    assert corpus.train.y == [1, 0]  # c1 approved via manual correction match! c2 rejected.


def test_load_ranker_artifact_rejects_missing_checksum(tmp_path):
    """Verify that load_ranker_artifact fails closed if artifact_sha256 is empty or missing."""
    from review_learning import RankerArtifactManifest, RankerMetrics, load_ranker_artifact

    model_file = tmp_path / "model.json"
    manifest_file = tmp_path / "manifest.json"

    # Write dummy model file
    model_file.write_text("{}", encoding="utf-8")

    # Manifest with empty artifact_sha256
    manifest = RankerArtifactManifest(
        model_version="v1",
        model_family="XGBRanker",
        feature_schema_version="cf-features-v1",
        label_policy_version="review-label-v1",
        training_cutoff="2026-09-10T00:00:00Z",
        corpus_fingerprint="fp-1",
        hyperparameters={},
        metrics=RankerMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        slice_metrics={},
        artifact_sha256="",  # Missing / empty!
    )
    manifest_file.write_text(manifest.to_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required artifact_sha256 checksum"):
        load_ranker_artifact(tmp_path)


def test_materializer_protected_mode_rejects_unverified_lineage_and_missing_features():
    """Verify that protected_mode enforces strict fail-closed requirements on real data:
    1. Rejects unverified fallback lineages (fallback_lineage:...)
    2. Rejects missing/empty feature_schema_version
    3. Rejects missing/empty feature_fingerprint
    4. Rejects missing precomputed features payload
    """
    from review_learning import generate_synthetic_review_group, materialize_training_corpus
    from dataclasses import replace

    s, e, f = generate_synthetic_review_group(
        review_id="rev-prot-1",
        lineage_component_id="fallback_lineage:chain_99",
        review_time="2026-09-01T10:00:00Z",
        scenario="STANDARD_TOP1_APPROVED",
    )

    # 1. Reject unverified fallback lineage
    corpus = materialize_training_corpus(
        sessions=[s],
        exposures=e,
        feedbacks=f,
        cutoff="2026-09-10T00:00:00Z",
        protected_mode=True,
    )
    assert corpus.train.num_groups == 0
    assert len(corpus.excluded_groups) == 1
    assert corpus.excluded_groups[0].reason == "UNVERIFIED_LINEAGE_FALLBACK"

    # Fix lineage to verified
    s_verified = replace(s, lineage_component_id="comp_verified_01")

    # 2. Reject missing feature_schema_version in protected mode
    e_no_schema = [replace(exp, feature_schema_version="") for exp in e]
    corpus_schema = materialize_training_corpus(
        sessions=[s_verified],
        exposures=e_no_schema,
        feedbacks=f,
        cutoff="2026-09-10T00:00:00Z",
        protected_mode=True,
    )
    assert corpus_schema.train.num_groups == 0
    assert any(g.reason == "FEATURE_SCHEMA_VERSION_MISMATCH" for g in corpus_schema.excluded_groups)

    # 3. Reject missing feature_fingerprint in protected mode
    e_no_fp = [replace(exp, feature_fingerprint="") for exp in e]
    corpus_fp = materialize_training_corpus(
        sessions=[s_verified],
        exposures=e_no_fp,
        feedbacks=f,
        cutoff="2026-09-10T00:00:00Z",
        protected_mode=True,
    )
    assert corpus_fp.train.num_groups == 0
    assert any(g.reason == "FEATURE_FINGERPRINT_MISMATCH" for g in corpus_fp.excluded_groups)

    # 4. Reject missing precomputed features in protected mode
    e_no_feat = [replace(exp, feature_payload={}) for exp in e]
    corpus_feat = materialize_training_corpus(
        sessions=[s_verified],
        exposures=e_no_feat,
        feedbacks=f,
        cutoff="2026-09-10T00:00:00Z",
        protected_mode=True,
    )
    assert corpus_feat.train.num_groups == 0
    assert any(g.reason == "FEATURE_SCHEMA_VERSION_MISMATCH" for g in corpus_feat.excluded_groups)

    # 5. When all valid and verified, protected mode successfully materializes
    corpus_valid = materialize_training_corpus(
        sessions=[s_verified],
        exposures=e,
        feedbacks=f,
        cutoff="2026-09-10T00:00:00Z",
        protected_mode=True,
    )
    assert corpus_valid.train.num_groups == 1
    assert len(corpus_valid.excluded_groups) == 0
