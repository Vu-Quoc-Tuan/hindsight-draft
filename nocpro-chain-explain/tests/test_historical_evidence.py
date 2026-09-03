"""Exact, episode-deduplicated behavioural history (H) tests."""

from __future__ import annotations

import math

import pytest

from history import (
    HistoricalChainState,
    HistoricalEpisode,
    HistoricalEvidenceConfig,
    HistoricalTaxonomy,
    TaxonomyLevel,
    TaxonomyTokens,
    build_historical_model,
    evaluate_historical_evidence,
    evaluate_historical_oracle,
    episodes_from_lineage_prefix,
    model_from_dict,
    model_to_dict,
    taxonomy_from_dict,
    taxonomy_to_dict,
)
from temporal_delay import observations_from_lineage_prefix
from evolution import GlobalEpisodeDag, LineageConfig
from libs.contracts import IngestedAlarm, load_package


def alarm(alarm_id: str, name: str) -> IngestedAlarm:
    return IngestedAlarm(
        alarm_id=alarm_id,
        snapshot_id="current",
        raw={},
        alarm_name=name,
    )


def token(value: str, *, family: str | None = None, category: str | None = None) -> TaxonomyTokens:
    return TaxonomyTokens(type=value, family=family, category=category)


def state(snapshot: str, time: str, *chains: tuple[TaxonomyTokens, ...]) -> HistoricalChainState:
    return HistoricalChainState(snapshot, "v1", time, chains)


def episode(episode_id: str, *states: HistoricalChainState) -> HistoricalEpisode:
    return HistoricalEpisode(episode_id, states)


def config(min_support: int = 3) -> HistoricalEvidenceConfig:
    return HistoricalEvidenceConfig("history-synthetic-v1", min_support, 4.0, 4.0)


def taxonomy() -> HistoricalTaxonomy:
    return HistoricalTaxonomy(
        "synthetic-taxonomy",
        "syn-tax-v1",
        {
            "current-a": token("A", family="F-A", category="C-A"),
            "current-b": token("B", family="F-B", category="C-B"),
            "family-a": TaxonomyTokens(family="F-A", category="C-A"),
            "family-b": TaxonomyTokens(family="F-B", category="C-B"),
        },
    )


def corpus() -> tuple[HistoricalEpisode, ...]:
    """N=7, N_A=N_B=4, N_AB=3: lift=21/16 (>1)."""
    a, b, c, d, x, y = (token(value) for value in "ABCDXY")
    return (
        # Repeated states are one episode and must count AB once.
        episode(
            "E1",
            state("s1", "2026-01-01T00:00:00Z", (a, b)),
            state("s2", "2026-01-01T00:01:00Z", (a, b)),
            state("s3", "2026-01-01T00:02:00Z", (a, b)),
        ),
        episode("E2", state("s4", "2026-01-01T00:03:00Z", (a, b))),
        episode("E3", state("s5", "2026-01-01T00:04:00Z", (a, b))),
        episode("E4", state("s6", "2026-01-01T00:05:00Z", (a, c))),
        episode("E5", state("s7", "2026-01-01T00:06:00Z", (b, d))),
        episode("E6", state("s8", "2026-01-01T00:07:00Z", (x, y))),
        episode("E7", state("s9", "2026-01-01T00:08:00Z", (x, y))),
    )


def model(*, cutoff: str = "2026-01-02T00:00:00Z", min_support: int = 3):
    return build_historical_model(
        corpus(),
        training_cutoff=cutoff,
        lineage_prefix_fingerprint="lineage-prefix-syn-v1",
        taxonomy=taxonomy(),
        config=config(min_support),
    )


def _lineage_package(
    snapshot_id: str,
    snapshot_time: str,
    chains: dict[str, list[tuple[str, str]]],
):
    alarms = []
    memberships = []
    seen: set[str] = set()
    for chain_id, members in chains.items():
        for alarm_id, alarm_name in members:
            if alarm_id not in seen:
                alarms.append(
                    {
                        "alarm_id": alarm_id,
                        "snapshot_id": snapshot_id,
                        "alarm_name": alarm_name,
                        "raw": {},
                    }
                )
                seen.add(alarm_id)
            memberships.append(
                {"snapshot_id": snapshot_id, "chain_id": chain_id, "alarm_id": alarm_id}
            )
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": snapshot_id,
                "snapshot_version": "1",
                "snapshot_time": snapshot_time,
                "status": "COMPLETE",
                "source": "synthetic-h",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": snapshot_time,
                "schema_version": "v1",
            },
            "alarms": alarms,
            "chains": [
                {"snapshot_id": snapshot_id, "chain_id": chain_id, "member_count": len(members)}
                for chain_id, members in chains.items()
            ],
            "memberships": memberships,
        }
    )


