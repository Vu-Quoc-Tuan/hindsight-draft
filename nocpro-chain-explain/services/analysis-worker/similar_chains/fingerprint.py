"""Chain fingerprint for Similar Chains (§8.3, ADR-0022).

    Fingerprint(C) = [ TF-IDF(alarm_family) . TF-IDF(device_type) .
                       top IDENTITY descriptor predicates .
                       size bin . duration bin ]

Alarm taxonomy resolution is a **data-adapter fallback**, not the
``BACKOFF type->family->category`` rule the spec defines for ``T_delay``/``H``
(§4A). That rule backs a *finer* level off to a *coarser* one; using
``alarm_type_name`` when family is unavailable is the opposite direction, so it
is labeled ``TYPE_FALLBACK`` rather than described as backoff:

    1. canonical alarm_family, if a real taxonomy resolves it
    2. else alarm_type_name, labeled TYPE_FALLBACK
    3. else no term is emitted (never guessed from alarm_name/device_code)

FAMILY and TYPE_FALLBACK terms are namespaced by level before entering the term
vector, so a family value and a differently-sourced type value that happen to
share spelling can never collide in the vocabulary.

``device_type_name`` is a real column and is used verbatim, never guessed from
a device-code prefix.

Everything here is deterministic given (chain members, taxonomy, descriptors,
config): no randomness, so the same input always yields the same fingerprint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from channels.semantic import AlarmTaxonomy, EMPTY_TAXONOMY
from descriptor.mining import Descriptor
from libs.contracts import IngestedAlarm

#: Size bin edges (inclusive upper bound), in member count.
DEFAULT_SIZE_BINS: tuple[int, ...] = (1, 2, 5, 10, 20, 50, 100, 500)

#: Duration bin edges (inclusive upper bound), in seconds.
DEFAULT_DURATION_BINS: tuple[int, ...] = (10, 30, 60, 300, 900, 3600, 86400)

#: How many top IDENTITY predicates feed the fingerprint.
DEFAULT_TOP_DESCRIPTOR_PREDICATES = 5


class TaxonomyLevel(str, Enum):
    """Which level resolved the alarm-taxonomy term for one alarm."""

    FAMILY = "FAMILY"
    #: Resolved from alarm_type_name because no family taxonomy matched.
    TYPE_FALLBACK = "TYPE_FALLBACK"


class TaxonomyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


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


@dataclass(frozen=True)
class AlarmTaxonomyTerm:
    """A resolved taxonomy value plus the level that resolved it."""

    value: str
    level: TaxonomyLevel

    @property
    def namespaced(self) -> str:
        """``LEVEL:value``, so FAMILY and TYPE_FALLBACK never share a vocabulary slot."""
        return f"{self.level.value}:{self.value}"


def _family_term(
    alarm: IngestedAlarm, taxonomy: AlarmTaxonomy
) -> AlarmTaxonomyTerm | None:
    """Resolve the alarm-taxonomy term, tagged with the level that resolved it."""
    name = (alarm.alarm_name or "").strip() or None
    if name is not None:
        family = taxonomy.family_of(name)
        if family is not None:
            return AlarmTaxonomyTerm(value=family, level=TaxonomyLevel.FAMILY)

    # No taxonomy match: fall to alarm_type_name, explicitly labeled as such.
    alarm_type = (alarm.raw.get("alarm_type_name") or "").strip() or None
    if alarm_type is not None:
        return AlarmTaxonomyTerm(value=alarm_type, level=TaxonomyLevel.TYPE_FALLBACK)

    # Real data fallback: use group_name if present
    group = (alarm.raw.get("group_name") or "").strip() or None
    if group is not None:
        return AlarmTaxonomyTerm(value=group, level=TaxonomyLevel.FAMILY)

    # Real data fallback: use fault_id if present
    fault_id = str(alarm.raw.get("fault_id") or "").strip() or None
    if fault_id:
        return AlarmTaxonomyTerm(value=f"FAULT_{fault_id}", level=TaxonomyLevel.TYPE_FALLBACK)

    # Neither resolves: no term. Never guessed from alarm_name/device_code.
    return None


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
    """Deterministic fingerprint for one chain, ready for cosine similarity.

    The fingerprint's raw term vectors are model-independent; ``TfIdfModel``
    weighting is applied at scoring time. But a *scored* result (e.g. cached
    for reuse) is only meaningful under the model that produced it, so
    ``scored_with_model_version`` lets a cached/persisted fingerprint record
    which model last scored it. ``None`` means "never scored", which is the
    normal state for a freshly built fingerprint headed into
    :func:`fit_fingerprint_model`.
    """

    chain_id: str
    lineage_component_id: str | None
    family_terms: TermVector
    device_type_terms: TermVector
    descriptor_terms: tuple[str, ...]
    size_bin: str
    duration_bin: str
    member_count: int
    scored_with_model_version: str | None = None

    def scored_with(self, model_version: str) -> ChainFingerprint:
        """Return a copy stamped with the model version that scored it."""
        from dataclasses import replace

        return replace(self, scored_with_model_version=model_version)

    def active_blocks(self) -> tuple[str, ...]:
        """Fingerprint blocks that actually contributed a term.

        Used for the "basis N/5 feature blocks available" diagnostic: a
        cosine=1.0 result between two singletons with an empty taxonomy is a
        real collision under a *reduced* representation, not proof the two
        incidents are identical. The UI must be able to say which blocks were
        actually compared.
        """
        blocks = []
        if self.family_terms.counts:
            blocks.append("alarm_taxonomy")
        if self.device_type_terms.counts:
            blocks.append("device_type")
        if self.descriptor_terms:
            blocks.append("identity_descriptors")
        # size_bin/duration_bin are always present by construction.
        blocks.append("size_bin")
        blocks.append("duration_bin")
        return tuple(blocks)

    def missing_blocks(self) -> tuple[str, ...]:
        all_blocks = ("alarm_taxonomy", "device_type", "identity_descriptors", "size_bin", "duration_bin")
        active = set(self.active_blocks())
        return tuple(b for b in all_blocks if b not in active)


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
    include_taxonomy_terms: bool = True,
) -> ChainFingerprint:
    """Build a chain's fingerprint from its members and mined descriptors."""
    # A caller that declares taxonomy unavailable must not let raw
    # alarm_type/group/fault fields reappear as an implicit taxonomy vector.
    # The remaining fingerprint blocks are still exact source facts.
    family_terms = (
        [
            term.namespaced
            for alarm in alarms
            if (term := _family_term(alarm, taxonomy)) is not None
        ]
        if include_taxonomy_terms
        else []
    )
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
    """Document-frequency model fit over a corpus of chain fingerprints."""

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


