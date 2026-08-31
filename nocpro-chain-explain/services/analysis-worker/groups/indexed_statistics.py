"""Channel-agnostic indexed sufficient-statistics result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from libs.provenance import ProvenanceClass, ProvenanceSubtype


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
    chain_id: str
    members: tuple[str, ...]
    statistics_mode: StatisticsMode
    audit_graph_mode: AuditGraphMode = AuditGraphMode.NOT_COMPUTED
    pair_materialization: PairMaterializationMode = PairMaterializationMode.ON_DEMAND
    fits: dict[tuple[str, str], ChannelFitFromIndex] = field(default_factory=dict)
    channel_meta: dict[
        str, tuple[str, ProvenanceClass, ProvenanceSubtype | None]
    ] = field(default_factory=dict)
    #: Exact bitmap of supporting peers for one member/channel. Bit positions
    #: follow ``members``. This is sufficient statistics for joint support
    #: queries without retaining or re-evaluating a pair list.
    support_peer_bitmaps: dict[tuple[str, str], int] = field(default_factory=dict)

    def fit_of(self, alarm_id: str, channel_id: str) -> ChannelFitFromIndex | None:
        return self.fits.get((alarm_id, channel_id))

    def support_bitmap_of(self, alarm_id: str, channel_id: str) -> int:
        return self.support_peer_bitmaps.get((alarm_id, channel_id), 0)

    @property
    def channel_ids(self) -> list[str]:
        return sorted(self.channel_meta)
