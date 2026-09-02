"""Effective derivation grouping (V2.3.1 §4B, ADR-0009).

Implements the derivation-group homogeneity invariant: a group is keyed by
``derivation_tag`` *plus* provenance class *plus* eligibility signature, so
``provenance(g)``, ``audit_eligible(g)``, ``role_eligible(g)`` and
``Agreement_external`` are well-defined at group level.

``source_kind`` and ``chaining_usage`` are deliberately excluded from the key:
they constrain Validate only and must not change Explain/Role/Audit grouping
(ADR-0010).

Only normalized ``K_pair`` channels are players. ``SYSTEM_FACT`` adapter objects
(``M_pair``, ``M_chain_rule``, ``M_chain_characteristic``,
``M_attribute_config``) and chain-level descriptors are not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from .classes import ProvenanceClass, ProvenanceSubtype
from .eligibility import EligibilitySignature, baseline_eligibility


@dataclass(frozen=True)
class NormalizedChannel:
    """One normalized pair-evidence channel in ``K_pair``.

    ``availability`` and support are per-pair in the full model; this carries the
    per-pair values for the pair under evaluation.
    """

    channel_id: str
    derivation_tag: str
    provenance_class: ProvenanceClass
    provenance_subtype: ProvenanceSubtype | None = None
    availability: bool = True
    #: Support after applying the channel's own threshold: b_k.
    supports: bool = False
    #: s_k+ for the pair, retained for s_g+ aggregation.
    positive_score: float = 0.0
    #: Validate-only metadata; must not influence grouping.
    source_kind: str | None = None
    chaining_usage: str | None = None

    @property
    def eligibility(self) -> EligibilitySignature:
        return baseline_eligibility(self.provenance_class, self.provenance_subtype)


class PairChannelVerdict(Protocol):
    """Structural view required to normalize a pair channel for grouping."""

    channel_id: str
    derivation_tag: str
    provenance_class: ProvenanceClass
    provenance_subtype: ProvenanceSubtype | None
    availability: bool
    positive_score: float

    @property
    def supports(self) -> bool: ...


def normalize_pair_channels(
    values: Sequence[PairChannelVerdict],
) -> list[NormalizedChannel]:
    """Copy pair verdicts into the grouping model without importing channels.

    The shared helper deliberately lives in ``libs.provenance`` so both audit
    and other exact evidence aggregators can use identical normalization
    without creating an ``audit <-> channels`` import cycle.
    """
    return [
        NormalizedChannel(
            channel_id=value.channel_id,
            derivation_tag=value.derivation_tag,
            provenance_class=value.provenance_class,
            provenance_subtype=value.provenance_subtype,
            availability=value.availability,
            supports=value.supports,
            positive_score=value.positive_score,
        )
        for value in values
    ]


@dataclass(frozen=True)
class EffectiveGroupKey:
    """The semantic homogeneity key from ADR-0009."""

    derivation_tag: str
    provenance_class: ProvenanceClass
    explain_eligible: bool
    role_eligible: bool
    audit_eligible: bool

    @classmethod
    def of(cls, channel: NormalizedChannel) -> EffectiveGroupKey:
        signature = channel.eligibility
        return cls(
            derivation_tag=channel.derivation_tag,
            provenance_class=channel.provenance_class,
            explain_eligible=signature.explain_eligible,
            role_eligible=signature.role_eligible,
            audit_eligible=signature.audit_eligible,
        )


@dataclass
class DerivationGroup:
    """An effective derivation group for one pair."""

    key: EffectiveGroupKey
    channels: list[NormalizedChannel] = field(default_factory=list)

    @property
    def provenance_class(self) -> ProvenanceClass:
        return self.key.provenance_class

    @property
    def eligibility(self) -> EligibilitySignature:
        return EligibilitySignature(
            explain_eligible=self.key.explain_eligible,
            role_eligible=self.key.role_eligible,
            audit_eligible=self.key.audit_eligible,
        )

    @property
    def audit_eligible(self) -> bool:
        return self.key.audit_eligible

    @property
    def role_eligible(self) -> bool:
        return self.key.role_eligible

    @property
    def explain_eligible(self) -> bool:
        return self.key.explain_eligible

    @property
    def availability(self) -> bool:
        """``availability_g = max_k availability_k``.

        Safe because the group is homogeneous: every channel here shares one
        eligibility regime.
        """
        return any(c.availability for c in self.channels)

    @property
    def supports(self) -> bool:
        """``b_g = max_k b_k``, so one derivation casts at most one vote."""
        return any(c.availability and c.supports for c in self.channels)

    @property
    def positive_score(self) -> float:
        """``s_g+``: max supported channel score, or 0 when the group does not support."""
        supported = [
            c.positive_score for c in self.channels if c.availability and c.supports
        ]
        return max(supported) if supported else 0.0

    def eligibility_signatures(self) -> set[tuple[bool, bool, bool]]:
        """Distinct signatures among members; the invariant requires exactly one."""
        return {c.eligibility.as_tuple() for c in self.channels}


def build_derivation_groups(
    channels: list[NormalizedChannel],
) -> list[DerivationGroup]:
    """Group normalized channels into effective derivation groups.

    Channels sharing a ``derivation_tag`` but differing in provenance class or
    eligibility signature land in different groups, which is exactly the
    homogeneity invariant.
    """
    grouped: dict[EffectiveGroupKey, DerivationGroup] = {}
    for channel in channels:
        key = EffectiveGroupKey.of(channel)
        group = grouped.get(key)
        if group is None:
            group = DerivationGroup(key=key)
            grouped[key] = group
        group.channels.append(channel)
    # Sorted for deterministic output.
    return [
        grouped[key]
        for key in sorted(
            grouped,
            key=lambda k: (
                k.derivation_tag,
                k.provenance_class.value,
                k.explain_eligible,
                k.role_eligible,
                k.audit_eligible,
            ),
        )
    ]


def audit_groups(groups: list[DerivationGroup]) -> list[DerivationGroup]:
    """``G_audit(i,j) = {g : audit_eligible(g)=1 ∧ availability_g(i,j)=1}``.

    Both conditions are required, so an unavailable group never reaches the
    ``w*_audit`` denominator.
    """
    return [g for g in groups if g.audit_eligible and g.availability]


def role_groups(groups: list[DerivationGroup]) -> list[DerivationGroup]:
    return [g for g in groups if g.role_eligible and g.availability]
