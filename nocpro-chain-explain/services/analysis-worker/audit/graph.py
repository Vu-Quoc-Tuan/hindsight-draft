"""The audit graph (§6, three-graph rule).

Three graph kinds must stay distinct:

    STATISTICAL     full counts, never sparsified
    VISUALIZATION    top-K, UI only
    AUDIT            |C| <= ~2k: full graph; larger: supernode/sparsifier

Audit **never** runs on the top-K visualization graph: a bridge or weak cut can
be an artifact of pruning rather than a real structural feature. This module
builds the AUDIT graph from ``w*_audit`` (group-level, audit-eligible only), which
is exactly the quantity :mod:`groups.roles`/:mod:`libs.provenance.derivation`
already define as ``G_audit``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from channels.base import ChannelValue
from libs.provenance import (
    DerivationGroup,
    NormalizedChannel,
    audit_groups,
    build_derivation_groups,
    normalize_pair_channels,
)

#: Above this member count, the audit graph must not be materialized exactly.
#: Matches groups.statistics.EXACT_STATISTICS_MAX_MEMBERS (§6's ~2k bound).
AUDIT_EXACT_MAX_MEMBERS = 2_000


@dataclass(frozen=True)
class AuditEdge:
    """One ``w*_audit`` edge between two members."""

    node_a: str
    node_b: str
    weight: float
    supporting_groups: tuple[str, ...]


@dataclass
class AuditGraph:
    """The exact audit graph for one chain (|C| <= AUDIT_EXACT_MAX_MEMBERS)."""

    members: tuple[str, ...]
    edges: tuple[AuditEdge, ...]
    adjacency: dict[str, dict[str, float]] = field(default_factory=dict)

    def weight(self, a: str, b: str) -> float:
        return self.adjacency.get(a, {}).get(b, 0.0)

    def neighbours(self, node: str) -> dict[str, float]:
        return self.adjacency.get(node, {})

    def volume(self, nodes: set[str]) -> float:
        """Sum of edge weights incident to ``nodes`` (both endpoints counted once
        for internal edges, matching standard conductance volume)."""
        total = 0.0
        for node in nodes:
            total += sum(self.adjacency.get(node, {}).values())
        return total


def _channel_representatives(values: list[ChannelValue]) -> list[NormalizedChannel]:
    """One :class:`NormalizedChannel` per channel verdict for this pair.

    Availability/support/score must be copied from the actual per-pair
    ``ChannelValue``: :class:`NormalizedChannel` defaults ``supports`` to
    ``False``, so building it from metadata alone (channel id/tag/provenance
    only) would make every group look non-supporting regardless of the real
    verdict.
    """
    return normalize_pair_channels(values)


def _pair_audit_groups(values: list[ChannelValue]) -> list[DerivationGroup]:
    """``G_audit(i,j)`` for one pair, built from that pair's channel verdicts.

    Reuses the same eligibility/homogeneity machinery as MembershipSupport
    (ADR-0009/0010), so a channel that is not audit-eligible can never make this
    pair's group set look supported.
    """
    groups = build_derivation_groups(_channel_representatives(values))
    return audit_groups(groups)


def build_audit_graph(
    members: list[str],
    pair_channel_values: dict[tuple[str, str], list[ChannelValue]],
) -> AuditGraph:
    """Build the exact audit graph from per-pair channel evaluations.

    ``pair_channel_values`` maps an unordered pair to the list of
    ``ChannelValue`` computed for it (the same values statistics accumulates
    from). Only audit-eligible, available groups contribute weight, and an edge
    exists only when at least one audit-eligible group supports the pair
    (mirrors the ``>= 2 distinct groups`` rule at the *audit-edge* level via
    ``w*_audit`` weighting, not by inventing a separate rule here).
    """
    edges: list[AuditEdge] = []
    adjacency: dict[str, dict[str, float]] = {m: {} for m in members}

    for (a, b), values in pair_channel_values.items():
        groups = _pair_audit_groups(values)
        supporting = [g for g in groups if g.supports]

        # "Audit edge <=> >= 2 DISTINCT AUDIT_ELIGIBLE derivation groups support."
        # This is the anti single-view-edge rule, not an independence proof
        # (distinct derivation != independent validation source).
        if len(supporting) < 2:
            continue

        # w*_audit(i,j) = sum(alpha_g * s_g+ * b_g) / sum(alpha_g), g in G_audit(i,j).
        # alpha_g = 1 (equal-weighted groups); explicit so a future weighting
        # scheme has one place to change.
        denominator = len(groups)
        numerator = sum(g.positive_score for g in supporting)
        weight = numerator / denominator

        edges.append(
            AuditEdge(
                node_a=a,
                node_b=b,
                weight=weight,
                supporting_groups=tuple(g.key.derivation_tag for g in supporting),
            )
        )
        adjacency.setdefault(a, {})[b] = weight
        adjacency.setdefault(b, {})[a] = weight

    return AuditGraph(members=tuple(members), edges=tuple(edges), adjacency=adjacency)