def test_episode_dedup_counts_repeated_cogroup_once():
    value = evaluate_historical_evidence(alarm("a", "current-a"), alarm("b", "current-b"), model=model(), taxonomy=taxonomy())
    assert value.available is True
    assert value.resolved_level is TaxonomyLevel.TYPE
    assert value.episode_population == 7
    assert (value.marginal_a, value.marginal_b, value.support) == (4, 4, 3)
    assert value.lift == pytest.approx(21 / 16)
    assert value.supports is True
    assert value.positive_score > 0
    assert value.strength == pytest.approx(math.log(21 / 16) / math.log(4))
    assert value.reliability == pytest.approx(1 - math.exp(-3 / 4))


def test_split_branches_count_marginals_but_not_false_cogroup():
    a, b, x = token("A"), token("B"), token("X")
    episodes = (
        episode("split", state("s1", "2026-01-01T00:00:00Z", (a,), (b,))),
        episode("other", state("s2", "2026-01-01T00:01:00Z", (x,))),
    )
    frozen = build_historical_model(
        episodes,
        training_cutoff="2026-01-02T00:00:00Z",
        lineage_prefix_fingerprint="prefix",
        taxonomy=taxonomy(),
        config=config(1),
    )
    value = evaluate_historical_evidence(alarm("a", "current-a"), alarm("b", "current-b"), model=frozen, taxonomy=taxonomy())
    assert (value.marginal_a, value.marginal_b, value.support) == (1, 1, 0)
    assert value.lift == 0
    assert value.available is True
    assert value.supports is False
    assert value.positive_score == 0


def test_strict_cutoff_excludes_current_and_future_observations():
    a, b = token("A"), token("B")
    episodes = (episode("future", state("future", "2026-01-03T00:00:00Z", (a, b))),)
    frozen = build_historical_model(
        episodes,
        training_cutoff="2026-01-02T00:00:00Z",
        lineage_prefix_fingerprint="prefix",
        taxonomy=taxonomy(),
        config=config(1),
    )
    value = evaluate_historical_evidence(alarm("a", "current-a"), alarm("b", "current-b"), model=frozen, taxonomy=taxonomy())
    assert value.available is False
    assert value.reason == "HISTORY_STATISTICS_UNAVAILABLE"


@pytest.mark.parametrize("min_support", [4, 5])
def test_insufficient_support_is_available_neutral(min_support: int):
    value = evaluate_historical_evidence(alarm("a", "current-a"), alarm("b", "current-b"), model=model(min_support=min_support), taxonomy=taxonomy())
    assert value.available is True
    assert value.support == 3
    assert value.lift is not None and value.lift > 1
    assert value.positive_score == 0
    assert value.supports is False


def test_lift_not_positive_is_available_neutral():
    a, b, c = token("A"), token("B"), token("C")
    episodes = (
        episode("e1", state("s1", "2026-01-01T00:00:00Z", (a, b))),
        episode("e2", state("s2", "2026-01-01T00:01:00Z", (a, c))),
        episode("e3", state("s3", "2026-01-01T00:02:00Z", (a, b))),
    )
    frozen = build_historical_model(
        episodes,
        training_cutoff="2026-01-02T00:00:00Z",
        lineage_prefix_fingerprint="prefix",
        taxonomy=taxonomy(),
        config=config(1),
    )
    value = evaluate_historical_evidence(alarm("a", "current-a"), alarm("b", "current-b"), model=frozen, taxonomy=taxonomy())
    assert value.available is True
    assert value.lift == pytest.approx(1.0)
    assert value.positive_score == 0
    assert value.supports is False


def test_common_level_backoff_is_not_mixed_between_endpoints():
    value = evaluate_historical_evidence(alarm("a", "family-a"), alarm("b", "family-b"), model=model(), taxonomy=taxonomy())
    assert value.resolved_level is TaxonomyLevel.FAMILY
    assert value.available is False
    # The model's FAMILY corpus contains no F-A/F-B historical tokens, so it
    # must be unavailable rather than mix these with TYPE tokens.
    assert value.reason == "HISTORY_STATISTICS_UNAVAILABLE"


def test_missing_authoritative_taxonomy_is_unavailable_not_neutral():
    value = evaluate_historical_evidence(alarm("a", "current-a"), alarm("b", "current-b"), model=model(), taxonomy=None)
    assert value.available is False
    assert value.reason == "TAXONOMY_UNAVAILABLE"
    assert value.supports is False


