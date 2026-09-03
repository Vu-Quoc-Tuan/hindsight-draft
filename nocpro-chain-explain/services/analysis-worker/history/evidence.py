"""Episode-deduplicated, immutable behavioural evidence ``H``.

This module deliberately does not consume NocPro ``HistorySimilarity``.  It
builds statistics from historical chain membership under a strict temporal
cutoff, then answers pair queries with exact count lookups.  The production
adapter/persistence wiring is intentionally separate from this core model.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Mapping

from libs.contracts import IngestedAlarm


HISTORICAL_CHANNEL = "H"
HISTORICAL_DERIVATION = "grouping_history"


class TaxonomyLevel(str, Enum):
    TYPE = "TYPE"
    FAMILY = "FAMILY"
    CATEGORY = "CATEGORY"


_LEVELS = (
    TaxonomyLevel.TYPE,
    TaxonomyLevel.FAMILY,
    TaxonomyLevel.CATEGORY,
)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class TaxonomyTokens:
    """Authoritative tokens for one alarm identity in a taxonomy source."""

    type: str | None = None
    family: str | None = None
    category: str | None = None

    def at(self, level: TaxonomyLevel) -> str | None:
        value = {
            TaxonomyLevel.TYPE: self.type,
            TaxonomyLevel.FAMILY: self.family,
            TaxonomyLevel.CATEGORY: self.category,
        }[level]
        return value.strip() if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class HistoricalTaxonomy:
    """External/versioned taxonomy, keyed by canonical alarm name.

    Looking up an alarm name is only a join key into an authoritative mapping;
    no token is inferred from free text.  A missing mapping is therefore a real
    lack of taxonomy capability.
    """

    source_id: str
    source_version: str
    tokens_by_alarm_name: Mapping[str, TaxonomyTokens]

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_version.strip():
            raise ValueError("historical taxonomy source_id and source_version are required")

    def resolve(self, alarm: IngestedAlarm) -> TaxonomyTokens | None:
        name = (alarm.alarm_name or "").strip()
        return self.tokens_by_alarm_name.get(name) if name else None


@dataclass(frozen=True)
class HistoricalEvidenceConfig:
    """All numeric H parameters are explicit and versioned."""

    config_version: str
    min_support: int
    lambda_h: float
    lift_cap: float

    def __post_init__(self) -> None:
        if not self.config_version.strip():
            raise ValueError("history config_version is required")
        if self.min_support < 1:
            raise ValueError("history min_support must be >= 1")
        if self.lambda_h <= 0:
            raise ValueError("history lambda_h must be > 0")
        if self.lift_cap <= 1:
            raise ValueError("history lift_cap must be > 1")


@dataclass(frozen=True)
class HistoricalChainState:
    """One historical chain state, with tokens already authoritatively resolved."""

    snapshot_id: str
    snapshot_version: str
    snapshot_time: str
    chains: tuple[tuple[TaxonomyTokens, ...], ...]

    def __post_init__(self) -> None:
        _parse_time(self.snapshot_time)


@dataclass(frozen=True)
class HistoricalEpisode:
    """One weakly-connected lineage component in the prefix under analysis."""

    episode_id: str
    states: tuple[HistoricalChainState, ...]

    def __post_init__(self) -> None:
        if not self.episode_id.strip():
            raise ValueError("historical episode_id is required")


@dataclass(frozen=True)
class LevelStatistics:
    episode_population_count: int
    marginal_count: Mapping[str, int]
    co_group_episode_count: Mapping[tuple[str, str], int]


@dataclass(frozen=True)
class HistoricalEvidenceModel:
    """Frozen statistics/index used for exactly one temporal cutoff."""

    model_version: str
    training_cutoff: str
    corpus_fingerprint: str
    lineage_prefix_fingerprint: str
    taxonomy_source_id: str
    taxonomy_source_version: str
    config: HistoricalEvidenceConfig
    statistics: Mapping[TaxonomyLevel, LevelStatistics]

    def __post_init__(self) -> None:
        if not self.model_version.strip():
            raise ValueError("historical model_version is required")
        _parse_time(self.training_cutoff)
        if not self.corpus_fingerprint or not self.lineage_prefix_fingerprint:
            raise ValueError("historical model fingerprints are required")


@dataclass(frozen=True)
class HistoricalEvidenceValue:
    """Pair-level H result with a strict-positive support predicate."""

    available: bool
    reason: str | None
    resolved_level: TaxonomyLevel | None
    token_a: str | None
    token_b: str | None
    support: int | None
    marginal_a: int | None
    marginal_b: int | None
    episode_population: int | None
    lift: float | None
    strength: float | None
    reliability: float | None
    positive_score: float
    model_version: str | None
    training_cutoff: str | None
    taxonomy_source_id: str | None
    taxonomy_source_version: str | None

    @property
    def supports(self) -> bool:
        """H is SUPPORT iff it has strictly positive evidence, never ``>= 0``."""
        return self.available and self.positive_score > 0.0


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def _tokens_in_episode(
    episode: HistoricalEpisode,
    level: TaxonomyLevel,
    cutoff: datetime,
) -> tuple[set[str], set[tuple[str, str]]]:
    """Return marginal tokens and actual co-group pairs for one episode.

    Tokens may occur in separate split branches and still count as marginals,
    but only two distinct member positions in one chain state make a co-group
    pair.  Sets impose the required one-vote-per-episode deduplication.
    """
    episode_tokens: set[str] = set()
    episode_pairs: set[tuple[str, str]] = set()
    for state in episode.states:
        if _parse_time(state.snapshot_time) >= cutoff:
            continue
        for chain in state.chains:
            resolved = [token.at(level) for token in chain]
            values = [token for token in resolved if token is not None]
            episode_tokens.update(values)
            for index, left in enumerate(values):
                for right in values[index + 1 :]:
                    episode_pairs.add(_pair_key(left, right))
    return episode_tokens, episode_pairs


def _fingerprint(
    episodes: tuple[HistoricalEpisode, ...], cutoff: datetime, lineage_prefix: str
) -> str:
    material = {
        "cutoff": cutoff.isoformat(),
        "lineage_prefix_fingerprint": lineage_prefix,
        "episodes": [
            {
                "episode_id": episode.episode_id,
                "states": [
                    {
                        "snapshot": (state.snapshot_id, state.snapshot_version, state.snapshot_time),
                        "chains": [
                            [
                                (token.type, token.family, token.category)
                                for token in chain
                            ]
                            for chain in state.chains
                        ],
                    }
                    for state in episode.states
                ],
            }
            for episode in sorted(episodes, key=lambda item: item.episode_id)
        ],
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_historical_model(
    episodes: tuple[HistoricalEpisode, ...],
    *,
    training_cutoff: str,
    lineage_prefix_fingerprint: str,
    taxonomy: HistoricalTaxonomy,
    config: HistoricalEvidenceConfig,
    model_version: str | None = None,
) -> HistoricalEvidenceModel:
    """Freeze exact sufficient statistics from the lineage prefix before cutoff."""
    cutoff = _parse_time(training_cutoff)
    corpus_fingerprint = _fingerprint(episodes, cutoff, lineage_prefix_fingerprint)
    statistics: dict[TaxonomyLevel, LevelStatistics] = {}
    for level in _LEVELS:
        population = 0
        marginals: Counter[str] = Counter()
        pairs: Counter[tuple[str, str]] = Counter()
        for episode in episodes:
            tokens, co_group_pairs = _tokens_in_episode(episode, level, cutoff)
            if not tokens:
                continue
            population += 1
            marginals.update(tokens)
            pairs.update(co_group_pairs)
        statistics[level] = LevelStatistics(
            episode_population_count=population,
            marginal_count=dict(sorted(marginals.items())),
            co_group_episode_count=dict(sorted(pairs.items())),
        )
    return HistoricalEvidenceModel(
        model_version=model_version or f"hist_{corpus_fingerprint[:24]}",
        training_cutoff=training_cutoff,
        corpus_fingerprint=corpus_fingerprint,
        lineage_prefix_fingerprint=lineage_prefix_fingerprint,
        taxonomy_source_id=taxonomy.source_id,
        taxonomy_source_version=taxonomy.source_version,
        config=config,
        statistics=statistics,
    )


def _unavailable(
    reason: str,
    *,
    model: HistoricalEvidenceModel | None = None,
    resolved_level: TaxonomyLevel | None = None,
    token_a: str | None = None,
    token_b: str | None = None,
) -> HistoricalEvidenceValue:
    return HistoricalEvidenceValue(
        available=False,
        reason=reason,
        resolved_level=resolved_level,
        token_a=token_a,
        token_b=token_b,
        support=None,
        marginal_a=None,
        marginal_b=None,
        episode_population=None,
        lift=None,
        strength=None,
        reliability=None,
        positive_score=0.0,
        model_version=model.model_version if model else None,
        training_cutoff=model.training_cutoff if model else None,
        taxonomy_source_id=model.taxonomy_source_id if model else None,
        taxonomy_source_version=model.taxonomy_source_version if model else None,
    )


def _common_level(
    left: TaxonomyTokens | None, right: TaxonomyTokens | None
) -> tuple[TaxonomyLevel, str, str] | None:
    if left is None or right is None:
        return None
    for level in _LEVELS:
        left_token, right_token = left.at(level), right.at(level)
        if left_token is not None and right_token is not None:
            return level, left_token, right_token
    return None


def evaluate_historical_evidence(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    *,
    model: HistoricalEvidenceModel | None,
    taxonomy: HistoricalTaxonomy | None,
) -> HistoricalEvidenceValue:
    """Evaluate H by exact count lookup in one immutable model."""
    if model is None:
        return _unavailable("HISTORY_MODEL_UNAVAILABLE")
    if taxonomy is None:
        return _unavailable("TAXONOMY_UNAVAILABLE", model=model)
    if (taxonomy.source_id, taxonomy.source_version) != (
        model.taxonomy_source_id,
        model.taxonomy_source_version,
    ):
        return _unavailable("TAXONOMY_MODEL_MISMATCH", model=model)
    common = _common_level(taxonomy.resolve(alarm_a), taxonomy.resolve(alarm_b))
    if common is None:
        return _unavailable("TAXONOMY_UNAVAILABLE", model=model)
    level, token_a, token_b = common
    stats = model.statistics[level]
    population = stats.episode_population_count
    marginal_a = stats.marginal_count.get(token_a, 0)
    marginal_b = stats.marginal_count.get(token_b, 0)
    if population == 0 or marginal_a == 0 or marginal_b == 0:
        return _unavailable(
            "HISTORY_STATISTICS_UNAVAILABLE",
            model=model,
            resolved_level=level,
            token_a=token_a,
            token_b=token_b,
        )
    support = stats.co_group_episode_count.get(_pair_key(token_a, token_b), 0)
    lift = population * support / (marginal_a * marginal_b)
    positive_history = support >= model.config.min_support and lift > 1.0
    strength = (
        min(1.0, math.log(lift) / math.log(model.config.lift_cap))
        if positive_history
        else 0.0
    )
    reliability = 1.0 - math.exp(-support / model.config.lambda_h)
    score = strength * reliability if positive_history else 0.0
    return HistoricalEvidenceValue(
        available=True,
        reason=None,
        resolved_level=level,
        token_a=token_a,
        token_b=token_b,
        support=support,
        marginal_a=marginal_a,
        marginal_b=marginal_b,
        episode_population=population,
        lift=lift,
        strength=strength,
        reliability=reliability,
        positive_score=score,
        model_version=model.model_version,
        training_cutoff=model.training_cutoff,
        taxonomy_source_id=model.taxonomy_source_id,
        taxonomy_source_version=model.taxonomy_source_version,
    )


def evaluate_historical_oracle(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    *,
    episodes: tuple[HistoricalEpisode, ...],
    training_cutoff: str,
    taxonomy: HistoricalTaxonomy | None,
    config: HistoricalEvidenceConfig,
) -> HistoricalEvidenceValue:
    """Slow reference implementation used only by synthetic equivalence tests."""
    if taxonomy is None:
        return _unavailable("TAXONOMY_UNAVAILABLE")
    common = _common_level(taxonomy.resolve(alarm_a), taxonomy.resolve(alarm_b))
    if common is None:
        return _unavailable("TAXONOMY_UNAVAILABLE")
    level, token_a, token_b = common
    cutoff = _parse_time(training_cutoff)
    population = marginal_a = marginal_b = support = 0
    pair = _pair_key(token_a, token_b)
    for episode in episodes:
        tokens, pairs = _tokens_in_episode(episode, level, cutoff)
        if not tokens:
            continue
        population += 1
        marginal_a += token_a in tokens
        marginal_b += token_b in tokens
        support += pair in pairs
    if population == 0 or marginal_a == 0 or marginal_b == 0:
        return _unavailable("HISTORY_STATISTICS_UNAVAILABLE")
    lift = population * support / (marginal_a * marginal_b)
    positive_history = support >= config.min_support and lift > 1.0
    strength = min(1.0, math.log(lift) / math.log(config.lift_cap)) if positive_history else 0.0
    reliability = 1.0 - math.exp(-support / config.lambda_h)
    score = strength * reliability if positive_history else 0.0
    return HistoricalEvidenceValue(
        available=True,
        reason=None,
        resolved_level=level,
        token_a=token_a,
        token_b=token_b,
        support=support,
        marginal_a=marginal_a,
        marginal_b=marginal_b,
        episode_population=population,
        lift=lift,
        strength=strength,
        reliability=reliability,
        positive_score=score,
        model_version=None,
        training_cutoff=training_cutoff,
        taxonomy_source_id=taxonomy.source_id,
        taxonomy_source_version=taxonomy.source_version,
    )
