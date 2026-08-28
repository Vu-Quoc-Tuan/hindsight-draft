"""Indexed hypothetical Fit queries for contrastive rival chains."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from libs.contracts import IngestedAlarm, IngestedPackage
from libs.provenance import ProvenanceClass

from groups.fit import GroupFit
from groups.fit_from_index import group_fits_from_index
from groups.indexed_statistics import (
    AuditGraphMode,
    ChannelFitFromIndex,
    IndexedChainStatistics,
    PairMaterializationMode,
    StatisticsMode,
)

from .indexed_statistics import read_indexed_field
from .semantic import EMPTY_TAXONOMY, AlarmTaxonomy
from .temporal import DEFAULT_SILENT_GAP_SECONDS, context_key
from .dependency import (
    DEFAULT_D_MAX,
    PHYSICAL_RELATIONS,
    ResourceResolver,
    TopologyGraph,
    build_topology_graph,
)


EQUALITY_CHANNELS = (
    ("E_reference", "reference", "node_reference"),
    ("E_device", "device", "device_code"),
    ("E_card", "card", "component"),
    ("E_site", "site", "location_code"),
    ("E_remote", "remote", "remote_node"),
    ("S", "semantic", "alarm_name"),
)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class _BurstPosting:
    times: tuple[datetime, ...]
    run_ids: tuple[int, ...]
    run_sizes: dict[int, int]


class RivalFitIndex:
    """Reusable exact lookups for ``Fit_g(x, C')`` without pair enumeration."""

    def __init__(
        self,
        *,
        chain_id: str,
        peers: list[IngestedAlarm],
        taxonomy: AlarmTaxonomy,
        silent_gap_seconds: int,
        graph: TopologyGraph,
        resolver: ResourceResolver,
        d_max: int,
    ) -> None:
        self.chain_id = chain_id
        self.taxonomy = taxonomy
        self.silent_gap_seconds = silent_gap_seconds
        self.graph = graph
        self.resolver = resolver
        self.d_max = d_max
        self._peer_ids = {alarm.alarm_id for alarm in peers}
        self._domains: dict[str, int] = {}
        self._groups: dict[str, Counter[str]] = {}

        for channel_id, _, field_name in EQUALITY_CHANNELS:
            counts: Counter[str] = Counter()
            domain = 0
            for alarm in peers:
                value = read_indexed_field(alarm, field_name)
                if value is None:
                    continue
                domain += 1
                counts[self._group_key(channel_id, value)] += 1
            self._domains[channel_id] = domain
            self._groups[channel_id] = counts

        by_context: dict[str, list[datetime]] = {}
        for alarm in peers:
            key = context_key(alarm, ("location_code", "device_code"))
            start = _parse(alarm.canonical_start_time)
            if key is not None and start is not None:
                by_context.setdefault(key, []).append(start)
        self._burst_domain = sum(len(times) for times in by_context.values())
        self._burst_postings = {
            key: self._build_burst_posting(times)
            for key, times in by_context.items()
        }
        self._resource_counts: Counter[str] = Counter(
            resource
            for alarm in peers
            if (resource := resolver.resource_of(alarm.alarm_id)) is not None
        )
        self._dep_neighbourhoods = (
            {
                resource: graph.reachable_within(resource, max_depth=d_max)
                for resource in self._resource_counts
            }
            if graph.adjacency
            else {}
        )

    @classmethod
    def from_chain(
        cls,
        package: IngestedPackage,
        chain_id: str,
        *,
        taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
        silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
        d_max: int = DEFAULT_D_MAX,
    ) -> "RivalFitIndex":
        if chain_id not in package.chains:
            raise KeyError(f"unknown rival chain_id {chain_id!r}")
        return cls(
            chain_id=chain_id,
            peers=package.alarms_of(chain_id),
            taxonomy=taxonomy,
            silent_gap_seconds=silent_gap_seconds,
            graph=build_topology_graph(package, relation_types=PHYSICAL_RELATIONS),
            resolver=ResourceResolver.from_package(package),
            d_max=d_max,
        )

    def _group_key(self, channel_id: str, value: str) -> str:
        if channel_id != "S":
            return value
        family = self.taxonomy.family_of(value)
        return f"FAMILY:{family}" if family is not None else f"NAME:{value}"

    def _build_burst_posting(self, times: list[datetime]) -> _BurstPosting:
        ordered = sorted(times)
        run_ids: list[int] = []
        run_sizes: Counter[int] = Counter()
        run_id = 0
        previous: datetime | None = None
        for start in ordered:
            if previous is not None:
                gap = (start - previous).total_seconds()
                if gap > self.silent_gap_seconds:
                    run_id += 1
            run_ids.append(run_id)
            run_sizes[run_id] += 1
            previous = start
        return _BurstPosting(tuple(ordered), tuple(run_ids), dict(run_sizes))

    def _channel_fit(
        self, alarm: IngestedAlarm, channel_id: str, derivation_tag: str, field: str
    ) -> ChannelFitFromIndex:
        value = read_indexed_field(alarm, field)
        domain = self._domains[channel_id] if value is not None else 0
        supporting = (
            self._groups[channel_id][self._group_key(channel_id, value)]
            if value is not None
            else 0
        )
        return ChannelFitFromIndex(
            channel_id=channel_id,
            derivation_tag=derivation_tag,
            provenance_class=ProvenanceClass.POST_HOC,
            fit=supporting / domain if domain else None,
            domain_size=domain,
            supporting=supporting,
        )

    def _burst_fit(self, alarm: IngestedAlarm) -> ChannelFitFromIndex:
        key = context_key(alarm, ("location_code", "device_code"))
        start = _parse(alarm.canonical_start_time)
        supporting = 0
        if key is not None and start is not None:
            posting = self._burst_postings.get(key)
            if posting is not None:
                position = bisect_left(posting.times, start)
                connected_runs: set[int] = set()
                if position > 0:
                    left = posting.times[position - 1]
                    if (start - left).total_seconds() <= self.silent_gap_seconds:
                        connected_runs.add(posting.run_ids[position - 1])
                if position < len(posting.times):
                    right = posting.times[position]
                    if (right - start).total_seconds() <= self.silent_gap_seconds:
                        connected_runs.add(posting.run_ids[position])
                supporting = sum(posting.run_sizes[run] for run in connected_runs)
        domain = self._burst_domain if key is not None and start is not None else 0
        return ChannelFitFromIndex(
            channel_id="T_burst",
            derivation_tag="temporal_burst",
            provenance_class=ProvenanceClass.POST_HOC,
            fit=supporting / domain if domain else None,
            domain_size=domain,
            supporting=supporting,
        )

    def _dep_fit(self, alarm: IngestedAlarm) -> ChannelFitFromIndex:
        resource = self.resolver.resource_of(alarm.alarm_id)
        domain = 0
        if resource is not None and self.graph.adjacency:
            neighbourhood = self._dep_neighbourhoods.get(
                resource
            ) or self.graph.reachable_within(
                resource, max_depth=self.d_max
            )
            domain = sum(self._resource_counts[item] for item in neighbourhood)
            if alarm.alarm_id in self._peer_ids:
                domain -= 1
        return ChannelFitFromIndex(
            channel_id="Dep_hop",
            derivation_tag="dependency_hop",
            provenance_class=self.graph.provenance_class,
            fit=1.0 if domain else None,
            domain_size=domain,
            supporting=domain,
        )

    def group_fits_for(self, alarm: IngestedAlarm) -> tuple[GroupFit, ...]:
        statistics = IndexedChainStatistics(
            chain_id=self.chain_id,
            members=(alarm.alarm_id,),
            statistics_mode=StatisticsMode.EXACT_INDEXED,
            audit_graph_mode=AuditGraphMode.NOT_COMPUTED,
            pair_materialization=PairMaterializationMode.ON_DEMAND,
        )
        for channel_id, tag, field in EQUALITY_CHANNELS:
            statistics.channel_meta[channel_id] = (
                tag,
                ProvenanceClass.POST_HOC,
                None,
            )
            statistics.fits[(alarm.alarm_id, channel_id)] = self._channel_fit(
                alarm, channel_id, tag, field
            )
        statistics.channel_meta["T_burst"] = (
            "temporal_burst",
            ProvenanceClass.POST_HOC,
            None,
        )
        statistics.fits[(alarm.alarm_id, "T_burst")] = self._burst_fit(alarm)
        statistics.channel_meta["T_delay"] = (
            "temporal_delay",
            ProvenanceClass.POST_HOC,
            None,
        )
        statistics.fits[(alarm.alarm_id, "T_delay")] = ChannelFitFromIndex(
            channel_id="T_delay",
            derivation_tag="temporal_delay",
            provenance_class=ProvenanceClass.POST_HOC,
            fit=None,
            domain_size=0,
            supporting=0,
        )
        statistics.channel_meta["Dep_hop"] = (
            "dependency_hop",
            self.graph.provenance_class,
            self.graph.provenance_subtype,
        )
        statistics.fits[(alarm.alarm_id, "Dep_hop")] = self._dep_fit(alarm)
        return tuple(group_fits_from_index(alarm.alarm_id, statistics))
