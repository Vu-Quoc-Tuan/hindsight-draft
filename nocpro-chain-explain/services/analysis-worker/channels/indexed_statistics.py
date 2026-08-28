"""Semantics-preserving indexed providers for Tier-1 channel statistics."""

from __future__ import annotations

from collections import Counter

from libs.contracts import IngestedAlarm, IngestedPackage
from libs.provenance import ProvenanceClass, ProvenanceSubtype

from groups.indexed_statistics import (
    ChannelFitFromIndex,
    IndexedChainStatistics,
    StatisticsMode,
)

from .semantic import EMPTY_TAXONOMY, AlarmTaxonomy
from .temporal import DEFAULT_SILENT_GAP_SECONDS, segment_bursts
from .common_dependency import DEFAULT_LAMBDA_DEP, DEFAULT_THETA_CD
from .dep_upstream_index import DepUpstreamFitIndex
from .dependency import (
    DEFAULT_D_MAX,
    PHYSICAL_RELATIONS,
    ResourceResolver,
    TopologyGraph,
    build_topology_graph,
)


EQUALITY_CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("E_reference", "reference", "node_reference"),
    ("E_device", "device", "device_code"),
    ("E_card", "card", "component"),
    ("E_site", "site", "location_code"),
    ("E_remote", "remote", "remote_node"),
    ("S", "semantic", "alarm_name"),
)


