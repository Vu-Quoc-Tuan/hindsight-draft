"""Normalized pair-evidence channel primitives (§4/4A).

Every channel in ``K_pair`` carries ``s+``/``s-`` in [0,1], an availability bit, a
derivation tag, a provenance class and a threshold. The three-state distinction is
mandatory:

- SUPPORT      available and ``s+ >= theta``
- NEUTRAL      available, computed, below threshold
- UNAVAILABLE  not computable (⊥)

Conflating NEUTRAL with UNAVAILABLE is what makes WEAK indistinguishable from
INSUFFICIENT DATA, so the two are kept apart throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from libs.provenance import ProvenanceClass, ProvenanceSubtype

from .contracts import ChannelFamily, DependencySemantic


class EvidenceState(str, Enum):
    SUPPORT = "SUPPORT"
    #: Computed and below threshold. This is real information.
    NEUTRAL = "NEUTRAL"
    #: Not computable (⊥). Absence of information, never negative evidence.
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ChannelValue:
    """One channel's verdict for one ordered pair."""

    channel_id: str
    derivation_tag: str
    provenance_class: ProvenanceClass
    availability: bool
    positive_score: float
    threshold: float
    negative_score: float = 0.0
    provenance_subtype: ProvenanceSubtype | None = None
    detail: str | None = None
    #: Stable serialized family. Provider-specific ``channel_id`` stays internal.
    channel_family: ChannelFamily | None = None
    #: Dependency claim tier; intentionally independent from numeric score.
    dependency_semantic: DependencySemantic | None = None
    #: Versioned source/model identity used to derive the effective group tag.
    source_ref: str | None = None

    def __post_init__(self) -> None:
        # Normalized channels are contractually bounded; raw SYSTEM_FACT values
        # live in M_pair and never pass through here.
        if self.availability:
            for name, value in (
                ("positive_score", self.positive_score),
                ("negative_score", self.negative_score),
            ):
                if not 0.0 <= value <= 1.0:
                    raise ValueError(
                        f"{self.channel_id}: {name}={value} outside [0,1]; raw "
                        "system scores must stay in M_pair (ADR-0008)"
                    )

    @property
    def state(self) -> EvidenceState:
        if not self.availability:
            return EvidenceState.UNAVAILABLE
        return (
            EvidenceState.SUPPORT
            if self.positive_score >= self.threshold
            else EvidenceState.NEUTRAL
        )

    @property
    def supports(self) -> bool:
        """``b_k = 1[availability_k=1 and s_k+ >= theta_k]``."""
        return self.state is EvidenceState.SUPPORT


def unavailable(
    channel_id: str,
    derivation_tag: str,
    provenance_class: ProvenanceClass,
    *,
    reason: str,
    threshold: float = 0.0,
    provenance_subtype: ProvenanceSubtype | None = None,
    channel_family: ChannelFamily | None = None,
    dependency_semantic: DependencySemantic | None = None,
    source_ref: str | None = None,
) -> ChannelValue:
    """Build an explicit ⊥ value.

    Used whenever an input is missing, e.g. an unmapped resource for ``Dep_hop``.
    Fail closed: never emit 0.0 as if the channel had been computed.
    """
    return ChannelValue(
        channel_id=channel_id,
        derivation_tag=derivation_tag,
        provenance_class=provenance_class,
        provenance_subtype=provenance_subtype,
        availability=False,
        positive_score=0.0,
        threshold=threshold,
        detail=reason,
        channel_family=channel_family,
        dependency_semantic=dependency_semantic,
        source_ref=source_ref,
    )
