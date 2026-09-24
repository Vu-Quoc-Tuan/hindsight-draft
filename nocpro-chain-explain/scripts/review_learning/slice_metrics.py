"""Canonical slice metrics shared by ranker training and evaluation CLIs."""

from __future__ import annotations

from typing import Any

from review_learning import GroupedRankingDataset, evaluate_deterministic_baseline, evaluate_predictions


def evaluate_slice_subset(
    dataset: GroupedRankingDataset,
    scores: list[float],
    matched_group_indices: list[int],
    abstention_threshold: float = 0.0,
) -> dict[str, Any]:
    """Helper to evaluate ranking metrics on a subset of groups."""
    if not matched_group_indices:
        return {"num_groups": 0, "status": "NO_DATA"}
    matched = set(matched_group_indices)

    sub_X: list[list[float]] = []
    sub_y: list[int] = []
    sub_qids: list[str] = []
    sub_cand_ids: list[str] = []
    sub_sizes: list[int] = []
    sub_weights: list[float] = []
    sub_rids: list[str] = []
    sub_scores: list[float] = []

    cur = 0
    for g_i, size in enumerate(dataset.group_sizes):
        if g_i in matched:
            sub_X.extend(dataset.X[cur : cur + size])
            sub_y.extend(dataset.y[cur : cur + size])
            sub_qids.extend(dataset.qids[cur : cur + size])
            sub_cand_ids.extend(dataset.candidate_ids[cur : cur + size])
            sub_scores.extend(scores[cur : cur + size])
            sub_sizes.append(size)
            sub_weights.append(dataset.group_weights[g_i])
            sub_rids.append(dataset.review_ids[g_i])
        cur += size

    sub_ds = GroupedRankingDataset(
        qids=sub_qids,
        X=sub_X,
        y=sub_y,
        group_sizes=sub_sizes,
        group_weights=sub_weights,
        candidate_ids=sub_cand_ids,
        review_ids=sub_rids,
    )

    sub_metrics = evaluate_predictions(sub_ds, sub_scores, abstention_threshold=abstention_threshold)
    sub_baseline = evaluate_deterministic_baseline(sub_ds)

    return {
        "num_groups": len(sub_sizes),
        "ndcg_1": round(sub_metrics.ndcg_1, 4),
        "ndcg_3": round(sub_metrics.ndcg_3, 4),
        "ndcg_5": round(sub_metrics.ndcg_5, 4),
        "mean_regret": round(sub_metrics.mean_regret, 4),
        "baseline_ndcg_3": round(sub_baseline.ndcg_3, 4),
        "ndcg_improvement": round(sub_metrics.ndcg_3 - sub_baseline.ndcg_3, 4),
        "abstention_rate": round(sub_metrics.abstention_rate, 4),
    }


def evaluate_all_slices(
    dataset: GroupedRankingDataset,
    scores: list[float],
    abstention_threshold: float = 0.0,
) -> dict[str, Any]:
    """Compute slice metrics across operations, source kinds, and truth tiers."""
    results: dict[str, Any] = {
        "operations": {},
        "source_kinds": {},
        "truth_tiers": {},
    }

    # 1. Operation slices (partitioned by operation of the best/approved candidate)
    ops = ["REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER", "MERGE_CHAINS"]
    op_groups: dict[str, list[int]] = {op: [] for op in ops}

    cur = 0
    for g_i, size in enumerate(dataset.group_sizes):
        group_X = dataset.X[cur : cur + size]
        group_y = dataset.y[cur : cur + size]
        cur += size
        if not group_y:
            continue
        max_rel = max(group_y)
        best_idx = group_y.index(max_rel)
        best_row = group_X[best_idx]
        for op_idx, op_name in enumerate(ops):
            if len(best_row) > op_idx and best_row[op_idx] == 1.0:
                op_groups[op_name].append(g_i)
                break

    for op_name in ops:
        results["operations"][op_name] = evaluate_slice_subset(dataset, scores, op_groups[op_name], abstention_threshold=abstention_threshold)

    # 2. Source kinds
    distinct_sources = set(dataset.source_kinds)
    for sk in distinct_sources:
        if not sk:
            continue
        matched_idx = [i for i, s in enumerate(dataset.source_kinds) if s == sk]
        results["source_kinds"][sk] = evaluate_slice_subset(dataset, scores, matched_idx, abstention_threshold=abstention_threshold)

    # 3. Truth tiers
    distinct_tiers: set[str] = set()
    for t_list in dataset.group_truth_tiers:
        distinct_tiers.update(t_list)
    for tier in distinct_tiers:
        if not tier:
            continue
        matched_idx = [
            i for i, t_list in enumerate(dataset.group_truth_tiers) if tier in t_list
        ]
        results["truth_tiers"][tier] = evaluate_slice_subset(dataset, scores, matched_idx, abstention_threshold=abstention_threshold)
    return results


def evaluate_operation_slices(
    dataset: GroupedRankingDataset,
    scores: list[float],
    abstention_threshold: float = 0.0,
) -> dict[str, Any]:
    """Compute slice metrics across candidate operations."""
    return evaluate_all_slices(dataset, scores, abstention_threshold=abstention_threshold)["operations"]