def test_indexed_model_and_pairwise_oracle_are_equivalent():
    frozen = model()
    indexed = evaluate_historical_evidence(alarm("a", "current-a"), alarm("b", "current-b"), model=frozen, taxonomy=taxonomy())
    oracle = evaluate_historical_oracle(
        alarm("a", "current-a"),
        alarm("b", "current-b"),
        episodes=corpus(),
        training_cutoff=frozen.training_cutoff,
        taxonomy=taxonomy(),
        config=frozen.config,
    )
    assert indexed.available == oracle.available
    assert indexed.reason == oracle.reason
    assert indexed.resolved_level == oracle.resolved_level
    assert indexed.token_a == oracle.token_a
    assert indexed.token_b == oracle.token_b
    assert indexed.support == oracle.support
    assert indexed.marginal_a == oracle.marginal_a
    assert indexed.marginal_b == oracle.marginal_b
    assert indexed.episode_population == oracle.episode_population
    assert indexed.lift == pytest.approx(oracle.lift)
    assert indexed.strength == pytest.approx(oracle.strength)
    assert indexed.reliability == pytest.approx(oracle.reliability)
    assert indexed.positive_score == pytest.approx(oracle.positive_score)
    assert indexed.supports == oracle.supports


def test_frozen_model_and_taxonomy_round_trip_without_changing_pair_result():
    frozen = model()
    restored_model = model_from_dict(model_to_dict(frozen))
    restored_taxonomy = taxonomy_from_dict(taxonomy_to_dict(taxonomy()))
    original = evaluate_historical_evidence(
        alarm("a", "current-a"), alarm("b", "current-b"), model=frozen, taxonomy=taxonomy()
    )
    restored = evaluate_historical_evidence(
        alarm("a", "current-a"),
        alarm("b", "current-b"),
        model=restored_model,
        taxonomy=restored_taxonomy,
    )
    assert restored_model == frozen
    assert restored_taxonomy == taxonomy()
    assert restored == original


def test_lineage_prefix_episodes_ignore_future_merge_aliases():
    """A future merge cannot retroactively combine H training episodes."""
    first = _lineage_package(
        "s1",
        "2026-01-01T00:00:00Z",
        {"left": [("a1", "A"), ("b1", "B")], "right": [("c1", "C"), ("d1", "D")]},
    )
    second = _lineage_package(
        "s2",
        "2026-01-01T00:01:00Z",
        {"left2": [("a1", "A"), ("b1", "B")], "right2": [("c1", "C"), ("d1", "D")]},
    )
    future_merge = _lineage_package(
        "s3",
        "2026-01-01T00:02:00Z",
        {"merged": [("a1", "A"), ("b1", "B"), ("c1", "C"), ("d1", "D")]},
    )
    dag = GlobalEpisodeDag()
    lineage_config = LineageConfig(config_version="h-prefix", m_min=1)
    dag.apply_snapshot(first, previous=None, config=lineage_config)
    dag.apply_snapshot(second, previous=first, config=lineage_config)
    dag.apply_snapshot(future_merge, previous=second, config=lineage_config)

    authoritative = HistoricalTaxonomy(
        "synthetic-taxonomy",
        "prefix-v1",
        {name: TaxonomyTokens(type=name) for name in "ABCD"},
    )
    episodes, prefix = episodes_from_lineage_prefix(
        [first, second, future_merge],
        dag=dag,
        cutoff="2026-01-01T00:02:00Z",
        taxonomy=authoritative,
    )

    assert len(episodes) == 2
    assert all(len(item.states) == 2 for item in episodes)
    assert len(prefix) == 64
    assert all(
        state.snapshot_id != "s3"
        for item in episodes
        for state in item.states
    )


