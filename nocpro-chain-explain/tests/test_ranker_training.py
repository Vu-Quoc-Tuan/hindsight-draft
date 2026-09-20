"""Tests for XGBRanker offline model training, evaluation, and artifact integrity."""

from __future__ import annotations

import tempfile
import pytest

from review_learning import (
    FEATURE_SCHEMA_VERSION,
    LABEL_POLICY_VERSION,
    RankerArtifactManifest,
    generate_synthetic_review_corpus,
    load_ranker_artifact,
    materialize_training_corpus,
    save_ranker_artifact,
    train_xgbranker,
)


@pytest.fixture
def synthetic_corpus():
    sessions, exposures, feedbacks = generate_synthetic_review_corpus(
        group_count=30,
        base_date="2026-09-01T10:00:00Z",
    )
    corpus = materialize_training_corpus(
        sessions=sessions,
        exposures=exposures,
        feedbacks=feedbacks,
        cutoff="2026-09-10T00:00:00Z",
    )
    return corpus


def test_xgbranker_train_and_evaluate(synthetic_corpus):
    """Verify XGBRanker trains on valid synthetic groups with non-empty val split."""
    assert synthetic_corpus.train.num_groups >= 10
    assert synthetic_corpus.val.num_groups >= 2
    assert synthetic_corpus.test.num_groups >= 2

    model, metrics = train_xgbranker(
        train_ds=synthetic_corpus.train,
        val_ds=synthetic_corpus.val,
        params={"n_estimators": 10, "max_depth": 3, "random_state": 42},
    )

    assert model is not None
    assert metrics.ndcg_1 >= 0.0 and metrics.ndcg_1 <= 1.0
    assert metrics.ndcg_3 >= 0.0 and metrics.ndcg_3 <= 1.0
    assert metrics.ndcg_5 >= 0.0 and metrics.ndcg_5 <= 1.0
    assert metrics.mean_regret >= 0.0
    assert metrics.top1_approved_recall >= 0.0 and metrics.top1_approved_recall <= 1.0
    assert metrics.top3_approved_recall >= 0.0 and metrics.top3_approved_recall <= 1.0


def test_xgbranker_save_and_load_artifact(synthetic_corpus):
    """Verify model and manifest artifact persistence and exact prediction reproducibility."""
    model, metrics = train_xgbranker(
        train_ds=synthetic_corpus.train,
        val_ds=synthetic_corpus.val,
        params={"n_estimators": 10, "max_depth": 3, "random_state": 42},
    )

    manifest = RankerArtifactManifest(
        model_version="v1-test",
        model_family="XGBRanker",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        label_policy_version=LABEL_POLICY_VERSION,
        training_cutoff=synthetic_corpus.cutoff,
        corpus_fingerprint=synthetic_corpus.corpus_fingerprint,
        hyperparameters={"n_estimators": 10, "max_depth": 3},
        metrics=metrics,
        slice_metrics={},
        artifact_sha256="",
        approval_status="DRAFT",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        model_file, manifest_file = save_ranker_artifact(model, manifest, tmpdir)
        assert model_file.exists()
        assert manifest_file.exists()

        # Load and verify
        loaded_model, loaded_manifest = load_ranker_artifact(tmpdir)
        assert loaded_manifest.model_version == "v1-test"
        assert loaded_manifest.artifact_sha256 != ""

        # Bit-for-bit prediction reproducibility
        orig_preds = model.predict(synthetic_corpus.test.X)
        loaded_preds = loaded_model.predict(synthetic_corpus.test.X)
        assert list(orig_preds) == list(loaded_preds)


def test_xgbranker_tamper_detection(synthetic_corpus):
    """Verify load_ranker_artifact fails closed if model artifact is tampered with."""
    model, metrics = train_xgbranker(
        train_ds=synthetic_corpus.train,
        val_ds=synthetic_corpus.val,
        params={"n_estimators": 10, "max_depth": 3, "random_state": 42},
    )

    manifest = RankerArtifactManifest(
        model_version="v1-test",
        model_family="XGBRanker",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        label_policy_version=LABEL_POLICY_VERSION,
        training_cutoff=synthetic_corpus.cutoff,
        corpus_fingerprint=synthetic_corpus.corpus_fingerprint,
        hyperparameters={"n_estimators": 10, "max_depth": 3},
        metrics=metrics,
        slice_metrics={},
        artifact_sha256="",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        model_file, _ = save_ranker_artifact(model, manifest, tmpdir)

        # Tamper with model file
        with open(model_file, "ab") as f:
            f.write(b"CORRUPT")

        # Loading must raise ValueError due to checksum mismatch
        with pytest.raises(ValueError, match="Artifact SHA-256 checksum mismatch"):
            load_ranker_artifact(tmpdir)
