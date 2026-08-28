"""Indexed sufficient statistics (§11, execution contract v2).

Computes exact ``Fit_k``/``Fit_g``/``MembershipSupport`` from **indexed/grouped
counts** without materializing the full C(n,2) pair graph. This is what makes
Tier-1A/1B viable for chains with hundreds or thousands of members.

Strategy per channel family (§11 "chiến lược tính toán"):

    E_reference / E_device / E_site / E_remote / S
        hash group-by → group size → Fit_k(x) = (group_size - 1) / (domain - 1)
        Domain = members with the field available.

    T_burst
        contextual segmentation → burst membership → burst size
        Fit_burst(x) = (burst_size - 1) / (domain - 1) where domain = members
        with a resolved burst assignment.

    T_delay
        UNAVAILABLE without a fitted distribution; not indexed here.

    Dep_hop
        topology index → bounded BFS neighborhood → intersect with chain members.
        Exact only when mapping + topology is available; else UNAVAILABLE.

    Dep_upstream (CommonDependency)
        ancestor/path inverted index → not indexed per-pair here; UNAVAILABLE
        in Tier-1A statistics and evaluated on-demand in Tier-1B/2.

The key insight: for equality-based channels, ``Fit_k(x, C)`` simplifies to:

    D_k(x, C) = { y in C\\{x} : both x and y have the field available }
    supporting(x) = { y in D_k : field(x) == field(y) }
    Fit_k(x, C) = |supporting(x)| / |D_k(x, C)|

which can be computed from group sizes alone, no pair enumeration needed.

Three fidelity flags replace the old ``statistics_exact: bool``:

    statistics_mode:      EXACT_INDEXED | APPROXIMATED | UNAVAILABLE
    audit_graph_mode:     NOT_COMPUTED | EXACT_FULL | SPARSIFIED | SUPERNODE
    pair_materialization: ON_DEMAND | BOUNDED | TRUNCATED
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from libs.contracts import IngestedAlarm, IngestedPackage
from libs.provenance import ProvenanceClass

from channels.temporal import (
    DEFAULT_SILENT_GAP_SECONDS,
    BurstSegmentation,
    context_key,
    segment_bursts,
)


class StatisticsMode(str, Enum):
    EXACT_INDEXED = "EXACT_INDEXED"
    APPROXIMATED = "APPROXIMATED"
    UNAVAILABLE = "UNAVAILABLE"


class AuditGraphMode(str, Enum):
    NOT_COMPUTED = "NOT_COMPUTED"
    EXACT_FULL = "EXACT_FULL"
    SPARSIFIED = "SPARSIFIED"
    SUPERNODE = "SUPERNODE"


class PairMaterializationMode(str, Enum):
    ON_DEMAND = "ON_DEMAND"
    BOUNDED = "BOUNDED"
    TRUNCATED = "TRUNCATED"


@dataclass(frozen=True)
class ChannelFitFromIndex:
    """``Fit_k(x, C)`` computed from grouped counts, not pair iteration."""

    channel_id: str
    derivation_tag: str
    provenance_class: ProvenanceClass
    fit: float | None
    domain_size: int
    supporting: int

    @property
    def is_unavailable(self) -> bool:
        return self.fit is None


@dataclass
class IndexedChainStatistics:
    """Sufficient statistics for one chain, from indexed/grouped counts.

    This replaces the old ``ChannelStatistics`` (which streamed over all pairs)
    for the purpose of computing Fit/MembershipSupport/role. The old streaming
    approach remains valid as a reference/correctness check for small chains,
    but is never the production path for chains above ~50 members.
    """

    chain_id: str
    members: tuple[str, ...]
    statistics_mode: StatisticsMode
    audit_graph_mode: AuditGraphMode = AuditGraphMode.NOT_COMPUTED
    pair_materialization: PairMaterializationMode = PairMaterializationMode.ON_DEMAND

    #: Per-member, per-channel Fit from indexed counts.
    #: Key: (alarm_id, channel_id)
    fits: dict[tuple[str, str], ChannelFitFromIndex] = field(default_factory=dict)

    #: Channel metadata (derivation_tag, provenance) for grouping purposes.
    channel_meta: dict[str, tuple[str, ProvenanceClass]] = field(default_factory=dict)

    def fit_of(self, alarm_id: str, channel_id: str) -> ChannelFitFromIndex | None:
        return self.fits.get((alarm_id, channel_id))

    @property
    def channel_ids(self) -> list[str]:
        return sorted(self.channel_meta)


#: Fields used for equality-channel indexed statistics.
#: (channel_id, derivation_tag, raw_field_name)
EQUALITY_CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("E_reference", "reference", "node_reference"),
    ("E_device", "device", "device_code"),
    ("E_card", "card", "component"),
    ("E_site", "site", "location_code"),
    ("E_remote", "remote", "remote_node"),
    ("S", "semantic", "alarm_name"),
)

#: Semantic channel uses ordinal scale (same name=1.0, family=0.6, category=0.3)
#: but for Fit purposes (threshold=0.6 for S in the evaluator), only same-name
#: counts as SUPPORT at the default threshold. So the indexed approach groups by
#: exact alarm_name, matching the behavior of ``evaluate_semantic_channel`` at
#: the default ``THRESHOLD = SCORE_SAME_FAMILY = 0.6``: only ``same alarm_name``
#: (score=1.0) clears 0.6.
#: If a taxonomy is used, family-level matches also clear, requiring a lookup.
#: For now, the indexed path uses exact equality, which is correct for the
#: EMPTY_TAXONOMY default and the current real export.
SEMANTIC_CHANNEL_THRESHOLD = 0.6


def _read_field(alarm: IngestedAlarm, field_name: str) -> str | None:
    value = getattr(alarm, field_name, None)
    if value is None:
        value = alarm.raw.get(field_name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_indexed_statistics(
    package: IngestedPackage,
    chain_id: str,
    *,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
) -> IndexedChainStatistics:
    """Build exact indexed statistics for one chain without materializing pairs.

    For equality channels, ``Fit_k(x)`` = (same_group_size - 1) / (domain - 1).
    For T_burst, ``Fit_burst(x)`` = (burst_size - 1) / (domain - 1).
    """
    alarms = package.alarms_of(chain_id)
    member_ids = tuple(a.alarm_id for a in alarms)

    stats = IndexedChainStatistics(
        chain_id=chain_id,
        members=member_ids,
        statistics_mode=StatisticsMode.EXACT_INDEXED,
    )

    # --- Equality channels: hash group-by ---
    for channel_id, derivation_tag, field_name in EQUALITY_CHANNELS:
        stats.channel_meta[channel_id] = (derivation_tag, ProvenanceClass.POST_HOC)

        # Group members by their field value; None means the field is unavailable.
        groups: dict[str | None, list[str]] = {}
        for alarm in alarms:
            value = _read_field(alarm, field_name)
            groups.setdefault(value, []).append(alarm.alarm_id)

        # Domain = members that have the field available (non-None key).
        domain_ids = {
            alarm_id
            for value, members in groups.items()
            if value is not None
            for alarm_id in members
        }
        domain_size = len(domain_ids)

        for alarm in alarms:
            value = _read_field(alarm, field_name)
            if value is None or alarm.alarm_id not in domain_ids:
                # Field unavailable for this member => Fit = ⊥.
                stats.fits[(alarm.alarm_id, channel_id)] = ChannelFitFromIndex(
                    channel_id=channel_id,
                    derivation_tag=derivation_tag,
                    provenance_class=ProvenanceClass.POST_HOC,
                    fit=None,
                    domain_size=0,
                    supporting=0,
                )
                continue

            # D_k(x) = domain - 1 (all members with field available, minus x).
            d_k = domain_size - 1
            if d_k == 0:
                stats.fits[(alarm.alarm_id, channel_id)] = ChannelFitFromIndex(
                    channel_id=channel_id,
                    derivation_tag=derivation_tag,
                    provenance_class=ProvenanceClass.POST_HOC,
                    fit=None,
                    domain_size=0,
                    supporting=0,
                )
                continue

            # Supporting = members in the same group, minus self.
            same_group_size = len(groups[value])
            supporting = same_group_size - 1
            fit = supporting / d_k

            stats.fits[(alarm.alarm_id, channel_id)] = ChannelFitFromIndex(
                channel_id=channel_id,
                derivation_tag=derivation_tag,
                provenance_class=ProvenanceClass.POST_HOC,
                fit=fit,
                domain_size=d_k,
                supporting=supporting,
            )

    # --- T_burst: contextual segmentation → burst group sizes ---
    burst_channel = "T_burst"
    burst_tag = "temporal_burst"
    stats.channel_meta[burst_channel] = (burst_tag, ProvenanceClass.POST_HOC)

    segmentation = segment_bursts(alarms, silent_gap_seconds=silent_gap_seconds)
    burst_groups: dict[str, list[str]] = {}
    domain_burst: set[str] = set()
    for alarm in alarms:
        burst_id = segmentation.burst_of.get(alarm.alarm_id)
        if burst_id is not None:
            burst_groups.setdefault(burst_id, []).append(alarm.alarm_id)
            domain_burst.add(alarm.alarm_id)

    domain_burst_size = len(domain_burst)
    for alarm in alarms:
        burst_id = segmentation.burst_of.get(alarm.alarm_id)
        if burst_id is None or alarm.alarm_id not in domain_burst:
            stats.fits[(alarm.alarm_id, burst_channel)] = ChannelFitFromIndex(
                channel_id=burst_channel,
                derivation_tag=burst_tag,
                provenance_class=ProvenanceClass.POST_HOC,
                fit=None,
                domain_size=0,
                supporting=0,
            )
            continue

        d_k = domain_burst_size - 1
        if d_k == 0:
            stats.fits[(alarm.alarm_id, burst_channel)] = ChannelFitFromIndex(
                channel_id=burst_channel,
                derivation_tag=burst_tag,
                provenance_class=ProvenanceClass.POST_HOC,
                fit=None,
                domain_size=0,
                supporting=0,
            )
            continue

        same_burst_size = len(burst_groups[burst_id])
        supporting = same_burst_size - 1
        stats.fits[(alarm.alarm_id, burst_channel)] = ChannelFitFromIndex(
            channel_id=burst_channel,
            derivation_tag=burst_tag,
            provenance_class=ProvenanceClass.POST_HOC,
            fit=supporting / d_k,
            domain_size=d_k,
            supporting=supporting,
        )

    # --- T_delay: UNAVAILABLE without fitted distribution (not indexed) ---
    delay_channel = "T_delay"
    delay_tag = "temporal_delay"
    stats.channel_meta[delay_channel] = (delay_tag, ProvenanceClass.POST_HOC)
    for alarm in alarms:
        stats.fits[(alarm.alarm_id, delay_channel)] = ChannelFitFromIndex(
            channel_id=delay_channel,
            derivation_tag=delay_tag,
            provenance_class=ProvenanceClass.POST_HOC,
            fit=None,
            domain_size=0,
            supporting=0,
        )

    # --- Dep_hop: UNAVAILABLE unless topology/mapping loaded (not indexed here) ---
    dep_channel = "Dep_hop"
    dep_tag = "dependency_hop"
    stats.channel_meta[dep_channel] = (dep_tag, ProvenanceClass.EXTERNAL_OPERATIONAL)
    for alarm in alarms:
        stats.fits[(alarm.alarm_id, dep_channel)] = ChannelFitFromIndex(
            channel_id=dep_channel,
            derivation_tag=dep_tag,
            provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
            fit=None,
            domain_size=0,
            supporting=0,
        )

    return stats
