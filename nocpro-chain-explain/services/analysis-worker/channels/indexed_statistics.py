"""Semantics-preserving indexed providers for Tier-1 channel statistics."""

from __future__ import annotations

import bisect
from collections import Counter
from datetime import datetime

from libs.contracts import IngestedAlarm, IngestedPackage
from libs.provenance import ProvenanceClass, ProvenanceSubtype

from groups.indexed_statistics import (
    ChannelFitFromIndex,
    IndexedChainStatistics,
    NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH,
    StatisticsMode,
    SupportIndexSemantics,
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


def _get_alarm_timestamp(alarm: IngestedAlarm) -> float | None:
    time_str = (
        getattr(alarm, "canonical_start_time", None)
        or alarm.raw.get("canonical_start_time")
        or alarm.raw.get("cah.start_time")
    )
    if not time_str:
        return None
    try:
        dt = datetime.fromisoformat(str(time_str).replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None


def _add_temporal_delay_statistics(
    alarms: list[IngestedAlarm],
    positions: dict[str, int],
    statistics: IndexedChainStatistics,
    *,
    delay_window_seconds: float | None,
) -> None:
    delay_channel = "T_delay"
    delay_tag = "temporal_delay"
    statistics.channel_meta[delay_channel] = (
        delay_tag,
        ProvenanceClass.POST_HOC,
        None,
    )
    if delay_window_seconds is None:
        for alarm in alarms:
            statistics.fits[(alarm.alarm_id, delay_channel)] = ChannelFitFromIndex(
                channel_id=delay_channel,
                derivation_tag=delay_tag,
                provenance_class=ProvenanceClass.POST_HOC,
                fit=None,
                domain_size=0,
                supporting=0,
                unavailable_reason=NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH,
            )
            statistics.support_peer_bitmaps[(alarm.alarm_id, delay_channel)] = 0
        return

    alarm_ts: list[tuple[str, float]] = []
    unparseable: set[str] = set()
    for alarm in alarms:
        ts = _get_alarm_timestamp(alarm)
        if ts is not None:
            alarm_ts.append((alarm.alarm_id, ts))
        else:
            unparseable.add(alarm.alarm_id)

    valid_count = len(alarm_ts)
    domain_size = valid_count - 1 if valid_count > 1 else 0

    for alarm_id in unparseable:
        statistics.fits[(alarm_id, delay_channel)] = ChannelFitFromIndex(
            channel_id=delay_channel,
            derivation_tag=delay_tag,
            provenance_class=ProvenanceClass.POST_HOC,
            fit=None,
            domain_size=0,
            supporting=0,
            unavailable_reason="UNPARSEABLE_TIMESTAMP",
        )
        statistics.support_peer_bitmaps[(alarm_id, delay_channel)] = 0

    if valid_count <= 1:
        for alarm_id, _ in alarm_ts:
            statistics.fits[(alarm_id, delay_channel)] = ChannelFitFromIndex(
                channel_id=delay_channel,
                derivation_tag=delay_tag,
                provenance_class=ProvenanceClass.POST_HOC,
                fit=None,
                domain_size=0,
                supporting=0,
            )
            statistics.support_peer_bitmaps[(alarm_id, delay_channel)] = 0
        return

    # Small chains (N <= 200): direct pairwise comparison O(N^2)
    # Large chains (N > 200): sorted sliding window with bisect O(N log N)
    if valid_count <= 200:
        for i, (alarm_id_i, ts_i) in enumerate(alarm_ts):
            peer_bitmap = 0
            supporting = 0
            for j, (alarm_id_j, ts_j) in enumerate(alarm_ts):
                if i == j:
                    continue
                if abs(ts_j - ts_i) <= delay_window_seconds:
                    supporting += 1
                    peer_bitmap |= (1 << positions[alarm_id_j])

            statistics.fits[(alarm_id_i, delay_channel)] = _entry(
                channel_id=delay_channel,
                derivation_tag=delay_tag,
                provenance_class=ProvenanceClass.POST_HOC,
                domain_size=domain_size,
                supporting=supporting,
            )
            statistics.support_peer_bitmaps[(alarm_id_i, delay_channel)] = peer_bitmap
    else:
        sorted_items = sorted(alarm_ts, key=lambda item: item[1])
        timestamps = [item[1] for item in sorted_items]

        for alarm_id_i, ts_i in sorted_items:
            left_idx = bisect.bisect_left(timestamps, ts_i - delay_window_seconds)
            right_idx = bisect.bisect_right(timestamps, ts_i + delay_window_seconds)

            peer_bitmap = 0
            supporting = 0
            for k in range(left_idx, right_idx):
                other_id, _ = sorted_items[k]
                if other_id != alarm_id_i:
                    supporting += 1
                    peer_bitmap |= (1 << positions[other_id])

            statistics.fits[(alarm_id_i, delay_channel)] = _entry(
                channel_id=delay_channel,
                derivation_tag=delay_tag,
                provenance_class=ProvenanceClass.POST_HOC,
                domain_size=domain_size,
                supporting=supporting,
            )
            statistics.support_peer_bitmaps[(alarm_id_i, delay_channel)] = peer_bitmap


def build_indexed_statistics(
    package: IngestedPackage,
    chain_id: str,
    *,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
    delay_window_seconds: float | None = None,
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
    positions = {alarm.alarm_id: index for index, alarm in enumerate(alarms)}

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

        group_bitmaps = {
            key: sum(1 << positions[alarm_id] for alarm_id in alarm_ids)
            for key, alarm_ids in groups.items()
        }

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
            peer_bitmap = (
                group_bitmaps[values[alarm.alarm_id]]
                & ~(1 << positions[alarm.alarm_id])
                if alarm.alarm_id in available
                else 0
            )
            statistics.support_peer_bitmaps[(alarm.alarm_id, channel_id)] = peer_bitmap

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
    burst_bitmaps: dict[str, int] = {}
    for alarm_id, burst_id in segmentation.burst_of.items():
        burst_bitmaps[burst_id] = (
            burst_bitmaps.get(burst_id, 0) | (1 << positions[alarm_id])
        )
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
        peer_bitmap = (
            burst_bitmaps[burst_id] & ~(1 << positions[alarm.alarm_id])
            if burst_id is not None
            else 0
        )
        statistics.support_peer_bitmaps[(alarm.alarm_id, burst_channel)] = peer_bitmap

    _add_temporal_delay_statistics(
        alarms,
        positions,
        statistics,
        delay_window_seconds=delay_window_seconds,
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
    # All providers above emit unordered pair support symmetrically. Consumers
    # require this explicit construction contract rather than assuming it.
    statistics.support_index_semantics = (
        SupportIndexSemantics.SYMMETRIC_UNORDERED_PAIRS_V1
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
        for channel_id, bitmap in index.support_bitmaps_for(alarm):
            statistics.support_peer_bitmaps[(alarm.alarm_id, channel_id)] = bitmap


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
    positions = {alarm.alarm_id: index for index, alarm in enumerate(alarms)}
    alarms_per_resource = Counter(
        resource for resource in resources.values() if resource is not None
    )
    resource_bitmaps: dict[str, int] = {}
    for alarm_id, resource in resources.items():
        if resource is not None:
            resource_bitmaps[resource] = (
                resource_bitmaps.get(resource, 0) | (1 << positions[alarm_id])
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
        peer_bitmap = 0
        if resource is not None and graph.adjacency:
            for reachable_resource in neighbourhoods[resource]:
                peer_bitmap |= resource_bitmaps.get(reachable_resource, 0)
            peer_bitmap &= ~(1 << positions[alarm.alarm_id])
        statistics.support_peer_bitmaps[(alarm.alarm_id, channel_id)] = peer_bitmap
