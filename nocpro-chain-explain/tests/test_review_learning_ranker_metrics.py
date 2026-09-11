import math
from review_learning import (
    RankerArtifactManifest,
    RankerMetrics,
    dcg_at_k,
    evaluate_deterministic_baseline,
    evaluate_predictions,
    generate_synthetic_review_group,
    materialize_training_corpus,
    ndcg_at_k,
)


def test_ndcg_at_k_calculation():
    # Ideal ranking [3, 2, 0] scored as [10.0, 5.0, 1.0] -> NDCG = 1.0
    y_true = [3, 2, 0]
    y_score = [10.0, 5.0, 1.0]
    assert math.isclose(ndcg_at_k(y_true, y_score, 3), 1.0)

    # Worst ranking [3, 2, 0] scored as [1.0, 5.0, 10.0] -> NDCG < 1.0
    y_score_bad = [1.0, 5.0, 10.0]
    ndcg_bad = ndcg_at_k(y_true, y_score_bad, 3)
    assert 0.0 < ndcg_bad < 1.0


def test_evaluate_deterministic_baseline():
    s, e, f = generate_synthetic_review_group(
        review_id="rev-base-1",
        scenario="STANDARD_TOP1_APPROVED",
    )
    corpus = materialize_training_corpus(
        sessions=[s],
        exposures=e,
        feedbacks=f,
        cutoff="2026-09-10T00:00:00Z",
    )
    metrics = evaluate_deterministic_baseline(corpus.train)
    # In STANDARD_TOP1_APPROVED, candidate 1 (original rank 1) is approved (y=1)
    # So deterministic order puts it at top 1 -> NDCG@1 must be 1.0!
    assert math.isclose(metrics.ndcg_1, 1.0)
    assert math.isclose(metrics.top1_approved_recall, 1.0)


def test_ranker_artifact_manifest_serialization():
    metrics = RankerMetrics(
        ndcg_1=0.90,
        ndcg_3=0.85,
        ndcg_5=0.80,
        top1_approved_recall=0.75,
        top3_approved_recall=0.90,
        baseline_ndcg_3=0.70,
        ndcg_improvement=0.15,
    )
    manifest = RankerArtifactManifest(
        model_version="xgb-v1-test",
        model_family="xgboost",
        feature_schema_version="cf-features-v1",
        label_policy_version="review-label-v1",
        training_cutoff="2026-09-01T00:00:00Z",
        corpus_fingerprint="fp12345",
        hyperparameters={"max_depth": 4},
        metrics=metrics,
        slice_metrics={},
        artifact_sha256="sha256:abc",
    )
    payload = manifest.to_json()
    loaded = RankerArtifactManifest.from_json(payload)
    assert loaded.model_version == "xgb-v1-test"
    assert math.isclose(loaded.metrics.ndcg_3, 0.85)
    assert math.isclose(loaded.metrics.ndcg_improvement, 0.15)
