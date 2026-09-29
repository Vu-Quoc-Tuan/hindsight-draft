"""Exact cross-chain audit-evidence statistics.

This module evaluates the bounded Cartesian pair space ``C_left x C_right``
for two distinct chains.  It is deliberately an evidence primitive, not a
merge recommender: it has no policy thresholds, ranking, candidate ceiling or
operation semantics.

The derivation-group and audit-edge definitions are reused exactly from the
canonical audit path.  In particular, unavailable evidence remains outside an
available denominator, and an audit edge requires support from at least two
distinct audit-eligible derivation groups.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedPackage
from libs.provenance import (
    EffectiveGroupKey,
    build_derivation_groups,
    normalize_pair_channels,
)

from .dependency import (
    DEFAULT_D_MAX,
    PHYSICAL_RELATIONS,
    ResourceResolver,
    TopologyGraph,
    build_topology_graph,
)
from .evaluator import DEFAULT_DELAY_THRESHOLD, _evaluate_pair
from .semantic import EMPTY_TAXONOMY, AlarmTaxonomy
from .temporal import DEFAULT_SILENT_GAP_SECONDS, DelayDistribution, segment_bursts


@dataclass(frozen=True)
class CrossGroupStatistics:
    """Exact counts for one audit-eligible effective derivation group."""

    key: EffectiveGroupKey
    available_count: int
    support_count: int

    @property
    def cross_fit(self) -> float | None:
        """``S_g^x / A_g^x`` or ``None`` (bottom) when unavailable everywhere."""
        if self.available_count == 0:
            return None
        return self.support_count / self.available_count


@dataclass(frozen=True)
class CrossChainEvidence:
    """Exact descriptive evidence over one canonical cross-chain pair space."""

    left_chain_id: str
    right_chain_id: str
    cross_pair_count: int
    groups: tuple[CrossGroupStatistics, ...]
    cross_audit_edge_count: int
    cross_evidence_union_pair_count: int

    @property
    def cross_available_counts_by_group(self) -> dict[EffectiveGroupKey, int]:
        return {group.key: group.available_count for group in self.groups}

    @property
    def cross_support_counts_by_group(self) -> dict[EffectiveGroupKey, int]:
        return {group.key: group.support_count for group in self.groups}

    @property
    def cross_fit_by_group(self) -> dict[EffectiveGroupKey, float | None]:
        return {group.key: group.cross_fit for group in self.groups}

    @property
    def cross_audit_edge_coverage(self) -> float:
        if self.cross_pair_count == 0:
            return 0.0
        return self.cross_audit_edge_count / self.cross_pair_count

    @property
    def cross_evidence_union_coverage(self) -> float:
        if self.cross_pair_count == 0:
            return 0.0
        return self.cross_evidence_union_pair_count / self.cross_pair_count

    @property
    def cross_supported_group_count(self) -> int:
        return sum(group.support_count > 0 for group in self.groups)

    def as_payload(self) -> dict[str, object]:
        """Return the stable persisted/API representation of this evidence.

        Persisting the dataclass field layout would leak implementation-only
        ``EffectiveGroupKey`` nesting into a restart-loaded Review result. The
        public payload records the descriptive cross-chain statistics exposed
        by the MERGE contract instead.
        """
        return {
            "cross_pair_count": self.cross_pair_count,
            "cross_available_counts_by_group": [
                {
                    "derivation_tag": group.key.derivation_tag,
                    "provenance_class": group.key.provenance_class.value,
                    "available_count": group.available_count,
                    "support_count": group.support_count,
                    "cross_fit": group.cross_fit,
                }
                for group in self.groups
            ],
            "cross_audit_edge_count": self.cross_audit_edge_count,
            "cross_audit_edge_coverage": self.cross_audit_edge_coverage,
            "cross_supported_group_count": self.cross_supported_group_count,
            "cross_evidence_union_coverage": self.cross_evidence_union_coverage,
        }


def exact_cross_chain_evidence(
    package: IngestedPackage,
    chain_a: str,
    chain_b: str,
    *,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    topology: TopologyGraph | None = None,
    resolver: ResourceResolver | None = None,
    delay_distribution: DelayDistribution | None = None,
    delay_threshold: float = DEFAULT_DELAY_THRESHOLD,
    d_max: int = DEFAULT_D_MAX,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
) -> CrossChainEvidence:
    """Return exact audit evidence over ``C_left x C_right``.

    The result identity is canonical and unordered.  The channel context is
    the union of both chains, matching the pair context a later merged-chain
    exact evaluation would use.  The inputs must have disjoint memberships:
    an overlapping membership is not a two-chain partition edit and is
    rejected rather than counted ambiguously.
    """
    if chain_a == chain_b:
        raise ValueError("cross-chain evidence requires two distinct chain ids")
    for chain_id in (chain_a, chain_b):
        if chain_id not in package.chains:
            raise KeyError(f"unknown chain_id {chain_id!r}")

    left_chain_id, right_chain_id = sorted((chain_a, chain_b))
    left_members = package.members_of(left_chain_id)
    right_members = package.members_of(right_chain_id)
    overlap = set(left_members).intersection(right_members)
    if overlap:
        raise ValueError(
            "cross-chain evidence requires disjoint memberships; overlapping "
            f"alarm ids: {sorted(overlap)!r}"
        )

    members = left_members + right_members
    alarms = [package.alarms[alarm_id] for alarm_id in members]
    segmentation = segment_bursts(alarms, silent_gap_seconds=silent_gap_seconds)
    if resolver is None:
        resolver = ResourceResolver.from_package(package)
    if topology is None and (package.topology.get("edges") or ()):
        topology = build_topology_graph(package, relation_types=PHYSICAL_RELATIONS)

    available_counts: dict[EffectiveGroupKey, int] = {}
    support_counts: dict[EffectiveGroupKey, int] = {}
    cross_audit_edge_count = 0
    union_pair_count = 0

    for left_alarm_id in left_members:
        for right_alarm_id in right_members:
            values = _evaluate_pair(
                package.alarms[left_alarm_id],
                package.alarms[right_alarm_id],
                taxonomy=taxonomy,
                segmentation=segmentation,
                topology=topology,
                resolver=resolver,
                delay_distribution=delay_distribution,
                delay_threshold=delay_threshold,
                d_max=d_max,
            )
            audit_eligible_groups = [
                group
                for group in build_derivation_groups(normalize_pair_channels(values))
                if group.audit_eligible
            ]
            supporting_groups = [
                group for group in audit_eligible_groups if group.supports
            ]

            for group in audit_eligible_groups:
                available_counts.setdefault(group.key, 0)
                support_counts.setdefault(group.key, 0)
                if group.availability:
                    available_counts[group.key] += 1
                if group.supports:
                    support_counts[group.key] += 1

            if supporting_groups:
                union_pair_count += 1
            if len(supporting_groups) >= 2:
                cross_audit_edge_count += 1

    group_keys = sorted(
        available_counts,
        key=lambda key: (
            key.derivation_tag,
            key.provenance_class.value,
            key.explain_eligible,
            key.role_eligible,
            key.audit_eligible,
        ),
    )
    groups = tuple(
        CrossGroupStatistics(
            key=key,
            available_count=available_counts[key],
            support_count=support_counts[key],
        )
        for key in group_keys
    )
    return CrossChainEvidence(
        left_chain_id=left_chain_id,
        right_chain_id=right_chain_id,
        cross_pair_count=len(left_members) * len(right_members),
        groups=groups,
        cross_audit_edge_count=cross_audit_edge_count,
        cross_evidence_union_pair_count=union_pair_count,
    )


__all__ = [
    "CrossChainEvidence",
    "CrossGroupStatistics",
    "exact_cross_chain_evidence",
]
