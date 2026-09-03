"""H-B integration: behavioural history belongs only in on-demand Pair WHY."""

from __future__ import annotations

from channels import evaluate_chain_channels, evaluate_pair_channels
from history import (
    HistoricalChainState,
    HistoricalEpisode,
    HistoricalEvidenceConfig,
    HistoricalTaxonomy,
    TaxonomyTokens,
    build_historical_model,
)
from libs.contracts import load_package
from libs.provenance import ProvenanceClass


def _package():
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "current",
                "snapshot_version": "1",
                "snapshot_time": "2026-02-01T00:00:00Z",
                "status": "COMPLETE",
                "source": "test",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": "2026-02-01T00:00:00Z",
            },
            "alarms": [
                {
                    "alarm_id": "a",
                    "snapshot_id": "current",
                    "source_kind": "SYNTHETIC_TEST",
                    "provenance_class": "SYSTEM_FACT",
                    "alarm_name": "A",
                    "raw": {},
                },
                {
                    "alarm_id": "b",
                    "snapshot_id": "current",
                    "source_kind": "SYNTHETIC_TEST",
                    "provenance_class": "SYSTEM_FACT",
                    "alarm_name": "B",
                    "raw": {},
                },
            ],
            "chains": [
                {
                    "chain_id": "C",
                    "snapshot_id": "current",
                    "member_count": 2,
                    "source_kind": "SYNTHETIC_TEST",
                    "provenance_class": "SYSTEM_FACT",
                }
            ],
            "memberships": [
                {"chain_id": "C", "alarm_id": alarm_id, "snapshot_id": "current", "source_kind": "SYNTHETIC_TEST"}
                for alarm_id in ("a", "b")
            ],
        }
    )


def _model_and_taxonomy():
    taxonomy = HistoricalTaxonomy(
        "synthetic-taxonomy",
        "v1",
        {"A": TaxonomyTokens(type="A"), "B": TaxonomyTokens(type="B")},
    )
    a, b, x, y = (TaxonomyTokens(type=value) for value in "ABXY")
    episodes = (
        HistoricalEpisode(
            "e1",
            (
                HistoricalChainState("s1", "1", "2026-01-01T00:00:00Z", ((a, b),)),
                HistoricalChainState("s2", "1", "2026-01-01T00:01:00Z", ((a, b),)),
            ),
        ),
        HistoricalEpisode("e2", (HistoricalChainState("s3", "1", "2026-01-01T00:02:00Z", ((a, b),)),)),
        HistoricalEpisode("e3", (HistoricalChainState("s4", "1", "2026-01-01T00:03:00Z", ((a, b),)),)),
        HistoricalEpisode("e4", (HistoricalChainState("s5", "1", "2026-01-01T00:04:00Z", ((a, x),)),)),
        HistoricalEpisode("e5", (HistoricalChainState("s6", "1", "2026-01-01T00:05:00Z", ((b, y),)),)),
        HistoricalEpisode("e6", (HistoricalChainState("s7", "1", "2026-01-01T00:06:00Z", ((x, y),)),)),
        HistoricalEpisode("e7", (HistoricalChainState("s8", "1", "2026-01-01T00:07:00Z", ((x, y),)),)),
    )
    model = build_historical_model(
        episodes,
        training_cutoff="2026-02-01T00:00:00Z",
        lineage_prefix_fingerprint="prefix",
        taxonomy=taxonomy,
        config=HistoricalEvidenceConfig("synthetic-history", 3, 4.0, 4.0),
    )
    return model, taxonomy


def test_h_is_pair_why_only_and_uses_strict_positive_support():
    package = _package()
    model, taxonomy = _model_and_taxonomy()
    values = evaluate_pair_channels(
        package,
        "C",
        "a",
        "b",
        historical_model=model,
        historical_taxonomy=taxonomy,
        include_historical=True,
    )
    history = next(item for item in values if item.channel_id == "H")
    assert history.provenance_class is ProvenanceClass.BEHAVIORAL
    assert history.availability is True
    assert history.positive_score > 0
    assert history.threshold is None
    assert history.supports is True
    assert history.evidence_metadata == {
        "resolved_level": "TYPE",
        "support": 3,
        "marginal_a": 4,
        "marginal_b": 4,
        "episode_population": 7,
        "lift": 21 / 16,
        "strength": history.evidence_metadata["strength"],
        "reliability": history.evidence_metadata["reliability"],
        "history_model_id": model.model_version,
        "training_cutoff": "2026-02-01T00:00:00Z",
    }
    # The default chain-statistics route never calls the Pair WHY adapter.
    chain = evaluate_chain_channels(package, "C")
    assert all(
        entry.channel_id != "H"
        for pair in chain.matrix.values.values()
        for entry in pair
    )


def test_h_without_authoritative_taxonomy_is_unavailable_not_neutral():
    values = evaluate_pair_channels(_package(), "C", "a", "b", include_historical=True)
    history = next(item for item in values if item.channel_id == "H")
    assert history.availability is False
    assert history.state.value == "UNAVAILABLE"
    assert history.detail == "TAXONOMY_UNAVAILABLE"
    assert history.supports is False
