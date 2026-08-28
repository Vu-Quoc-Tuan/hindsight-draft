"""Indexed Tier-1 evidence without default pair materialization."""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedPackage

from groups.indexed_statistics import (
    AuditGraphMode,
    IndexedChainStatistics,
    PairMaterializationMode,
    StatisticsMode,
)

from .semantic import EMPTY_TAXONOMY, AlarmTaxonomy
from .indexed_statistics import build_indexed_statistics
from .temporal import DEFAULT_SILENT_GAP_SECONDS
from .dependency import DEFAULT_D_MAX


@dataclass
class IndexedChainEvidence:
    """Tier-1 statistical evidence with explicit fidelity modes."""

    chain_id: str
    members: list[str]
    statistics: IndexedChainStatistics
    statistics_mode: StatisticsMode
    audit_graph_mode: AuditGraphMode
    pair_materialization: PairMaterializationMode
    detail_pairs: int = 0
    detail_truncated: bool = False

    @property
    def full_pair_space(self) -> int:
        count = len(self.members)
        return count * (count - 1) // 2

    @property
    def statistics_exact(self) -> bool:
        return self.statistics_mode is StatisticsMode.EXACT_INDEXED


def evaluate_chain_indexed(
    package: IngestedPackage,
    chain_id: str,
    *,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
    d_max: int = DEFAULT_D_MAX,
) -> IndexedChainEvidence:
    """Build exact available Tier-1 statistics without scanning member pairs."""
    if chain_id not in package.chains:
        raise KeyError(f"unknown chain_id {chain_id!r}")
    statistics = build_indexed_statistics(
        package,
        chain_id,
        taxonomy=taxonomy,
        silent_gap_seconds=silent_gap_seconds,
        d_max=d_max,
    )
    return IndexedChainEvidence(
        chain_id=chain_id,
        members=list(statistics.members),
        statistics=statistics,
        statistics_mode=statistics.statistics_mode,
        audit_graph_mode=statistics.audit_graph_mode,
        pair_materialization=statistics.pair_materialization,
    )
