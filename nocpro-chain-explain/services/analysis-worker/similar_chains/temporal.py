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
    TermVector,
    TfIdfModel,
    TaxonomyStatus,
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
    snapshot_id: str
    snapshot_version: str

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
    taxonomy_status: TaxonomyStatus = TaxonomyStatus.AVAILABLE,
    taxonomy_reason: str | None = None,
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
        taxonomy_status=taxonomy_status,
        taxonomy_reason=taxonomy_reason,
        size_bin_edges=size_bin_edges,
        duration_bin_edges=duration_bin_edges,
        top_descriptor_predicates=top_descriptor_predicates,
    )
    encoded = tuple(
        TimedChainFingerprint(
            fingerprint=entry.fingerprint.scored_with(model.model_version),
            event_time=entry.event_time,
            snapshot_id=entry.snapshot_id,
            snapshot_version=entry.snapshot_version,
        )
        for entry in eligible
    )
    return VersionedSimilarityIndex(model=model, entries=encoded)


def fingerprint_to_dict(value: ChainFingerprint) -> dict:
    return {
        "chain_id": value.chain_id,
        "lineage_component_id": value.lineage_component_id,
        "family_terms": value.family_terms.counts,
        "device_type_terms": value.device_type_terms.counts,
        "descriptor_terms": list(value.descriptor_terms),
        "size_bin": value.size_bin,
        "duration_bin": value.duration_bin,
        "member_count": value.member_count,
        "scored_with_model_version": value.scored_with_model_version,
    }


def fingerprint_from_dict(value: dict) -> ChainFingerprint:
    return ChainFingerprint(
        chain_id=value["chain_id"],
        lineage_component_id=value.get("lineage_component_id"),
        family_terms=TermVector(dict(value["family_terms"])),
        device_type_terms=TermVector(dict(value["device_type_terms"])),
        descriptor_terms=tuple(value["descriptor_terms"]),
        size_bin=value["size_bin"],
        duration_bin=value["duration_bin"],
        member_count=int(value["member_count"]),
        scored_with_model_version=value.get("scored_with_model_version"),
    )


def model_to_dict(value: FingerprintModel) -> dict:
    return {
        "model_version": value.model_version,
        "trained_until_exclusive": value.trained_until_exclusive,
        "corpus_policy": value.corpus_policy,
        "model_update_policy": value.model_update_policy,
        "taxonomy_policy": value.taxonomy_policy,
        "taxonomy_status": value.taxonomy_status.value,
        "taxonomy_reason": value.taxonomy_reason,
        "vocabulary": list(value.vocabulary),
        "idf_weights": value.idf_weights,
        "family_document_count": value.family_model.document_count,
        "family_document_frequency": value.family_model.document_frequency,
        "device_document_count": value.device_model.document_count,
        "device_document_frequency": value.device_model.document_frequency,
        "size_bin_edges": list(value.size_bin_edges),
        "duration_bin_edges": list(value.duration_bin_edges),
        "top_descriptor_predicates": value.top_descriptor_predicates,
    }


def model_from_dict(value: dict) -> FingerprintModel:
    legacy_policy = value.get("taxonomy_policy", "CALLER_SUPPLIED")
    legacy_unavailable = legacy_policy == "NO_REAL_TAXONOMY_SOURCE"
    return FingerprintModel(
        model_version=value["model_version"],
        trained_until_exclusive=value["trained_until_exclusive"],
        corpus_policy=value["corpus_policy"],
        model_update_policy=value["model_update_policy"],
        taxonomy_policy=legacy_policy,
        taxonomy_status=TaxonomyStatus(
            value.get(
                "taxonomy_status",
                "UNAVAILABLE" if legacy_unavailable else "AVAILABLE",
            )
        ),
        taxonomy_reason=value.get("taxonomy_reason") or (
            "ALARM_TAXONOMY_NOT_USED_BY_SOURCE" if legacy_unavailable else None
        ),
        vocabulary=tuple(value["vocabulary"]),
        idf_weights=dict(value["idf_weights"]),
        family_model=TfIdfModel(
            int(value["family_document_count"]),
            dict(value["family_document_frequency"]),
        ),
        device_model=TfIdfModel(
            int(value["device_document_count"]),
            dict(value["device_document_frequency"]),
        ),
        size_bin_edges=tuple(value["size_bin_edges"]),
        duration_bin_edges=tuple(value["duration_bin_edges"]),
        top_descriptor_predicates=int(value["top_descriptor_predicates"]),
    )
