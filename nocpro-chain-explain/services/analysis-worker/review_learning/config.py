"""Fail-closed Review-Learning Configuration.

Frozen per 2026-09-11 implementation plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class ReviewLearningMode(str, Enum):
    EXPOSURE_ONLY = "EXPOSURE_ONLY"
    REVIEW_MEMORY = "REVIEW_MEMORY"
    RANKER_SHADOW = "RANKER_SHADOW"
    RANKER_ACTIVE = "RANKER_ACTIVE"


class RankerMode(str, Enum):
    DISABLED = "DISABLED"
    SHADOW = "SHADOW"
    ACTIVE = "ACTIVE"


class MutationMode(str, Enum):
    REVIEW_ONLY = "REVIEW_ONLY"
    SHADOW = "SHADOW"
    ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class PromotionThresholds:
    min_review_groups: int = 200
    min_groups_per_enabled_operation: int = 30
    min_explicit_positive_per_operation: int = 10
    min_explicit_negative_per_operation: int = 10


@dataclass(frozen=True)
class RetrievalConfig:
    enabled: bool = True
    top_k: int = 5
    min_common_blocks: int = 2


@dataclass(frozen=True)
class RankerConfig:
    mode: RankerMode = RankerMode.DISABLED
    model_family: str = "xgboost"
    feature_schema_version: str = "cf-features-v1"
    label_policy_version: str = "review-label-v1"


@dataclass(frozen=True)
class MutationConfig:
    mode: MutationMode = MutationMode.REVIEW_ONLY


@dataclass(frozen=True)
class ReviewLearningConfig:
    config_version: str
    mode: ReviewLearningMode
    retrieval: RetrievalConfig
    ranker: RankerConfig
    mutation: MutationConfig
    promotion: PromotionThresholds


def load_review_learning_config(source: str | Path | dict[str, Any]) -> ReviewLearningConfig:
    """Load and validate review learning configuration with fail-closed defaults."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"Review learning config not found at: {path}")
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    elif isinstance(source, dict):
        raw = source
    else:
        raise TypeError(f"Expected path or dict, got {type(source)}")

    if not isinstance(raw, dict):
        raise ValueError("Review learning config must be a mapping")

    config_version = str(raw.get("config_version", "v1"))
    mode = ReviewLearningMode(raw.get("mode", ReviewLearningMode.REVIEW_MEMORY.value))

    retrieval_raw = raw.get("retrieval", {})
    retrieval = RetrievalConfig(
        enabled=bool(retrieval_raw.get("enabled", True)),
        top_k=int(retrieval_raw.get("top_k", 5)),
        min_common_blocks=int(retrieval_raw.get("min_common_blocks", 2)),
    )

    ranker_raw = raw.get("ranker", {})
    ranker = RankerConfig(
        mode=RankerMode(ranker_raw.get("mode", RankerMode.DISABLED.value)),
        model_family=str(ranker_raw.get("model_family", "xgboost")),
        feature_schema_version=str(ranker_raw.get("feature_schema_version", "cf-features-v1")),
        label_policy_version=str(ranker_raw.get("label_policy_version", "review-label-v1")),
    )

    mutation_raw = raw.get("mutation", {})
    mutation = MutationConfig(
        mode=MutationMode(mutation_raw.get("mode", MutationMode.REVIEW_ONLY.value)),
    )

    promotion_raw = raw.get("promotion", {})
    promotion = PromotionThresholds(
        min_review_groups=int(promotion_raw.get("min_review_groups", 200)),
        min_groups_per_enabled_operation=int(promotion_raw.get("min_groups_per_enabled_operation", 30)),
        min_explicit_positive_per_operation=int(promotion_raw.get("min_explicit_positive_per_operation", 10)),
        min_explicit_negative_per_operation=int(promotion_raw.get("min_explicit_negative_per_operation", 10)),
    )

    return ReviewLearningConfig(
        config_version=config_version,
        mode=mode,
        retrieval=retrieval,
        ranker=ranker,
        mutation=mutation,
        promotion=promotion,
    )
