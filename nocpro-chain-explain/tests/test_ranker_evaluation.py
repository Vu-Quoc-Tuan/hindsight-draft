"""Tests for ranker evaluation, slice metrics, and regret computation."""

from __future__ import annotations

import pytest

from review_learning import (
    GroupedRankingDataset,
    dcg_at_k,
    evaluate_deterministic_baseline,
    evaluate_predictions,
    generate_synthetic_review_corpus,
    materialize_training_corpus,
    ndcg_at_k,
)
from scripts.review_learning.train_ranker import evaluate_operation_slices


def test_dcg_and_ndcg_at_k():
    """Verify standard IR metric calculations."""
    # Ideal ranking: [3, 2, 0]
    # At k=1: dcg = (2^3 - 1)/log2(2) = 7/1 = 7.0
    # At k=3: dcg = 7.0 + (2^2 - 1)/log2(3) = 7.0 + 3/1.58496 = 8.89278
    assert dcg_at_k([3, 2, 0], 1) == 7.0
    assert abs(dcg_at_k([3, 2, 0], 3) - 8.89278) < 1e-4

    # Perfect prediction gives NDCG=1.0
    assert ndcg_at_k([3, 2, 0], [10.0, 5.0, 1.0], 3) == 1.0

    # Inverted prediction gives NDCG < 1.0
    inverted_ndcg = ndcg_at_k([3, 2, 0], [1.0, 5.0, 10.0], 3)
    assert inverted_ndcg < 1.0
    assert inverted_ndcg > 0.0

    # Empty group returns 0.0
    assert ndcg_at_k([], [], 3) == 0.0


def test_candidate_regret_computation():
    """Verify regret calculation (y_max - y_pred_top1)."""
    # Group with y=[3, 1, 0]
    # Predictor ranks candidate 0 first: regret = 3 - 3 = 0.0
    ds_perfect = GroupedRankingDataset(
        qids=["q1", "q1", "q1"],
        X=[[0.0] * 43, [0.0] * 43, [0.0] * 43],
        y=[3, 1, 0],
        group_sizes=[3],
        group_weights=[1.0],
        candidate_ids=["c1", "c2", "c3"],
        review_ids=["q1"],
    )
    metrics_perfect = evaluate_predictions(ds_perfect, [10.0, 5.0, 1.0])
    assert metrics_perfect.mean_regret == 0.0

    # Predictor ranks candidate 2 (y=0) first: regret = 3 - 0 = 3.0
    metrics_suboptimal = evaluate_predictions(ds_perfect, [1.0, 5.0, 10.0])
    assert metrics_suboptimal.mean_regret == 3.0


def test_operation_slice_evaluation():
    """Verify slice evaluation computes correct metrics per candidate operation."""
    sessions, exposures, feedbacks = generate_synthetic_review_corpus(group_count=20)
    corpus = materialize_training_corpus(
        sessions=sessions,
        exposures=exposures,
        feedbacks=feedbacks,
        cutoff="2026-09-10T00:00:00Z",
    )

    dummy_scores = [float(-i) for i in range(corpus.train.num_candidates)]
    slices = evaluate_operation_slices(corpus.train, dummy_scores)

    assert "REMOVE_MEMBER" in slices
    assert "SPLIT_CHAIN" in slices
    assert "MOVE_MEMBER" in slices
    assert "MERGE_CHAINS" in slices

    for op, data in slices.items():
        if data.get("status") != "NO_DATA":
            assert data["num_groups"] > 0
            assert "ndcg_3" in data
            assert "mean_regret" in data
            assert "baseline_ndcg_3" in data
