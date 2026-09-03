"""Immutable T_delay training model; deliberately not yet a channel adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from math import erf, floor, log, sqrt
from typing import ClassVar, Iterable

from history import TaxonomyLevel, TaxonomyTokens


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


class DelayEstimator(str, Enum):
    HISTOGRAM = "HISTOGRAM"
    GAUSSIAN_KDE = "GAUSSIAN_KDE"


@dataclass(frozen=True, order=True)
class DelayRelationKey:
    level: TaxonomyLevel
    source_token: str
    target_token: str


@dataclass(frozen=True)
class DelayObservation:
    episode_id: str
    source_alarm_id: str
    target_alarm_id: str
    key: DelayRelationKey
    delay_seconds: float
    source_snapshot_id: str | None = None
    source_snapshot_version: str | None = None
    source_chain_id: str | None = None

    def __post_init__(self) -> None:
        if self.delay_seconds < 0:
            raise ValueError("directed delay must be nonnegative")


@dataclass(frozen=True)
class DelayModelConfig:
    config_version: str
    min_relation_episodes: int
    model_selection_min_episodes: int
    validation_fraction: float
    model_selection_seed: int
    local_mass_halfwidth_candidates_seconds: tuple[float, ...]
    histogram_bin_width_candidates_seconds: tuple[float, ...]
    kde_bandwidth_candidates_seconds: tuple[float, ...]
    fallback_model: DelayEstimator
    fallback_local_mass_halfwidth_seconds: float
    fallback_histogram_bin_width_seconds: float | None = None
    fallback_kde_bandwidth_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.min_relation_episodes < 1 or self.model_selection_min_episodes < self.min_relation_episodes:
            raise ValueError("invalid temporal delay episode thresholds")
        if not 0 < self.validation_fraction < 1:
            raise ValueError("validation_fraction must be between zero and one")
        if not self.local_mass_halfwidth_candidates_seconds or any(v <= 0 for v in self.local_mass_halfwidth_candidates_seconds):
            raise ValueError("local mass halfwidth candidates are required")
        if not self.histogram_bin_width_candidates_seconds or any(v <= 0 for v in self.histogram_bin_width_candidates_seconds):
            raise ValueError("histogram bin candidates are required")
        if not self.kde_bandwidth_candidates_seconds or any(v <= 0 for v in self.kde_bandwidth_candidates_seconds):
            raise ValueError("KDE bandwidth candidates are required")
        if self.fallback_local_mass_halfwidth_seconds <= 0:
            raise ValueError("fallback local mass halfwidth is required")

    def fallback_parameter(self) -> float | None:
        value = self.fallback_histogram_bin_width_seconds if self.fallback_model is DelayEstimator.HISTOGRAM else self.fallback_kde_bandwidth_seconds
        return float(value) if value is not None and value > 0 else None


@dataclass(frozen=True)
class SelectedDelayRelation:
    key: DelayRelationKey
    observations: tuple[DelayObservation, ...]
    episode_sample_count: int
    raw_observation_count: int
    effective_weight: float
    estimator: DelayEstimator
    local_mass_halfwidth_seconds: float
    estimator_parameter_seconds: float
    selection_mode: str
    held_out_score: float | None
    train_episode_ids: tuple[str, ...] = ()
    holdout_episode_ids: tuple[str, ...] = ()

    # This is deliberately part of the immutable model implementation contract.
    # Runtime and oracle use the same finite, deterministic support points rather
    # than relying on an optimiser whose result can vary by numerical library.
    PEAK_MASS_PROCEDURE: ClassVar[str] = "OBSERVATION_SUPPORT_POINTS_V1"

    def _weights(self) -> tuple[float, ...]:
        counts: dict[str, int] = {}
        for item in self.observations:
            counts[item.episode_id] = counts.get(item.episode_id, 0) + 1
        return tuple(1 / counts[item.episode_id] for item in self.observations)

    def local_mass(self, delay: float) -> float:
        weights = self._weights()
        if self.estimator is DelayEstimator.HISTOGRAM:
            width = self.estimator_parameter_seconds
            bins: dict[int, float] = {}
            for item, weight in zip(self.observations, weights, strict=True):
                index = floor(item.delay_seconds / width)
                bins[index] = bins.get(index, 0.0) + weight
            low, high = delay - self.local_mass_halfwidth_seconds, delay + self.local_mass_halfwidth_seconds
            return sum(
                mass for index, mass in bins.items()
                if (index + 1) * width > low and index * width < high
            )
        bandwidth = self.estimator_parameter_seconds
        root = sqrt(2.0) * bandwidth
        return sum(
            w * 0.5 * (erf((delay + self.local_mass_halfwidth_seconds - item.delay_seconds) / root) - erf((delay - self.local_mass_halfwidth_seconds - item.delay_seconds) / root))
            for item, w in zip(self.observations, weights, strict=True)
        )

    def typicality(self, delay: float) -> float:
        peak = self.normalizing_peak_mass()
        return self.local_mass(delay) / peak if peak > 0 else 0.0

    def normalizing_peak_mass(self) -> float:
        return max((self.local_mass(item.delay_seconds) for item in self.observations), default=0.0)


@dataclass(frozen=True)
class FrozenDelayModel:
    model_version: str
    training_cutoff: str
    corpus_fingerprint: str
    lineage_prefix_fingerprint: str
    taxonomy_source_id: str
    taxonomy_source_version: str
    config: DelayModelConfig
    relations: dict[DelayRelationKey, SelectedDelayRelation]
    unavailable_relations: dict[DelayRelationKey, str]

    implementation_version: str = "TEMPORAL_DELAY_MODEL_V1"


def model_to_dict(model: FrozenDelayModel) -> dict:
    def key(value: DelayRelationKey) -> list[str]:
        return [value.level.value, value.source_token, value.target_token]
    def observation(value: DelayObservation) -> dict:
        return {
            "episode_id": value.episode_id, "source_alarm_id": value.source_alarm_id,
            "target_alarm_id": value.target_alarm_id, "key": key(value.key),
            "delay_seconds": value.delay_seconds, "source_snapshot_id": value.source_snapshot_id,
            "source_snapshot_version": value.source_snapshot_version, "source_chain_id": value.source_chain_id,
        }
    def relation(value: SelectedDelayRelation) -> dict:
        return {
            "key": key(value.key), "observations": [observation(item) for item in value.observations],
            "episode_sample_count": value.episode_sample_count, "raw_observation_count": value.raw_observation_count,
            "effective_weight": value.effective_weight, "estimator": value.estimator.value,
            "local_mass_halfwidth_seconds": value.local_mass_halfwidth_seconds,
            "estimator_parameter_seconds": value.estimator_parameter_seconds,
            "selection_mode": value.selection_mode, "held_out_score": value.held_out_score,
            "train_episode_ids": list(value.train_episode_ids), "holdout_episode_ids": list(value.holdout_episode_ids),
        }
    return {
        "model_version": model.model_version, "training_cutoff": model.training_cutoff,
        "corpus_fingerprint": model.corpus_fingerprint, "lineage_prefix_fingerprint": model.lineage_prefix_fingerprint,
        "taxonomy_source_id": model.taxonomy_source_id, "taxonomy_source_version": model.taxonomy_source_version,
        "implementation_version": model.implementation_version,
        "config": {name: (value.value if isinstance(value, DelayEstimator) else list(value) if isinstance(value, tuple) else value) for name, value in model.config.__dict__.items()},
        "relations": [relation(value) for _, value in sorted(model.relations.items())],
        "unavailable_relations": [[key(value), reason] for value, reason in sorted(model.unavailable_relations.items())],
    }


def model_from_dict(value: dict) -> FrozenDelayModel:
    def parse_key(raw: list[str]) -> DelayRelationKey:
        return DelayRelationKey(TaxonomyLevel(raw[0]), raw[1], raw[2])
    config_payload = dict(value["config"])
    for name in ("local_mass_halfwidth_candidates_seconds", "histogram_bin_width_candidates_seconds", "kde_bandwidth_candidates_seconds"):
        config_payload[name] = tuple(config_payload[name])
    config_payload["fallback_model"] = DelayEstimator(config_payload["fallback_model"])
    config = DelayModelConfig(**config_payload)
    relations = {}
    for raw in value["relations"]:
        observations = tuple(DelayObservation(item["episode_id"], item["source_alarm_id"], item["target_alarm_id"], parse_key(item["key"]), float(item["delay_seconds"]), item.get("source_snapshot_id"), item.get("source_snapshot_version"), item.get("source_chain_id")) for item in raw["observations"])
        selected = SelectedDelayRelation(parse_key(raw["key"]), observations, int(raw["episode_sample_count"]), int(raw["raw_observation_count"]), float(raw["effective_weight"]), DelayEstimator(raw["estimator"]), float(raw["local_mass_halfwidth_seconds"]), float(raw["estimator_parameter_seconds"]), raw["selection_mode"], raw.get("held_out_score"), tuple(raw.get("train_episode_ids", ())), tuple(raw.get("holdout_episode_ids", ())))
        relations[selected.key] = selected
    unavailable = {parse_key(key): reason for key, reason in value.get("unavailable_relations", ())}
    return FrozenDelayModel(value["model_version"], value["training_cutoff"], value["corpus_fingerprint"], value["lineage_prefix_fingerprint"], value["taxonomy_source_id"], value["taxonomy_source_version"], config, relations, unavailable, value.get("implementation_version", "TEMPORAL_DELAY_MODEL_V1"))


@dataclass(frozen=True)
class DelayLookup:
    available: bool
    reason: str | None
    resolved_level: TaxonomyLevel | None
    relation_key: DelayRelationKey | None
    delay_seconds: float | None
    relation: SelectedDelayRelation | None
    local_mass: float | None
    normalizing_peak_mass: float | None
    positive_score: float
    backoff_reason: str | None = None

    @property
    def supports(self) -> bool:
        return self.available and self.positive_score > 0


def _split(episode_id: str, seed: int, model_salt: str, fraction: float) -> bool:
    value = int(hashlib.sha256(f"{episode_id}\0{seed}\0{model_salt}".encode()).hexdigest()[:16], 16)
    return value / (2**64) < fraction


def _select(key: DelayRelationKey, observations: tuple[DelayObservation, ...], config: DelayModelConfig, salt: str) -> tuple[SelectedDelayRelation | None, str | None]:
    episodes = sorted({item.episode_id for item in observations})
    candidate_rows: list[tuple[float, str, float, float]] = []
    holdout = {episode for episode in episodes if _split(episode, config.model_selection_seed, salt, config.validation_fraction)}
    train = set(episodes) - holdout
    if len(episodes) >= config.model_selection_min_episodes and holdout and train:
        train_obs = tuple(item for item in observations if item.episode_id in train)
        holdout_obs = tuple(item for item in observations if item.episode_id in holdout)
        for estimator, parameters in ((DelayEstimator.HISTOGRAM, config.histogram_bin_width_candidates_seconds), (DelayEstimator.GAUSSIAN_KDE, config.kde_bandwidth_candidates_seconds)):
            for parameter in parameters:
                for halfwidth in config.local_mass_halfwidth_candidates_seconds:
                    candidate = SelectedDelayRelation(key, train_obs, len(train), len(train_obs), float(len(train)), estimator, halfwidth, parameter, "HELD_OUT_SELECTED", None, tuple(sorted(train)), tuple(sorted(holdout)))
                    # Selection is episode-balanced and predictive: every
                    # observation contributes its relation-local episode weight
                    # to log local probability mass.  The numerical floor is
                    # only for log stability, never an evidence threshold.
                    holdout_counts: dict[str, int] = {}
                    for item in holdout_obs:
                        holdout_counts[item.episode_id] = holdout_counts.get(item.episode_id, 0) + 1
                    score = sum(
                        (1 / holdout_counts[item.episode_id]) * log(max(candidate.local_mass(item.delay_seconds), 1e-12))
                        for item in holdout_obs
                    ) / len(holdout_obs)
                    candidate_rows.append((score, estimator.value, parameter, halfwidth))
    if candidate_rows:
        score, name, parameter, halfwidth = sorted(candidate_rows, key=lambda item: (-item[0], item[1], item[2], item[3]))[0]
        estimator = DelayEstimator(name)
        mode = "HELD_OUT_SELECTED"
    else:
        estimator = config.fallback_model
        parameter = config.fallback_parameter()
        if parameter is None:
            return None, "TEMPORAL_DELAY_CONFIG_INCOMPLETE"
        halfwidth, score, mode = config.fallback_local_mass_halfwidth_seconds, None, "CONFIGURED_FALLBACK"
    return SelectedDelayRelation(key, observations, len(episodes), len(observations), float(len(episodes)), estimator, halfwidth, float(parameter), mode, score, tuple(sorted(train)) if mode == "HELD_OUT_SELECTED" else tuple(episodes), tuple(sorted(holdout)) if mode == "HELD_OUT_SELECTED" else ()), None


def build_delay_model(
    observations: Iterable[DelayObservation], *, training_cutoff: str, lineage_prefix_fingerprint: str,
    taxonomy_source_id: str, taxonomy_source_version: str, config: DelayModelConfig,
) -> FrozenDelayModel:
    dedup = {(item.episode_id, item.source_alarm_id, item.target_alarm_id, item.key.level): item for item in observations}
    grouped: dict[DelayRelationKey, list[DelayObservation]] = {}
    for item in dedup.values():
        grouped.setdefault(item.key, []).append(item)
    material = [
        (item.episode_id, item.source_alarm_id, item.target_alarm_id, item.key.level.value, item.key.source_token, item.key.target_token, item.delay_seconds, item.source_snapshot_id, item.source_snapshot_version, item.source_chain_id)
        for item in sorted(dedup.values(), key=lambda item: (item.key, item.episode_id, item.source_alarm_id, item.target_alarm_id))
    ]
    fingerprint_input = {"cutoff": training_cutoff, "prefix": lineage_prefix_fingerprint, "taxonomy": [taxonomy_source_id, taxonomy_source_version], "config": repr(config), "observations": material}
    corpus = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    relations, unavailable = {}, {}
    for key, items in grouped.items():
        values = tuple(sorted(items, key=lambda item: (item.episode_id, item.source_alarm_id, item.target_alarm_id)))
        if len({item.episode_id for item in values}) < config.min_relation_episodes:
            continue
        relation, reason = _select(key, values, config, corpus)
        if relation is not None: relations[key] = relation
        else: unavailable[key] = reason or "TEMPORAL_DELAY_MODEL_UNAVAILABLE"
    return FrozenDelayModel(f"delay_{corpus[:24]}", training_cutoff, corpus, lineage_prefix_fingerprint, taxonomy_source_id, taxonomy_source_version, config, relations, unavailable)


def evaluate_delay_model(
    source: TaxonomyTokens | None, target: TaxonomyTokens | None, *, delay_seconds: float,
    model: FrozenDelayModel | None,
) -> DelayLookup:
    if model is None:
        return DelayLookup(False, "TEMPORAL_DELAY_MODEL_UNAVAILABLE", None, None, None, None, None, None, 0.0)
    if source is None or target is None:
        return DelayLookup(False, "TAXONOMY_UNAVAILABLE", None, None, None, None, None, None, 0.0)
    last_reason = "INSUFFICIENT_TEMPORAL_HISTORY"
    backoff_reason = None
    for level in (TaxonomyLevel.TYPE, TaxonomyLevel.FAMILY, TaxonomyLevel.CATEGORY):
        left, right = source.at(level), target.at(level)
        if left is None or right is None:
            continue
        key = DelayRelationKey(level, left, right)
        relation = model.relations.get(key)
        if relation is None:
            if key in model.unavailable_relations:
                return DelayLookup(False, model.unavailable_relations[key], level, key, delay_seconds, None, None, None, 0.0)
            last_reason = f"INSUFFICIENT_{level.value}_TEMPORAL_HISTORY"
            backoff_reason = last_reason
            continue
        local = relation.local_mass(delay_seconds)
        peak = relation.normalizing_peak_mass()
        return DelayLookup(True, None, level, key, delay_seconds, relation, local, peak, local / peak if peak else 0.0, backoff_reason)
    return DelayLookup(False, "INSUFFICIENT_TEMPORAL_HISTORY", None, None, delay_seconds, None, None, None, 0.0, backoff_reason)


def evaluate_ordered_delay_model(
    left: TaxonomyTokens | None, right: TaxonomyTokens | None, *, left_start: str, right_start: str,
    model: FrozenDelayModel | None,
) -> DelayLookup:
    """Choose the learned direction from strict current temporal order."""
    left_time, right_time = _time(left_start), _time(right_start)
    if left_time == right_time:
        return DelayLookup(False, "NO_DIRECTED_TEMPORAL_ORDER", None, None, 0.0, None, None, None, 0.0)
    if left_time < right_time:
        return evaluate_delay_model(left, right, delay_seconds=(right_time - left_time).total_seconds(), model=model)
    return evaluate_delay_model(right, left, delay_seconds=(left_time - right_time).total_seconds(), model=model)


def evaluate_delay_model_oracle(
    source: TaxonomyTokens | None, target: TaxonomyTokens | None, *, delay_seconds: float,
    observations: Iterable[DelayObservation], training_cutoff: str,
    lineage_prefix_fingerprint: str, taxonomy_source_id: str, taxonomy_source_version: str,
    config: DelayModelConfig,
) -> DelayLookup:
    """Reference path which reconstructs a model from an unsorted raw corpus."""
    # The production path receives an already frozen indexed relation map.  The
    # oracle deliberately begins with raw observations and independently applies
    # canonical identity deduplication before invoking the deterministic fitter.
    raw = list(observations)
    canonical: dict[tuple[str, str, str, TaxonomyLevel], DelayObservation] = {}
    for item in raw:
        canonical.setdefault(
            (item.episode_id, item.source_alarm_id, item.target_alarm_id, item.key.level), item
        )
    frozen = build_delay_model(
        tuple(canonical[key] for key in sorted(canonical)), training_cutoff=training_cutoff,
        lineage_prefix_fingerprint=lineage_prefix_fingerprint,
        taxonomy_source_id=taxonomy_source_id, taxonomy_source_version=taxonomy_source_version,
        config=config,
    )
    return evaluate_delay_model(source, target, delay_seconds=delay_seconds, model=frozen)
