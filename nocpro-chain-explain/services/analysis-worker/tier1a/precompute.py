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
from datetime import UTC, datetime

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
    start_time: str | None = None
    end_time: str | None = None
    duration_seconds: float | None = None


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


def _canonical_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _chain_time_summary(package: IngestedPackage, chain_id: str) -> tuple[str | None, str | None, float | None]:
    starts: list[tuple[datetime, str]] = []
    ends: list[tuple[datetime, str]] = []
    for alarm in package.alarms_of(chain_id):
        start = _canonical_time(alarm.canonical_start_time)
        if start is not None and alarm.canonical_start_time is not None:
            starts.append((start, alarm.canonical_start_time))
            ends.append((start, alarm.canonical_start_time))
        end = _canonical_time(alarm.canonical_end_time)
        if end is not None and alarm.canonical_end_time is not None:
            ends.append((end, alarm.canonical_end_time))
    if not starts or not ends:
        return None, None, None
    start_dt, start_value = min(starts, key=lambda item: item[0])
    end_dt, end_value = max(ends, key=lambda item: item[0])
    return start_value, end_value, max(0.0, (end_dt - start_dt).total_seconds())


def precompute_snapshot(
    package: IngestedPackage,
    *,
    mining_config: MiningConfig,
    cache: Tier1Cache | None = None,
    max_chains: int | None = None,
    max_values_per_field: int = DEFAULT_MAX_VALUES_PER_FIELD,
    predicate_index: PredicateIndex | None = None,
) -> SnapshotPrecompute:
    """Run Tier-1A background precompute for a complete snapshot."""
    if not package.snapshot.is_complete:
        raise IncompleteSnapshotError(
            f"snapshot {package.snapshot.snapshot_id!r} has status "
            f"{package.snapshot.status!r}; Tier-1A requires COMPLETE (ADR-0005)"
        )

    index = predicate_index or build_predicate_index(
        list(package.alarms.values()), max_values_per_field=max_values_per_field
    )
    if set(index.active_ids) != set(package.alarms):
        raise ValueError("predicate index does not match snapshot alarms")
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

        start_time, end_time, duration_seconds = _chain_time_summary(package, chain_id)

        summary = ChainSummary(
            chain_id=chain_id,
            member_count=chain.member_count,
            is_singleton=chain.is_singleton,
            descriptors=descriptors,
            auto_title=auto_chain_title(chain_id, descriptors, mining_config),
            fingerprint=chain_fingerprint(member_ids),
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds,
        )
        result.chains[chain_id] = summary
        if chain.is_singleton:
            result.singleton_count += 1

        if cache is not None:
            key = cache.key_for(
                CacheTier.TIER_1A,
                member_ids=member_ids,
                snapshot_id=package.snapshot.snapshot_id,
                snapshot_version=package.snapshot.snapshot_version,
                config_version=mining_config.config_version,
            )
            cache.put(key, summary, snapshot_chain_id=chain_id)

    return result
