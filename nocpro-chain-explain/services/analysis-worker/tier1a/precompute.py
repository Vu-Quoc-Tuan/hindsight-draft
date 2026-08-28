"""Tier-1A snapshot background precompute (§3, ADR-0005/0014).

Tier-1A runs once per snapshot and produces only the global work that is reusable
across chains: predicate index, chain metadata, bounded descriptor candidates and
auto titles, plus cache warming.

Two hard rules:
- Tier-1A only runs on a COMPLETE snapshot (ADR-0005). An incomplete snapshot is
  refused rather than partially analyzed.
- Tier-1A does not compute roles or pair evidence. Those are Tier-1B, done lazily
  per chain on open, which is the 1A/1B split the spec introduced to resolve the
  earlier "background vs lazy" inconsistency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from descriptor import (
    DescriptorKind,
    DescriptorSet,
    MiningConfig,
    PredicateIndex,
    DEFAULT_MAX_VALUES_PER_FIELD,
    bitmap_of_members,
    build_predicate_index,
    mine_descriptors,
)
from libs.contracts import IngestedPackage
from tier1b.chain_analysis import auto_chain_title

from .cache import CacheTier, Tier1Cache


class IncompleteSnapshotError(RuntimeError):
    """Raised when Tier-1A is asked to run on an incomplete snapshot."""


@dataclass
class ChainSummary:
    """Per-chain Tier-1A output."""

    chain_id: str
    member_count: int
    is_singleton: bool
    descriptors: DescriptorSet
    auto_title: str
    fingerprint: str


@dataclass
class SnapshotPrecompute:
    """Tier-1A result for one snapshot."""

    snapshot_id: str
    config_version: str
    predicate_index: PredicateIndex
    chains: dict[str, ChainSummary] = field(default_factory=dict)
    alarm_count: int = 0
    singleton_count: int = 0

    @property
    def chain_count(self) -> int:
        return len(self.chains)

    def descriptors_of(self, chain_id: str) -> DescriptorSet | None:
        summary = self.chains.get(chain_id)
        return summary.descriptors if summary else None


def precompute_snapshot(
    package: IngestedPackage,
    *,
    mining_config: MiningConfig,
    cache: Tier1Cache | None = None,
    max_chains: int | None = None,
    max_values_per_field: int = DEFAULT_MAX_VALUES_PER_FIELD,
) -> SnapshotPrecompute:
    """Run Tier-1A background precompute for a complete snapshot."""
    if not package.snapshot.is_complete:
        raise IncompleteSnapshotError(
            f"snapshot {package.snapshot.snapshot_id!r} has status "
            f"{package.snapshot.status!r}; Tier-1A requires COMPLETE (ADR-0005)"
        )

    index = build_predicate_index(
        list(package.alarms.values()),
        max_values_per_field=max_values_per_field,
    )
    result = SnapshotPrecompute(
        snapshot_id=package.snapshot.snapshot_id,
        config_version=mining_config.config_version,
        predicate_index=index,
        alarm_count=len(package.alarms),
    )

    chain_ids = sorted(package.chains)
    if max_chains is not None:
        chain_ids = chain_ids[:max_chains]

    for chain_id in chain_ids:
        chain = package.chains[chain_id]
        member_ids = set(package.members_of(chain_id))
        target = bitmap_of_members(index, member_ids)

        # IDENTITY only: CONTRASTIVE needs U_local, which is Tier-1B work.
        identity = tuple(
            mine_descriptors(
                index, target, config=mining_config, kind=DescriptorKind.IDENTITY
            )
        )
        descriptors = DescriptorSet(
            chain_id=chain_id,
            identity=identity,
            config_version=mining_config.config_version,
            identity_insufficient=not identity,
        )

        from .cache import chain_fingerprint

        summary = ChainSummary(
            chain_id=chain_id,
            member_count=chain.member_count,
            is_singleton=chain.is_singleton,
            descriptors=descriptors,
            auto_title=auto_chain_title(chain_id, descriptors, mining_config),
            fingerprint=chain_fingerprint(member_ids),
        )
        result.chains[chain_id] = summary
        if chain.is_singleton:
            result.singleton_count += 1

        if cache is not None:
            key = cache.key_for(
                CacheTier.TIER_1A,
                member_ids=member_ids,
                snapshot_id=package.snapshot.snapshot_id,
                config_version=mining_config.config_version,
            )
            cache.put(key, summary, snapshot_chain_id=chain_id)

    return result
