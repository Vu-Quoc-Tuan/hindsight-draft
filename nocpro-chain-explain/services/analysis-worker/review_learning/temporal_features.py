"""KDE V2 temporal delay feature extraction for counterfactual candidate review.

Integrates directly with the existing FrozenDelayModel without model retraining,
computing before/after/delta pairs on affected chains.
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Any, Mapping, Sequence

from temporal_delay.model import (
    DelayLookup,
    FrozenDelayModel,
    TaxonomyLevel,
    evaluate_ordered_delay_model,
)


def _eval_pairs(
    alarm_pairs: Sequence[tuple[str, str]],
    alarms_by_id: Mapping[str, Any],
    delay_model: FrozenDelayModel,
    taxonomy: Any,
) -> dict[str, Any]:
    if not alarm_pairs:
        return {
            "pairs_total": 0,
            "pairs_available": 0,
            "coverage_ratio": 0.0,
            "mean_positive_score": 0.0,
            "min_positive_score": 0.0,
            "max_positive_score": 0.0,
            "backoff_level_counts": {},
            "unavailable_reasons": {},
        }

    total = len(alarm_pairs)
    available_scores: list[float] = []
    backoffs: dict[str, int] = {}
    reasons: dict[str, int] = {}

    for left_id, right_id in alarm_pairs:
        left_alarm = alarms_by_id.get(left_id)
        right_alarm = alarms_by_id.get(right_id)
        if left_alarm is None or right_alarm is None:
            continue

        left_name = getattr(left_alarm, "alarm_name", "") or ""
        right_name = getattr(right_alarm, "alarm_name", "") or ""

        left_tok = None
        right_tok = None
        if taxonomy is not None:
            if hasattr(taxonomy, "resolve"):
                left_tok = taxonomy.resolve(left_alarm)
                right_tok = taxonomy.resolve(right_alarm)
            elif hasattr(taxonomy, "tokens_by_alarm_name"):
                left_tok = taxonomy.tokens_by_alarm_name.get(left_name)
                right_tok = taxonomy.tokens_by_alarm_name.get(right_name)
            elif hasattr(taxonomy, "tokens_for"):
                left_tok = taxonomy.tokens_for(left_name)
                right_tok = taxonomy.tokens_for(right_name)

        left_start = getattr(left_alarm, "start_time", None) or getattr(left_alarm, "canonical_start_time", None) or ""
        right_start = getattr(right_alarm, "start_time", None) or getattr(right_alarm, "canonical_start_time", None) or ""

        lookup: DelayLookup = evaluate_ordered_delay_model(
            left_tok,
            right_tok,
            left_start=str(left_start),
            right_start=str(right_start),
            model=delay_model,
        )

        if lookup.available:
            available_scores.append(lookup.positive_score)
            if lookup.resolved_level:
                lvl = lookup.resolved_level.value if isinstance(lookup.resolved_level, TaxonomyLevel) else str(lookup.resolved_level)
                backoffs[lvl] = backoffs.get(lvl, 0) + 1
        else:
            r = lookup.reason or "UNKNOWN"
            reasons[r] = reasons.get(r, 0) + 1

    avail_count = len(available_scores)
    cov = avail_count / total if total > 0 else 0.0
    mean_sc = sum(available_scores) / avail_count if avail_count > 0 else 0.0
    min_sc = min(available_scores) if avail_count > 0 else 0.0
    max_sc = max(available_scores) if avail_count > 0 else 0.0

    return {
        "pairs_total": total,
        "pairs_available": avail_count,
        "coverage_ratio": round(cov, 4),
        "mean_positive_score": round(mean_sc, 4),
        "min_positive_score": round(min_sc, 4),
        "max_positive_score": round(max_sc, 4),
        "backoff_level_counts": backoffs,
        "unavailable_reasons": reasons,
    }


def sample_chain_pairs(chain_list: Sequence[str], max_pairs: int, seed: int) -> tuple[list[tuple[str, str]], int]:
    """Sample pairs from a chain without materializing the full N*(N-1)/2 Cartesian product."""
    N = len(chain_list)
    if N < 2:
        return [], 0
    total_pairs = N * (N - 1) // 2
    if total_pairs <= max_pairs:
        pairs = []
        for i in range(N):
            for j in range(i + 1, N):
                pairs.append((chain_list[i], chain_list[j]))
        return pairs, total_pairs

    rng = random.Random(seed)
    sampled_indices: set[int] = set()
    while len(sampled_indices) < max_pairs:
        sampled_indices.add(rng.randint(0, total_pairs - 1))

    pairs = []
    for k in sorted(sampled_indices):
        # Invert flat index k to (i, j) with 0 <= i < j < N
        discriminant = (2 * N - 1) ** 2 - 8 * k
        i = int((2 * N - 1 - math.isqrt(discriminant)) // 2)
        row_start = i * N - (i * (i + 1)) // 2
        j = k - row_start + i + 1
        pairs.append((chain_list[i], chain_list[j]))
    return pairs, total_pairs


def sample_bipartite_pairs(
    list_a: Sequence[str], list_b: Sequence[str], max_pairs: int, seed: int
) -> tuple[list[tuple[str, str]], int]:
    """Sample cross pairs between two disjoint sets without materializing full N1*N2 product."""
    N1 = len(list_a)
    N2 = len(list_b)
    total_pairs = N1 * N2
    if total_pairs == 0:
        return [], 0
    if total_pairs <= max_pairs:
        return [(a, b) for a in list_a for b in list_b], total_pairs

    rng = random.Random(seed)
    sampled_indices: set[int] = set()
    while len(sampled_indices) < max_pairs:
        sampled_indices.add(rng.randint(0, total_pairs - 1))

    pairs = []
    for k in sorted(sampled_indices):
        i = k // N2
        j = k % N2
        pairs.append((list_a[i], list_b[j]))
    return pairs, total_pairs


def summarize_candidate_delay_features(
    *,
    candidate: Mapping[str, Any],
    chain_alarm_ids: Sequence[str],
    alarms_by_id: Mapping[str, Any],
    delay_model: FrozenDelayModel | None,
    taxonomy: Any | None,
    target_chain_alarm_ids: Sequence[str] | None = None,
    max_evaluated_pairs: int = 500,
) -> dict[str, Any]:
    """Compute temporal delay shape before/after/delta for a counterfactual candidate.

    Applies memory-bounded deterministic pair sampling via flat-index inversion without
    materializing the full Cartesian product in memory.
    """
    if delay_model is None or taxonomy is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "NO_DELAY_MODEL_CONFIGURED" if delay_model is None else "NO_TAXONOMY_CONFIGURED",
            "delay_model_version": getattr(delay_model, "model_version", None),
            "before": None,
            "after": None,
            "delta": None,
        }

    cid = str(candidate.get("candidate_id", "default_cid"))
    seed = int(hashlib.md5(cid.encode("utf-8")).hexdigest()[:8], 16)
    chain_list = list(chain_alarm_ids)

    # Sample before pairs directly
    evaluated_before_pairs, total_before_pairs = sample_chain_pairs(
        chain_list, max_evaluated_pairs, seed
    )
    before_summary = _eval_pairs(evaluated_before_pairs, alarms_by_id, delay_model, taxonomy)
    before_summary["pairs_total"] = total_before_pairs
    before_summary["pairs_evaluated"] = len(evaluated_before_pairs)
    before_summary["sampling_status"] = "SAMPLED" if total_before_pairs > max_evaluated_pairs else "EXACT"

    op = candidate.get("operation", "UNKNOWN")
    delta_dict = candidate.get("partition_delta") or {}

    evaluated_after_pairs: list[tuple[str, str]] = []
    total_after_pairs = 0
    separated_pairs: list[tuple[str, str]] = []
    added_cross_pairs: list[tuple[str, str]] = []

    op_clean = str(op).upper()
    if op_clean in {"REMOVE", "REMOVE_MEMBER"}:
        removed_ids = set(
            delta_dict.get("removed_alarms")
            or delta_dict.get("removed_members")
            or delta_dict.get("alarms")
            or []
        )
        retained = [aid for aid in chain_list if aid not in removed_ids]
        evaluated_after_pairs, total_after_pairs = sample_chain_pairs(
            retained, max_evaluated_pairs, seed + 1
        )
        separated_pairs, _ = sample_bipartite_pairs(
            retained, list(removed_ids), max_evaluated_pairs, seed + 2
        )

    elif op_clean in {"SPLIT", "SPLIT_CHAIN"}:
        partitions = delta_dict.get("partitions") or delta_dict.get("split_partitions") or []
        if isinstance(partitions, list) and len(partitions) >= 2:
            # Intra-partition pairs
            intra_pairs: list[tuple[str, str]] = []
            sum_total_after = 0
            for p_idx, part in enumerate(partitions):
                p_list = list(part)
                part_pairs, p_total = sample_chain_pairs(
                    p_list, max_evaluated_pairs // len(partitions), seed + p_idx + 1
                )
                intra_pairs.extend(part_pairs)
                sum_total_after += p_total
            evaluated_after_pairs = intra_pairs[:max_evaluated_pairs]
            total_after_pairs = sum_total_after

            # Inter-partition (separated) pairs
            for p1_idx in range(len(partitions)):
                for p2_idx in range(p1_idx + 1, len(partitions)):
                    p_cut, _ = sample_bipartite_pairs(
                        list(partitions[p1_idx]), list(partitions[p2_idx]),
                        max_evaluated_pairs // (len(partitions) ** 2), seed + p1_idx * 10 + p2_idx
                    )
                    separated_pairs.extend(p_cut)
            separated_pairs = separated_pairs[:max_evaluated_pairs]
        else:
            evaluated_after_pairs = evaluated_before_pairs
            total_after_pairs = total_before_pairs

    elif op_clean in {"MOVE", "MOVE_MEMBER"}:
        moved_ids = set(
            delta_dict.get("moved_alarms")
            or delta_dict.get("moved_members")
            or delta_dict.get("alarms")
            or []
        )
        retained = [aid for aid in chain_list if aid not in moved_ids]
        retained_pairs, total_retained = sample_chain_pairs(
            retained, max_evaluated_pairs // 2, seed + 1
        )
        separated_pairs, _ = sample_bipartite_pairs(
            retained, list(moved_ids), max_evaluated_pairs, seed + 2
        )
        target_ids = list(target_chain_alarm_ids or delta_dict.get("target_chain_alarms") or [])
        added_cross_pairs, total_added = sample_bipartite_pairs(
            list(moved_ids), target_ids, max_evaluated_pairs // 2, seed + 3
        )
        evaluated_after_pairs = (retained_pairs + added_cross_pairs)[:max_evaluated_pairs]
        total_after_pairs = total_retained + total_added

    elif op_clean in {"MERGE", "MERGE_CHAINS"}:
        target_ids = list(target_chain_alarm_ids or delta_dict.get("target_chain_alarms") or delta_dict.get("merged_alarms") or [])
        added_cross_pairs, total_added = sample_bipartite_pairs(
            chain_list, target_ids, max_evaluated_pairs, seed + 1
        )
        evaluated_after_pairs = added_cross_pairs
        total_after_pairs = total_before_pairs + total_added

    else:
        evaluated_after_pairs = evaluated_before_pairs
        total_after_pairs = total_before_pairs

    after_summary = _eval_pairs(evaluated_after_pairs, alarms_by_id, delay_model, taxonomy)
    after_summary["sampling_status"] = "SAMPLED" if total_after_pairs > max_evaluated_pairs else "EXACT"
    after_summary["truncated"] = total_after_pairs > max_evaluated_pairs
    after_summary["pairs_total"] = total_after_pairs
    after_summary["pairs_evaluated"] = len(evaluated_after_pairs)

    separated_summary = _eval_pairs(separated_pairs, alarms_by_id, delay_model, taxonomy)

    delta_mean_score = round(
        after_summary["mean_positive_score"] - before_summary["mean_positive_score"], 4
    )
    delta_coverage = round(
        after_summary["coverage_ratio"] - before_summary["coverage_ratio"], 4
    )

    return {
        "status": "AVAILABLE",
        "reason": None,
        "delay_model_version": delay_model.model_version,
        "implementation_version": getattr(delay_model, "implementation_version", "TEMPORAL_DELAY_MODEL_V2"),
        "before": before_summary,
        "after": after_summary,
        "separated": separated_summary,
        "delta": {
            "delta_mean_positive_score": delta_mean_score,
            "delta_coverage_ratio": delta_coverage,
            "separated_pairs_count": len(separated_pairs),
            "separated_mean_score": separated_summary["mean_positive_score"],
            "added_cross_pairs_count": len(added_cross_pairs),
        },
    }