def read_indexed_field(alarm: IngestedAlarm, field_name: str) -> str | None:
    value = getattr(alarm, field_name, None)
    if value is None:
        value = alarm.raw.get(field_name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def semantic_group_key(value: str, taxonomy: AlarmTaxonomy) -> str:
    family = taxonomy.family_of(value)
    return f"FAMILY:{family}" if family is not None else f"NAME:{value}"


def _entry(
    *,
    channel_id: str,
    derivation_tag: str,
    provenance_class: ProvenanceClass,
    domain_size: int,
    supporting: int,
) -> ChannelFitFromIndex:
    return ChannelFitFromIndex(
        channel_id=channel_id,
        derivation_tag=derivation_tag,
        provenance_class=provenance_class,
        fit=supporting / domain_size if domain_size else None,
        domain_size=domain_size,
        supporting=supporting,
    )


def build_indexed_statistics(
    package: IngestedPackage,
    chain_id: str,
    *,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
    d_max: int = DEFAULT_D_MAX,
    lambda_dep: float = DEFAULT_LAMBDA_DEP,
    common_dependency_threshold: float = DEFAULT_THETA_CD,
) -> IndexedChainStatistics:
    """Build exact statistics for available indexed channels without pair scans."""
    alarms = package.alarms_of(chain_id)
    statistics = IndexedChainStatistics(
        chain_id=chain_id,
        members=tuple(alarm.alarm_id for alarm in alarms),
        statistics_mode=StatisticsMode.EXACT_INDEXED,
    )

    for channel_id, tag, field in EQUALITY_CHANNELS:
        statistics.channel_meta[channel_id] = (tag, ProvenanceClass.POST_HOC, None)
        groups: dict[str, list[str]] = {}
        available: set[str] = set()
        values: dict[str, str] = {}
        for alarm in alarms:
            value = read_indexed_field(alarm, field)
            if value is None:
                continue
            key = semantic_group_key(value, taxonomy) if channel_id == "S" else value
            values[alarm.alarm_id] = key
            available.add(alarm.alarm_id)
            groups.setdefault(key, []).append(alarm.alarm_id)

        for alarm in alarms:
            if alarm.alarm_id not in available:
                domain = supporting = 0
            else:
                domain = len(available) - 1
                supporting = len(groups[values[alarm.alarm_id]]) - 1
            statistics.fits[(alarm.alarm_id, channel_id)] = _entry(
                channel_id=channel_id,
                derivation_tag=tag,
                provenance_class=ProvenanceClass.POST_HOC,
                domain_size=domain,
                supporting=supporting,
            )

    burst_channel = "T_burst"
    burst_tag = "temporal_burst"
    statistics.channel_meta[burst_channel] = (
        burst_tag,
        ProvenanceClass.POST_HOC,
        None,
    )
    segmentation = segment_bursts(alarms, silent_gap_seconds=silent_gap_seconds)
    burst_groups: dict[str, int] = {}
    for burst_id in segmentation.burst_of.values():
        burst_groups[burst_id] = burst_groups.get(burst_id, 0) + 1
    burst_domain = len(segmentation.burst_of)
    for alarm in alarms:
        burst_id = segmentation.burst_of.get(alarm.alarm_id)
        domain = burst_domain - 1 if burst_id is not None else 0
        supporting = burst_groups[burst_id] - 1 if burst_id is not None else 0
        statistics.fits[(alarm.alarm_id, burst_channel)] = _entry(
            channel_id=burst_channel,
            derivation_tag=burst_tag,
            provenance_class=ProvenanceClass.POST_HOC,
            domain_size=domain,
            supporting=supporting,
        )

    statistics.channel_meta["T_delay"] = (
        "temporal_delay",
        ProvenanceClass.POST_HOC,
        None,
    )
    for alarm in alarms:
        statistics.fits[(alarm.alarm_id, "T_delay")] = _entry(
            channel_id="T_delay",
            derivation_tag="temporal_delay",
            provenance_class=ProvenanceClass.POST_HOC,
            domain_size=0,
            supporting=0,
        )

    _add_dep_hop_statistics(
        package,
        alarms,
        statistics,
        d_max=d_max,
    )
    _add_dep_upstream_statistics(
        package,
        alarms,
        statistics,
        lambda_dep=lambda_dep,
        theta=common_dependency_threshold,
    )
    return statistics


def _add_dep_upstream_statistics(
    package: IngestedPackage,
    alarms: list[IngestedAlarm],
    statistics: IndexedChainStatistics,
    *,
    lambda_dep: float,
    theta: float,
) -> None:
    index = DepUpstreamFitIndex(
        package,
        alarms,
        lambda_dep=lambda_dep,
        theta=theta,
    )
    statistics.channel_meta.update(index.channel_meta)
    for alarm in alarms:
        for entry in index.fits_for(alarm):
            statistics.fits[(alarm.alarm_id, entry.channel_id)] = entry


def _add_dep_hop_statistics(
    package: IngestedPackage,
    alarms: list[IngestedAlarm],
    statistics: IndexedChainStatistics,
    *,
    d_max: int,
) -> None:
    """Exact Dep_hop Fit from bounded topology neighbourhood postings."""
    channel_id = "Dep_hop"
    tag = "dependency_hop"
    graph = build_topology_graph(package, relation_types=PHYSICAL_RELATIONS)
    resolver = ResourceResolver.from_package(package)
    statistics.channel_meta[channel_id] = (
        tag,
        graph.provenance_class,
        graph.provenance_subtype,
    )

    resources = {
        alarm.alarm_id: resolver.resource_of(alarm.alarm_id) for alarm in alarms
    }
    alarms_per_resource = Counter(
        resource for resource in resources.values() if resource is not None
    )
    neighbourhoods: dict[str, set[str]] = {}
    if graph.adjacency:
        neighbourhoods = {
            resource: graph.reachable_within(resource, max_depth=d_max)
            for resource in alarms_per_resource
        }

    for alarm in alarms:
        resource = resources[alarm.alarm_id]
        if resource is None or not graph.adjacency:
            domain = supporting = 0
        else:
            domain = sum(
                alarms_per_resource[candidate]
                for candidate in neighbourhoods[resource]
            ) - 1
            # Every available pair has d<=D_max and therefore clears the
            # channel threshold 1/(1+D_max), exactly as the oracle does.
            supporting = domain
        statistics.fits[(alarm.alarm_id, channel_id)] = _entry(
            channel_id=channel_id,
            derivation_tag=tag,
            provenance_class=graph.provenance_class,
            domain_size=domain,
            supporting=supporting,
        )
