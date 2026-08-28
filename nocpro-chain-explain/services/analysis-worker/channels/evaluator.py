"""Per-chain channel evaluation (Tier-1B, §4A scope).

Two outputs with different guarantees:

``statistics``
    Exact counts over the **full** pair space, accumulated in a streaming pass.
    ``Fit_k``/``Fit_g``/``MembershipSupport``/role read from here, so a verdict is
    never a function of a display budget (§6 three-graph rule).

``matrix``
    Bounded pair detail for WHY drill-down and visualization, capped by
    ``pair_detail_limit``. Truncation is reported, never silent.

ADR-0015 prohibits unguarded pair *materialization*. Streaming aggregation keeps
memory at O(members x channels), so exact statistics remain available well beyond
the detail cap. Past :data:`EXACT_STATISTICS_MAX_MEMBERS` the statistics are
marked non-exact so the caller must choose an explicit policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedPackage

from groups.statistics import (
    EXACT_STATISTICS_MAX_MEMBERS,
    ChannelStatistics,
    pair_iterator,
    statistics_are_exact,
)

from .base import ChannelValue
from .pair_detail import PairChannelMatrix
from .dependency import (
    DEFAULT_D_MAX,
    PHYSICAL_RELATIONS,
    ResourceResolver,
    TopologyGraph,
    build_topology_graph,
    evaluate_dep_hop_channel,
)
from .entity import evaluate_entity_channels
from .semantic import EMPTY_TAXONOMY, AlarmTaxonomy, evaluate_semantic_channel
from .temporal import (
    DEFAULT_SILENT_GAP_SECONDS,
    BurstSegmentation,
    DelayDistribution,
    evaluate_burst_channel,
    evaluate_delay_channel,
    segment_bursts,
)

#: Default cap on **stored pair detail**, not on statistics.
DEFAULT_PAIR_DETAIL_LIMIT = 20_000

#: Default T_delay threshold; typicality is in [0,1].
DEFAULT_DELAY_THRESHOLD = 0.5


@dataclass
class ChainEvidence:
    """Materialized evidence for one chain."""

    chain_id: str
    members: list[str]
    #: Bounded pair detail (visualization / WHY drill-down).
    matrix: PairChannelMatrix
    #: Exact counts over the full pair space (statistical truth).
    statistics: ChannelStatistics
    burst_segmentation: BurstSegmentation
    #: Pairs stored in ``matrix``.
    detail_pairs: int
    #: True when pair *detail* was capped. Statistics remain exact.
    detail_truncated: bool
    pair_detail_limit: int

    @property
    def full_pair_space(self) -> int:
        n = len(self.members)
        return n * (n - 1) // 2

    @property
    def statistics_exact(self) -> bool:
        return self.statistics.exact

    @property
    def detail_coverage(self) -> float:
        total = self.full_pair_space
        return self.detail_pairs / total if total else 0.0


def evaluate_chain_channels(
    package: IngestedPackage,
    chain_id: str,
    *,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    topology: TopologyGraph | None = None,
    resolver: ResourceResolver | None = None,
    delay_distribution: DelayDistribution | None = None,
    delay_threshold: float = DEFAULT_DELAY_THRESHOLD,
    d_max: int = DEFAULT_D_MAX,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
    pair_detail_limit: int = DEFAULT_PAIR_DETAIL_LIMIT,
) -> ChainEvidence:
    """Evaluate all ``K_pair`` channels for one chain."""
    alarms = package.alarms_of(chain_id)
    members = [a.alarm_id for a in alarms]
    by_id = {a.alarm_id: a for a in alarms}

    segmentation = segment_bursts(alarms, silent_gap_seconds=silent_gap_seconds)
    if resolver is None:
        resolver = ResourceResolver.from_package(package)
    if topology is None and (package.topology.get("edges") or ()):
        topology = build_topology_graph(package, relation_types=PHYSICAL_RELATIONS)

    exact = statistics_are_exact(len(members))
    statistics = ChannelStatistics(
        chain_id=chain_id, members=tuple(members), exact=exact
    )
    matrix = PairChannelMatrix()
    detail_pairs = 0
    detail_truncated = False

    if not exact:
        # Fail loudly rather than quietly computing statistics from a subset.
        # The caller must apply a supernode/sparsifier policy (§6).
        return ChainEvidence(
            chain_id=chain_id,
            members=members,
            matrix=matrix,
            statistics=statistics,
            burst_segmentation=segmentation,
            detail_pairs=0,
            detail_truncated=True,
            pair_detail_limit=pair_detail_limit,
        )

    for alarm_a, alarm_b in pair_iterator(members):
        left, right = by_id[alarm_a], by_id[alarm_b]
        values = _evaluate_pair(
            left,
            right,
            taxonomy=taxonomy,
            segmentation=segmentation,
            topology=topology,
            resolver=resolver,
            delay_distribution=delay_distribution,
            delay_threshold=delay_threshold,
            d_max=d_max,
        )

        # Statistics always see every pair.
        statistics.record(alarm_a, alarm_b, values)
        statistics.pairs_counted += 1

        # Pair detail is what the cap limits.
        if detail_pairs < pair_detail_limit:
            matrix.add(alarm_a, alarm_b, values)
            detail_pairs += 1
        else:
            detail_truncated = True

    return ChainEvidence(
        chain_id=chain_id,
        members=members,
        matrix=matrix,
        statistics=statistics,
        burst_segmentation=segmentation,
        detail_pairs=detail_pairs,
        detail_truncated=detail_truncated,
        pair_detail_limit=pair_detail_limit,
    )


def _evaluate_pair(
    left,
    right,
    *,
    taxonomy: AlarmTaxonomy,
    segmentation: BurstSegmentation,
    topology: TopologyGraph | None,
    resolver: ResourceResolver,
    delay_distribution: DelayDistribution | None,
    delay_threshold: float,
    d_max: int,
) -> list[ChannelValue]:
    """Evaluate one pair using the canonical channel implementations."""
    values: list[ChannelValue] = evaluate_entity_channels(left, right)
    values.append(evaluate_semantic_channel(left, right, taxonomy))
    values.append(evaluate_burst_channel(left, right, segmentation))
    values.append(
        evaluate_delay_channel(
            left, right, distribution=delay_distribution, threshold=delay_threshold
        )
    )
    values.append(
        evaluate_dep_hop_channel(
            left, right, graph=topology, resolver=resolver, d_max=d_max
        )
    )
    return values


def evaluate_pair_channels(
    package: IngestedPackage,
    chain_id: str,
    alarm_a: str,
    alarm_b: str,
    *,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    topology: TopologyGraph | None = None,
    resolver: ResourceResolver | None = None,
    delay_distribution: DelayDistribution | None = None,
    delay_threshold: float = DEFAULT_DELAY_THRESHOLD,
    d_max: int = DEFAULT_D_MAX,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
) -> list[ChannelValue]:
    """Evaluate the full WHY detail for one explicitly requested chain pair."""
    members = set(package.members_of(chain_id))
    for alarm_id in (alarm_a, alarm_b):
        if alarm_id not in members or alarm_id not in package.alarms:
            raise KeyError(f"alarm {alarm_id!r} is not a member of chain {chain_id!r}")
    if alarm_a == alarm_b:
        raise ValueError("pair endpoints must be distinct")

    alarms = package.alarms_of(chain_id)
    segmentation = segment_bursts(alarms, silent_gap_seconds=silent_gap_seconds)
    if resolver is None:
        resolver = ResourceResolver.from_package(package)
    if topology is None and (package.topology.get("edges") or ()):
        topology = build_topology_graph(package, relation_types=PHYSICAL_RELATIONS)
    return _evaluate_pair(
        package.alarms[alarm_a],
        package.alarms[alarm_b],
        taxonomy=taxonomy,
        segmentation=segmentation,
        topology=topology,
        resolver=resolver,
        delay_distribution=delay_distribution,
        delay_threshold=delay_threshold,
        d_max=d_max,
    )


__all__ = [
    "DEFAULT_DELAY_THRESHOLD",
    "DEFAULT_PAIR_DETAIL_LIMIT",
    "EXACT_STATISTICS_MAX_MEMBERS",
    "ChainEvidence",
    "evaluate_chain_channels",
    "evaluate_pair_channels",
]