def test_temporal_prefix_requires_strict_order_same_chain_and_strict_cutoff():
    # Contract timestamps are immutable, so this fixture is built directly.
    payload = {"schema_version": "v1", "snapshot": {"snapshot_id": "s1", "snapshot_version": "1", "snapshot_time": "2026-01-01T00:00:00Z", "status": "COMPLETE", "source": "synthetic", "source_kind": "SYNTHETIC_TEST", "produced_at": "2026-01-01T00:00:00Z", "schema_version": "v1"}, "alarms": [{"alarm_id": "a", "snapshot_id": "s1", "alarm_name": "A", "canonical_start_time": "2026-01-01T00:00:00Z", "raw": {}}, {"alarm_id": "b", "snapshot_id": "s1", "alarm_name": "B", "canonical_start_time": "2026-01-01T00:00:05Z", "raw": {}}, {"alarm_id": "equal", "snapshot_id": "s1", "alarm_name": "C", "canonical_start_time": "2026-01-01T00:00:00Z", "raw": {}}], "chains": [{"snapshot_id": "s1", "chain_id": "chain", "member_count": 3}], "memberships": [{"snapshot_id": "s1", "chain_id": "chain", "alarm_id": value} for value in ("a", "b", "equal")]}
    first = load_package(payload)
    dag = GlobalEpisodeDag(); dag.apply_snapshot(first, previous=None, config=LineageConfig(config_version="delay", m_min=1))
    authoritative = HistoricalTaxonomy("syn", "v1", {name: TaxonomyTokens(type=name) for name in "ABC"})
    observations = observations_from_lineage_prefix([first], dag=dag, cutoff="2026-01-01T00:00:01Z", taxonomy=authoritative)
    assert [(item.key.source_token, item.key.target_token, item.delay_seconds) for item in observations] == [("A", "B", 5.0), ("C", "B", 5.0)]
    assert observations_from_lineage_prefix([first], dag=dag, cutoff="2026-01-01T00:00:00Z", taxonomy=authoritative) == ()


def test_temporal_prefix_dedups_repeated_event_pair_but_keeps_presplit_cogroup():
    def package(snapshot_id: str, snapshot_time: str, chains: dict[str, list[str]]):
        return load_package({
            "schema_version": "v1",
            "snapshot": {"snapshot_id": snapshot_id, "snapshot_version": "1", "snapshot_time": snapshot_time, "status": "COMPLETE", "source": "synthetic", "source_kind": "SYNTHETIC_TEST", "produced_at": snapshot_time, "schema_version": "v1"},
            "alarms": [
                {"alarm_id": alarm_id, "snapshot_id": snapshot_id, "alarm_name": "A" if alarm_id == "a" else "B", "canonical_start_time": "2026-01-01T00:00:00Z" if alarm_id == "a" else "2026-01-01T00:00:05Z", "raw": {}}
                for alarm_id in sorted({item for members in chains.values() for item in members})
            ],
            "chains": [{"snapshot_id": snapshot_id, "chain_id": chain_id, "member_count": len(members)} for chain_id, members in chains.items()],
            "memberships": [{"snapshot_id": snapshot_id, "chain_id": chain_id, "alarm_id": alarm_id} for chain_id, members in chains.items() for alarm_id in members],
        })
    s1 = package("s1", "2026-01-01T00:00:00Z", {"C": ["a", "b"]})
    s2 = package("s2", "2026-01-01T00:01:00Z", {"C2": ["a", "b"]})
    s3 = package("s3", "2026-01-01T00:02:00Z", {"L": ["a"], "R": ["b"]})
    dag = GlobalEpisodeDag(); config = LineageConfig(config_version="delay-prefix", m_min=1)
    dag.apply_snapshot(s1, previous=None, config=config)
    dag.apply_snapshot(s2, previous=s1, config=config)
    dag.apply_snapshot(s3, previous=s2, config=config)
    taxonomy = HistoricalTaxonomy("syn", "v1", {"A": TaxonomyTokens(type="A"), "B": TaxonomyTokens(type="B")})
    observations = observations_from_lineage_prefix([s1, s2, s3], dag=dag, cutoff="2026-01-01T00:03:00Z", taxonomy=taxonomy)
    directed = [item for item in observations if item.key.level is TaxonomyLevel.TYPE]
    assert len(directed) == 1
    assert (directed[0].key.source_token, directed[0].key.target_token, directed[0].delay_seconds) == ("A", "B", 5.0)


def test_temporal_prefix_split_branches_without_cogroup_do_not_create_observation():
    left = _lineage_package("left", "2026-01-01T00:00:00Z", {"L": [("a", "A")]})
    right = _lineage_package("right", "2026-01-01T00:01:00Z", {"R": [("b", "B")]})
    dag = GlobalEpisodeDag(); config = LineageConfig(config_version="delay-branches", m_min=1)
    dag.apply_snapshot(left, previous=None, config=config)
    dag.apply_snapshot(right, previous=left, config=config)
    taxonomy = HistoricalTaxonomy("syn", "v1", {"A": TaxonomyTokens(type="A"), "B": TaxonomyTokens(type="B")})
    assert observations_from_lineage_prefix([left, right], dag=dag, cutoff="2026-01-01T00:02:00Z", taxonomy=taxonomy) == ()
