"""Semantics-preserving indexed providers for Tier-1 channel statistics."""

from __future__ import annotations

from libs.contracts import IngestedAlarm, IngestedPackage
from libs.provenance import ProvenanceClass, ProvenanceSubtype

from groups.indexed_statistics import (
    ChannelFitFromIndex,
    IndexedChainStatistics,
    StatisticsMode,
)

from .semantic import EMPTY_TAXONOMY, AlarmTaxonomy
from .temporal import DEFAULT_SILENT_GAP_SECONDS, segment_bursts


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

    for channel_id, tag, provenance in (
        ("T_delay", "temporal_delay", ProvenanceClass.POST_HOC),
        ("Dep_hop", "dependency_hop", ProvenanceClass.EXTERNAL_OPERATIONAL),
    ):
        statistics.channel_meta[channel_id] = (
            tag,
            provenance,
            ProvenanceSubtype.TOPOLOGY_EXTERNAL if channel_id == "Dep_hop" else None,
        )
        for alarm in alarms:
            statistics.fits[(alarm.alarm_id, channel_id)] = _entry(
                channel_id=channel_id,
                derivation_tag=tag,
                provenance_class=provenance,
                domain_size=0,
                supporting=0,
            )
    return statistics
