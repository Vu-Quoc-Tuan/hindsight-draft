"""Versioned data readiness assessment for Review-Learning.

Never collapses independent gates into a single boolean (ADR-0028, fail-closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import PromotionThresholds, ReviewLearningConfig


@dataclass(frozen=True)
class DataReadiness:
    """Independent readiness statuses across data planes."""

    taxonomy_status: str
    lineage_status: str
    exposure_status: str
    feedback_status: str
    retrieval_status: str
    kde_status: str
    ranker_status: str
    promotion_status: str
    mutation_status: str
    details: dict[str, Any] = field(default_factory=dict)


def assess_data_readiness(
    *,
    verified_episode_count: int,
    reviewed_group_count: int,
    taxonomy_status: str,
    lineage_status: str,
    operation_counts: dict[str, int] | None = None,
    explicit_positive_counts: dict[str, int] | None = None,
    explicit_negative_counts: dict[str, int] | None = None,
    config: ReviewLearningConfig | None = None,
    exposure_count: int = 0,
    has_upstream_mutation_contract: bool = False,
) -> DataReadiness:
    """Assess readiness independently across review memory, KDE, ranker, and mutation planes."""
    op_counts = operation_counts or {}
    pos_counts = explicit_positive_counts or {}
    neg_counts = explicit_negative_counts or {}
    thresholds = config.promotion if config else PromotionThresholds()

    # Taxonomy & Lineage
    tax_ready = taxonomy_status.upper() in {"VERIFIED", "READY", "PASS"}
    lineage_ready = lineage_status.upper() in {"VERIFIED", "READY", "PASS"}

    # Exposure status
    if exposure_count > 0:
        exp_status = "READY"
    else:
        exp_status = "EMPTY"

    # Feedback status
    if reviewed_group_count >= thresholds.min_review_groups:
        feed_status = "READY"
    elif reviewed_group_count > 0:
        feed_status = "PARTIAL"
    else:
        feed_status = "NO_FEEDBACK"

    # Retrieval status (Case Store)
    if reviewed_group_count >= 1:
        retrieval_status = "READY"
    else:
        retrieval_status = "EMPTY"

    # KDE status: requires verified episodes AND valid taxonomy
    if verified_episode_count < 10 or not tax_ready:
        kde_status = "BLOCKED_BY_EPISODE_AND_TAXONOMY_DATA"
    else:
        kde_status = "READY"

    # Ranker training status
    supported_ops = {"REMOVE_MEMBER", "SPLIT_CHAIN", "MOVE_MEMBER", "MERGE_CHAINS"}
    covered_ops = {op for op in supported_ops if op_counts.get(op, 0) > 0}

    if reviewed_group_count < 5:
        ranker_status = "BLOCKED_BY_REVIEW_DATA"
    elif not covered_ops:
        ranker_status = "BLOCKED_BY_OPERATION_COVERAGE"
    else:
        ranker_status = "READY_FOR_OFFLINE_EXPERIMENT"

    # Promotion status
    promotion_reasons = []
    if reviewed_group_count < thresholds.min_review_groups:
        promotion_reasons.append(
            f"INSUFFICIENT_REVIEW_GROUPS: {reviewed_group_count} < {thresholds.min_review_groups}"
        )

    for op in supported_ops:
        c = op_counts.get(op, 0)
        if c < thresholds.min_groups_per_enabled_operation:
            promotion_reasons.append(f"INSUFFICIENT_GROUPS_FOR_{op}: {c} < {thresholds.min_groups_per_enabled_operation}")
        pos = pos_counts.get(op, 0)
        if pos < thresholds.min_explicit_positive_per_operation:
            promotion_reasons.append(f"INSUFFICIENT_POS_FOR_{op}: {pos} < {thresholds.min_explicit_positive_per_operation}")
        neg = neg_counts.get(op, 0)
        if neg < thresholds.min_explicit_negative_per_operation:
            promotion_reasons.append(f"INSUFFICIENT_NEG_FOR_{op}: {neg} < {thresholds.min_explicit_negative_per_operation}")

    if not promotion_reasons:
        promotion_status = "PROMOTION_ELIGIBLE"
    else:
        promotion_status = "BLOCKED_BY_PROMOTION_THRESHOLDS"

    # Mutation status: fail-closed
    if not has_upstream_mutation_contract:
        mutation_status = "MUTATION_UNAVAILABLE"
    else:
        mutation_status = "SHADOW_ONLY"

    details = {
        "verified_episode_count": verified_episode_count,
        "reviewed_group_count": reviewed_group_count,
        "exposure_count": exposure_count,
        "operation_counts": op_counts,
        "explicit_positive_counts": pos_counts,
        "explicit_negative_counts": neg_counts,
        "promotion_blockers": promotion_reasons,
    }

    return DataReadiness(
        taxonomy_status=taxonomy_status,
        lineage_status=lineage_status,
        exposure_status=exp_status,
        feedback_status=feed_status,
        retrieval_status=retrieval_status,
        kde_status=kde_status,
        ranker_status=ranker_status,
        promotion_status=promotion_status,
        mutation_status=mutation_status,
        details=details,
    )
