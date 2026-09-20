from pathlib import Path

from review_learning import (
    MutationMode,
    RankerMode,
    ReviewLearningMode,
    assess_data_readiness,
    load_review_learning_config,
)


def test_review_learning_defaults_are_fail_closed():
    config_path = Path(__file__).parent.parent / "config" / "review-learning" / "v1.yaml"
    config = load_review_learning_config(config_path)
    assert config.mode is ReviewLearningMode.REVIEW_MEMORY
    assert config.ranker.mode is RankerMode.DISABLED
    assert config.mutation.mode is MutationMode.REVIEW_ONLY
    assert config.promotion.min_review_groups == 200


def test_readiness_rejects_single_export_as_sequential_training_data():
    result = assess_data_readiness(
        verified_episode_count=0,
        reviewed_group_count=0,
        taxonomy_status="UNVERIFIED",
        lineage_status="UNAVAILABLE",
        operation_counts={},
    )
    assert result.ranker_status == "BLOCKED_BY_REVIEW_DATA"
    assert result.kde_status == "BLOCKED_BY_EPISODE_AND_TAXONOMY_DATA"
    assert result.mutation_status == "MUTATION_UNAVAILABLE"
    assert result.promotion_status == "BLOCKED_BY_PROMOTION_THRESHOLDS"
