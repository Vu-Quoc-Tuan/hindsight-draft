"""Temporal, versioned Similar Chains model materialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .fingerprint import (
    DEFAULT_DURATION_BINS,
    DEFAULT_SIZE_BINS,
    DEFAULT_TOP_DESCRIPTOR_PREDICATES,
    ChainFingerprint,
    FingerprintModel,
    fit_fingerprint_model,
)


class CorpusPolicy(str, Enum):
    HISTORY_BEFORE_SNAPSHOT = "HISTORY_BEFORE_SNAPSHOT"
    FROZEN_TRAINING = "FROZEN_TRAINING"


class ModelUpdatePolicy(str, Enum):
    SNAPSHOT_VERSIONED = "SNAPSHOT_VERSIONED"
    FROZEN = "FROZEN"


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class TimedChainFingerprint:
    fingerprint: ChainFingerprint
    event_time: str

    def __post_init__(self) -> None:
        parse_time(self.event_time)


@dataclass(frozen=True)
class VersionedSimilarityIndex:
    """One immutable vector space and the historical chains encoded in it."""

    model: FingerprintModel
    entries: tuple[TimedChainFingerprint, ...]

    def __post_init__(self) -> None:
        cutoff = parse_time(self.model.trained_until_exclusive)
        for entry in self.entries:
            if parse_time(entry.event_time) >= cutoff:
                raise ValueError(
                    f"chain {entry.fingerprint.chain_id!r} is not before exclusive "
                    f"training cutoff {self.model.trained_until_exclusive!r}"
                )
            if entry.fingerprint.scored_with_model_version != self.model.model_version:
                raise ValueError(
                    f"chain {entry.fingerprint.chain_id!r} is not encoded under "
                    f"model {self.model.model_version!r}"
                )

    @property
    def corpus(self) -> tuple[ChainFingerprint, ...]:
        return tuple(entry.fingerprint for entry in self.entries)


def materialize_similarity_index(
    history: list[TimedChainFingerprint],
    *,
    model_version: str,
    trained_until_exclusive: str,
    corpus_policy: CorpusPolicy,
    model_update_policy: ModelUpdatePolicy,
    taxonomy_policy: str,
    size_bin_edges: tuple[int, ...] = DEFAULT_SIZE_BINS,
    duration_bin_edges: tuple[int, ...] = DEFAULT_DURATION_BINS,
    top_descriptor_predicates: int = DEFAULT_TOP_DESCRIPTOR_PREDICATES,
) -> VersionedSimilarityIndex:
    """Fit once from eligible history and freeze the resulting search index."""
    cutoff = parse_time(trained_until_exclusive)
    eligible = tuple(
        sorted(
            (entry for entry in history if parse_time(entry.event_time) < cutoff),
            key=lambda entry: (parse_time(entry.event_time), entry.fingerprint.chain_id),
        )
    )
    model = fit_fingerprint_model(
        [entry.fingerprint for entry in eligible],
        model_version=model_version,
        trained_until_exclusive=trained_until_exclusive,
        corpus_policy=corpus_policy.value,
        model_update_policy=model_update_policy.value,
        taxonomy_policy=taxonomy_policy,
        size_bin_edges=size_bin_edges,
        duration_bin_edges=duration_bin_edges,
        top_descriptor_predicates=top_descriptor_predicates,
    )
    encoded = tuple(
        TimedChainFingerprint(
            fingerprint=entry.fingerprint.scored_with(model.model_version),
            event_time=entry.event_time,
        )
        for entry in eligible
    )
    return VersionedSimilarityIndex(model=model, entries=encoded)
