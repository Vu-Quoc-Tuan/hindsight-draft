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
)
from libs.contracts import IngestedAlarm


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
