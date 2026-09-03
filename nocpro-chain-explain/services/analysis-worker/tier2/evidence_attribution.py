"""Exact group-level Evidence Coverage Attribution (ADR-0031)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from groups import IndexedChainStatistics, StatisticsMode, SupportIndexSemantics
from libs.provenance import NormalizedChannel, ProvenanceClass, build_derivation_groups


class AttributionStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AttributionMode(str, Enum):
    EXACT = "EXACT"
    UNAVAILABLE = "UNAVAILABLE"


class AttributionReason(str, Enum):
    ATTRIBUTION_LIMIT_EXCEEDED = "ATTRIBUTION_LIMIT_EXCEEDED"
    EXACT_INDEXED_STATISTICS_UNAVAILABLE = "EXACT_INDEXED_STATISTICS_UNAVAILABLE"
    SINGLETON = "SINGLETON"


@dataclass(frozen=True)
class AttributionExecutionPolicy:
    """Independent policy boundary, currently fed by audit.exact_max_members."""

    exact_max_members: int

    def __post_init__(self) -> None:
        if self.exact_max_members <= 0:
            raise ValueError("exact_max_members must be positive")


@dataclass(frozen=True)
class EvidenceCoverageContribution:
    group_id: str
    derivation_tag: str
    provenance_class: ProvenanceClass
    explain_eligible: bool
    role_eligible: bool
    audit_eligible: bool
    behavioral: bool
    supported_pair_count: int
    attribution: float


@dataclass(frozen=True)
class EvidenceCoverageAttributionResult:
    status: AttributionStatus
    mode: AttributionMode
    reason: AttributionReason | None
    detail: str | None
    chain_size: int
    exact_max_members: int
    total_pair_count: int
    covered_pair_count: int | None = None
    total_coverage: float | None = None
    contributions: tuple[EvidenceCoverageContribution, ...] = ()


@dataclass(frozen=True)
class ExactAttributionGroup:
    group_id: str
    derivation_tag: str
    provenance_class: ProvenanceClass
    explain_eligible: bool
    role_eligible: bool
    audit_eligible: bool
    behavioral: bool
    channel_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExactAttributionSupport:
    """Exact indexed pair support without a materialized pair list."""

    members: tuple[str, ...]
    total_pair_count: int
    groups: tuple[ExactAttributionGroup, ...]
    group_peer_rows: tuple[tuple[int, ...], ...]
    signature_pair_counts: tuple[tuple[int, int], ...]


def _group_id(group) -> str:
    key = group.key
    return "|".join(
        (
            key.derivation_tag,
            key.provenance_class.value,
            f"explain={int(key.explain_eligible)}",
            f"role={int(key.role_eligible)}",
            f"audit={int(key.audit_eligible)}",
        )
    )


def _partition_support_signatures(group_masks: list[int]) -> dict[int, int]:
    """Return disjoint peer bitmaps keyed by their exact supporting-group mask."""
    partitions: dict[int, int] = {}
    covered = 0
    for group_index, support in enumerate(group_masks):
        if not support:
            continue
        group_bit = 1 << group_index
        updated: dict[int, int] = {}
        for signature, peers in partitions.items():
            overlap = peers & support
            remainder = peers & ~support
            if overlap:
                updated[signature | group_bit] = (
                    updated.get(signature | group_bit, 0) | overlap
                )
            if remainder:
                updated[signature] = updated.get(signature, 0) | remainder
        new_peers = support & ~covered
        if new_peers:
            updated[group_bit] = updated.get(group_bit, 0) | new_peers
        covered |= support
        partitions = updated
    return partitions


def _exact_support_index_is_complete(
    members: tuple[str, ...], stats: IndexedChainStatistics
) -> bool:
    """Reject incomplete or malformed indexed support rather than under-credit it."""
    if stats.members != members:
        return False
    if (
        stats.support_index_semantics
        is not SupportIndexSemantics.SYMMETRIC_UNORDERED_PAIRS_V1
    ):
        return False
    positions = {alarm_id: index for index, alarm_id in enumerate(members)}
    universe_mask = (1 << len(members)) - 1
    for channel_id in stats.channel_meta:
        for alarm_id, position in positions.items():
            key = (alarm_id, channel_id)
            if key not in stats.support_peer_bitmaps:
                return False
            peers = stats.support_peer_bitmaps[key]
            if peers < 0 or peers & ~universe_mask or peers & (1 << position):
                return False
    return True


def build_exact_attribution_support(
    members: tuple[str, ...] | list[str],
    statistics: IndexedChainStatistics | None,
) -> ExactAttributionSupport | None:
    """Build exact eligible-group bitmap rows, or fail closed with ``None``."""
    member_tuple = tuple(members)
    if (
        statistics is None
        or statistics.statistics_mode is not StatisticsMode.EXACT_INDEXED
        or not _exact_support_index_is_complete(member_tuple, statistics)
    ):
        return None

    representatives = [
        NormalizedChannel(
            channel_id=channel_id,
            derivation_tag=metadata[0],
            provenance_class=metadata[1],
            provenance_subtype=metadata[2],
        )
        for channel_id, metadata in statistics.channel_meta.items()
    ]
    derived_groups = tuple(
        group
        for group in build_derivation_groups(representatives)
        if group.explain_eligible
    )
    groups = tuple(
        ExactAttributionGroup(
            group_id=_group_id(group),
            derivation_tag=group.key.derivation_tag,
            provenance_class=group.provenance_class,
            explain_eligible=group.explain_eligible,
            role_eligible=group.role_eligible,
            audit_eligible=group.audit_eligible,
            behavioral=group.provenance_class is ProvenanceClass.BEHAVIORAL,
            channel_ids=tuple(channel.channel_id for channel in group.channels),
        )
        for group in derived_groups
    )
    rows: list[tuple[int, ...]] = []
    signature_pair_counts: dict[int, int] = {}
    for left, alarm_id in enumerate(member_tuple):
        upper_peers = ~((1 << (left + 1)) - 1)
        row: list[int] = []
        for group in groups:
            peers = 0
            for channel_id in group.channel_ids:
                peers |= statistics.support_bitmap_of(alarm_id, channel_id)
            row.append(peers & upper_peers)
        rows.append(tuple(row))
        for signature, peers in _partition_support_signatures(row).items():
            signature_pair_counts[signature] = (
                signature_pair_counts.get(signature, 0) + peers.bit_count()
            )
    return ExactAttributionSupport(
        members=member_tuple,
        total_pair_count=len(member_tuple) * (len(member_tuple) - 1) // 2,
        groups=groups,
        group_peer_rows=tuple(rows),
        signature_pair_counts=tuple(sorted(signature_pair_counts.items())),
    )


def compute_evidence_coverage_attribution(
    chain_id: str,
    members: tuple[str, ...] | list[str],
    statistics: IndexedChainStatistics | None,
    *,
    policy: AttributionExecutionPolicy,
    exact_support: ExactAttributionSupport | None = None,
) -> EvidenceCoverageAttributionResult:
    """Compute exact attribution from indexed support bitmaps, fail closed otherwise."""
    del chain_id  # retained in the interface for logging/caller symmetry
    chain_size = len(members)
    pair_count = chain_size * (chain_size - 1) // 2
    if chain_size > policy.exact_max_members:
        return EvidenceCoverageAttributionResult(
            status=AttributionStatus.UNAVAILABLE,
            mode=AttributionMode.UNAVAILABLE,
            reason=AttributionReason.ATTRIBUTION_LIMIT_EXCEEDED,
            detail=None,
            chain_size=chain_size,
            exact_max_members=policy.exact_max_members,
            total_pair_count=pair_count,
        )
    if chain_size == 1:
        return EvidenceCoverageAttributionResult(
            status=AttributionStatus.NOT_APPLICABLE,
            mode=AttributionMode.UNAVAILABLE,
            reason=AttributionReason.SINGLETON,
            detail="SINGLETON_CHAIN",
            chain_size=chain_size,
            exact_max_members=policy.exact_max_members,
            total_pair_count=0,
        )
    support = exact_support or build_exact_attribution_support(members, statistics)
    if support is None or support.members != tuple(members):
        return EvidenceCoverageAttributionResult(
            status=AttributionStatus.UNAVAILABLE,
            mode=AttributionMode.UNAVAILABLE,
            reason=AttributionReason.EXACT_INDEXED_STATISTICS_UNAVAILABLE,
            detail=None,
            chain_size=chain_size,
            exact_max_members=policy.exact_max_members,
            total_pair_count=pair_count,
        )

    weighted_shares = [0.0] * len(support.groups)
    supported_pair_counts = [0] * len(support.groups)
    covered_pair_count = sum(
        pair_multiplicity
        for _, pair_multiplicity in support.signature_pair_counts
    )
    for group_masks in support.group_peer_rows:
        for group_index, peers in enumerate(group_masks):
            supported_pair_counts[group_index] += peers.bit_count()
    for signature, pair_multiplicity in support.signature_pair_counts:
        share = pair_multiplicity / signature.bit_count()
        remaining_groups = signature
        while remaining_groups:
            group_bit = remaining_groups & -remaining_groups
            group_index = group_bit.bit_length() - 1
            weighted_shares[group_index] += share
            remaining_groups ^= group_bit

    contributions: list[EvidenceCoverageContribution] = []
    for group_index, group in enumerate(support.groups):
        contributions.append(
            EvidenceCoverageContribution(
                group_id=group.group_id,
                derivation_tag=group.derivation_tag,
                provenance_class=group.provenance_class,
                explain_eligible=group.explain_eligible,
                role_eligible=group.role_eligible,
                audit_eligible=group.audit_eligible,
                behavioral=group.behavioral,
                supported_pair_count=supported_pair_counts[group_index],
                attribution=weighted_shares[group_index] / pair_count,
            )
        )

    contributions.sort(
        key=lambda item: (-item.attribution, item.derivation_tag, item.provenance_class.value)
    )
    return EvidenceCoverageAttributionResult(
        status=AttributionStatus.AVAILABLE,
        mode=AttributionMode.EXACT,
        reason=None,
        detail=None,
        chain_size=chain_size,
        exact_max_members=policy.exact_max_members,
        total_pair_count=pair_count,
        covered_pair_count=covered_pair_count,
        total_coverage=covered_pair_count / pair_count,
        contributions=tuple(contributions),
    )
