"""Chain fingerprint for Similar Chains (§8.3, ADR-0022).

    Fingerprint(C) = [ TF-IDF(alarm_family) . TF-IDF(device_type) .
                       top IDENTITY descriptor predicates .
                       size bin . duration bin ]

Backoff (§4A "BACKOFF type->family->category"): when no family taxonomy is
supplied, the family term falls back to ``alarm_type_name`` -- the nearest
level actually present in the real export -- rather than inventing a family
label. ``device_type_name`` is a real column and is used directly, never
guessed from a device-code prefix.

Everything here is deterministic given (chain members, taxonomy, descriptors,
config): no randomness, so the same input always yields the same fingerprint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from channels.semantic import AlarmTaxonomy, EMPTY_TAXONOMY
from descriptor.mining import Descriptor
from libs.contracts import IngestedAlarm

#: Size bin edges (inclusive upper bound), in member count.
DEFAULT_SIZE_BINS: tuple[int, ...] = (1, 2, 5, 10, 20, 50, 100, 500)

#: Duration bin edges (inclusive upper bound), in seconds.
DEFAULT_DURATION_BINS: tuple[int, ...] = (10, 30, 60, 300, 900, 3600, 86400)

#: How many top IDENTITY predicates feed the fingerprint.
DEFAULT_TOP_DESCRIPTOR_PREDICATES = 5


def _bin_index(value: int, edges: tuple[int, ...]) -> int:
    """First bin edge the value does not exceed; the last bin catches overflow."""
    for index, edge in enumerate(edges):
        if value <= edge:
            return index
    return len(edges)


def size_bin(member_count: int, *, edges: tuple[int, ...] = DEFAULT_SIZE_BINS) -> str:
    return f"size_bin_{_bin_index(member_count, edges)}"


def duration_bin(
    duration_seconds: int | None, *, edges: tuple[int, ...] = DEFAULT_DURATION_BINS
) -> str:
    """``None`` duration (e.g. a singleton with no span) gets its own bin.

    A missing duration must not silently collapse into bin 0, which would make
    an unknown span look identical to a genuinely instantaneous chain.
    """
    if duration_seconds is None:
        return "duration_bin_unknown"
    return f"duration_bin_{_bin_index(duration_seconds, edges)}"


def _family_term(alarm: IngestedAlarm, taxonomy: AlarmTaxonomy) -> str | None:
    """Family term with backoff to ``alarm_type_name`` when untaxonomized."""
    name = (alarm.alarm_name or "").strip() or None
    if name is None:
        return None
    family = taxonomy.family_of(name)
    if family is not None:
        return family
    # Backoff: nearest real column above raw alarm_name.
    alarm_type = alarm.raw.get("alarm_type_name")
    return (alarm_type or "").strip() or None


def _device_type_term(alarm: IngestedAlarm) -> str | None:
    """Real ``device_type_name`` column, never guessed from a device-code prefix."""
    value = alarm.raw.get("device_type_name")
    return (value or "").strip() or None


@dataclass(frozen=True)
class TermVector:
    """A sparse bag-of-terms vector, keyed by term id."""

    counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_terms(cls, terms: list[str]) -> TermVector:
        counts: dict[str, int] = {}
        for term in terms:
            counts[term] = counts.get(term, 0) + 1
        return cls(counts=counts)


@dataclass(frozen=True)
class ChainFingerprint:
    """Deterministic fingerprint for one chain, ready for cosine similarity."""

    chain_id: str
    lineage_component_id: str | None
    family_terms: TermVector
    device_type_terms: TermVector
    descriptor_terms: tuple[str, ...]
    size_bin: str
    duration_bin: str
    member_count: int


def build_fingerprint(
    chain_id: str,
    alarms: list[IngestedAlarm],
    *,
    lineage_component_id: str | None = None,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    identity_descriptors: tuple[Descriptor, ...] = (),
    duration_seconds: int | None = None,
    top_descriptor_predicates: int = DEFAULT_TOP_DESCRIPTOR_PREDICATES,
    size_bin_edges: tuple[int, ...] = DEFAULT_SIZE_BINS,
    duration_bin_edges: tuple[int, ...] = DEFAULT_DURATION_BINS,
) -> ChainFingerprint:
    """Build a chain's fingerprint from its members and mined descriptors."""
    family_terms = [
        term for alarm in alarms if (term := _family_term(alarm, taxonomy)) is not None
    ]
    device_terms = [
        term for alarm in alarms if (term := _device_type_term(alarm)) is not None
    ]
    descriptor_terms = tuple(
        d.label for d in identity_descriptors[:top_descriptor_predicates]
    )

    return ChainFingerprint(
        chain_id=chain_id,
        lineage_component_id=lineage_component_id,
        family_terms=TermVector.from_terms(family_terms),
        device_type_terms=TermVector.from_terms(device_terms),
        descriptor_terms=descriptor_terms,
        size_bin=size_bin(len(alarms), edges=size_bin_edges),
        duration_bin=duration_bin(duration_seconds, edges=duration_bin_edges),
        member_count=len(alarms),
    )


@dataclass
class TfIdfModel:
    """Document-frequency model fit over a corpus of chain fingerprints.

    Fit once per snapshot (or benchmark corpus) so idf weights are shared and
    comparable across every chain scored against them.
    """

    document_count: int
    document_frequency: dict[str, int]

    @classmethod
    def fit(cls, term_vectors: list[TermVector]) -> TfIdfModel:
        document_frequency: dict[str, int] = {}
        for vector in term_vectors:
            for term in vector.counts:
                document_frequency[term] = document_frequency.get(term, 0) + 1
        return cls(
            document_count=len(term_vectors), document_frequency=document_frequency
        )

    def idf(self, term: str) -> float:
        """Smoothed idf; unseen terms get the maximum weight rather than zero.

        Zero would make a term absent from the fit corpus vanish entirely,
        which is wrong for a chain fingerprinted after the model was fit.
        """
        df = self.document_frequency.get(term, 0)
        n = self.document_count
        return math.log((1 + n) / (1 + df)) + 1.0

    def tfidf(self, vector: TermVector) -> dict[str, float]:
        return {term: count * self.idf(term) for term, count in vector.counts.items()}