@dataclass(frozen=True)
class FingerprintModel:
    """Everything needed to score fingerprints comparably, bundled as one unit.

    The spec requires cosine to be deterministic, but does not say which
    corpus the IDF weights are fit on. Left as two loose ``TfIdfModel``
    instances, nothing stops a caller from re-fitting per query batch or
    mixing a cached fingerprint's vector with a model fit at a different time
    -- comparing scores that no longer live in the same vector space.

    Bundling family/device IDF, the taxonomy/descriptor/bin config that
    produced the fingerprints, and an explicit ``model_version`` into one
    object makes "same model" a single object identity check instead of an
    implicit assumption. All fingerprints scored against each other in one
    request MUST be built with the same ``model_version``, and MUST be scored
    through the same ``FingerprintModel`` instance.
    """

    model_version: str
    trained_until_exclusive: str
    corpus_policy: str
    model_update_policy: str
    taxonomy_policy: str
    taxonomy_status: TaxonomyStatus
    taxonomy_reason: str | None
    vocabulary: tuple[str, ...]
    idf_weights: dict[str, float]
    family_model: TfIdfModel
    device_model: TfIdfModel
    size_bin_edges: tuple[int, ...]
    duration_bin_edges: tuple[int, ...]
    top_descriptor_predicates: int


def fit_fingerprint_model(
    fingerprints: list[ChainFingerprint],
    *,
    model_version: str,
    trained_until_exclusive: str = "9999-12-31T23:59:59Z",
    corpus_policy: str = "FROZEN_TRAINING",
    model_update_policy: str = "FROZEN",
    taxonomy_policy: str = "CALLER_SUPPLIED",
    taxonomy_status: TaxonomyStatus = TaxonomyStatus.AVAILABLE,
    taxonomy_reason: str | None = None,
    size_bin_edges: tuple[int, ...] = DEFAULT_SIZE_BINS,
    duration_bin_edges: tuple[int, ...] = DEFAULT_DURATION_BINS,
    top_descriptor_predicates: int = DEFAULT_TOP_DESCRIPTOR_PREDICATES,
) -> FingerprintModel:
    """Fit one versioned model over an index corpus.

    Fit once per index build. Re-fitting per query batch is exactly the
    inconsistency this type exists to prevent; encode the query fingerprint
    with the already-fit model instead of fitting a new one from it.
    """
    family_model = TfIdfModel.fit([fp.family_terms for fp in fingerprints])
    if taxonomy_status is TaxonomyStatus.UNAVAILABLE:
        if taxonomy_reason is None or not taxonomy_reason.strip():
            raise ValueError("unavailable taxonomy requires a reason")
        if family_model.document_frequency:
            raise ValueError(
                "taxonomy cannot be UNAVAILABLE when taxonomy terms are present"
            )
    device_model = TfIdfModel.fit([fp.device_type_terms for fp in fingerprints])
    vocabulary = tuple(
        sorted(
            {f"family:{term}" for term in family_model.document_frequency}
            | {f"device:{term}" for term in device_model.document_frequency}
            | {
                f"descriptor:{term}"
                for fingerprint in fingerprints
                for term in fingerprint.descriptor_terms
            }
            | {f"size:{fingerprint.size_bin}" for fingerprint in fingerprints}
            | {
                f"duration:{fingerprint.duration_bin}"
                for fingerprint in fingerprints
            }
        )
    )
    idf_weights = {
        **{
            f"family:{term}": family_model.idf(term)
            for term in family_model.document_frequency
        },
        **{
            f"device:{term}": device_model.idf(term)
            for term in device_model.document_frequency
        },
    }
    return FingerprintModel(
        model_version=model_version,
        trained_until_exclusive=trained_until_exclusive,
        corpus_policy=corpus_policy,
        model_update_policy=model_update_policy,
        taxonomy_policy=taxonomy_policy,
        taxonomy_status=taxonomy_status,
        taxonomy_reason=taxonomy_reason,
        vocabulary=vocabulary,
        idf_weights=idf_weights,
        family_model=family_model,
        device_model=device_model,
        size_bin_edges=size_bin_edges,
        duration_bin_edges=duration_bin_edges,
        top_descriptor_predicates=top_descriptor_predicates,
    )
