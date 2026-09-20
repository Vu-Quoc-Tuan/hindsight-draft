from __future__ import annotations

from dataclasses import dataclass
from review_learning.temporal_features import summarize_candidate_delay_features
from temporal_delay import (
    DelayEstimator,
    DelayModelConfig,
    DelayObservation,
    DelayRelationKey,
    build_delay_model,
)
from history import HistoricalTaxonomy, TaxonomyLevel


@dataclass(frozen=True)
class DummyAlarm:
    alarm_id: str
    alarm_name: str
    start_time: str


def _model_config():
    return DelayModelConfig(
        "delay-test-v1",
        2,
        4,
        0.4,
        42,
        (2.0, 5.0),
        (2.0, 5.0),
        (1.0, 3.0),
        DelayEstimator.HISTOGRAM,
        5.0,
        fallback_histogram_bin_width_seconds=5.0,
    )


def test_summarize_candidate_delay_features_without_model():
    cand = {"operation": "REMOVE", "partition_delta": {"removed_alarms": ["a2"]}}
    res = summarize_candidate_delay_features(
        candidate=cand,
        chain_alarm_ids=["a1", "a2"],
        alarms_by_id={},
        delay_model=None,
        taxonomy=None,
    )
    assert res["status"] == "UNAVAILABLE"
    assert res["reason"] == "NO_DELAY_MODEL_CONFIGURED"


def test_summarize_candidate_delay_features_with_fitted_model():
    from history import TaxonomyTokens

    tokens1 = TaxonomyTokens("POWER_LOSS", "OPTICAL", "PHYSICAL")
    tokens2 = TaxonomyTokens("SESSION_DOWN", "BGP", "ROUTING")
    taxonomy = HistoricalTaxonomy(
        source_id="tax_test",
        source_version="v1",
        tokens_by_alarm_name={
            "Optical Power Degradation": tokens1,
            "BGP Session Down": tokens2,
        },
    )

    key = DelayRelationKey(TaxonomyLevel.TYPE, "POWER_LOSS", "SESSION_DOWN")
    observations = [
        DelayObservation(
            episode_id=f"ep_{i}",
            source_alarm_id=f"s_{i}",
            target_alarm_id=f"t_{i}",
            key=key,
            delay_seconds=45.0,
        )
        for i in range(10)
    ]

    model = build_delay_model(
        observations=observations,
        training_cutoff="2026-01-01T00:00:00Z",
        lineage_prefix_fingerprint="test_lineage",
        taxonomy_source_id="tax_test",
        taxonomy_source_version="v1",
        config=_model_config(),
    )

    alarms = {
        "a1": DummyAlarm(alarm_id="a1", alarm_name="Optical Power Degradation", start_time="2026-09-11T08:00:00Z"),
        "a2": DummyAlarm(alarm_id="a2", alarm_name="BGP Session Down", start_time="2026-09-11T08:00:45Z"),
    }

    # Test REMOVE candidate
    cand_remove = {"operation": "REMOVE", "partition_delta": {"removed_alarms": ["a2"]}}
    res = summarize_candidate_delay_features(
        candidate=cand_remove,
        chain_alarm_ids=["a1", "a2"],
        alarms_by_id=alarms,
        delay_model=model,
        taxonomy=taxonomy,
    )

    assert res["status"] == "AVAILABLE"
    assert res["delay_model_version"] == model.model_version
    assert res["before"]["pairs_total"] == 1
    assert res["before"]["pairs_available"] == 1
    assert res["before"]["coverage_ratio"] == 1.0
    assert res["before"]["mean_positive_score"] > 0.0

    # After removing a2, no pairs remain in chain
    assert res["after"]["pairs_total"] == 0
    assert res["separated"]["pairs_total"] == 1
    assert res["delta"]["separated_pairs_count"] == 1
