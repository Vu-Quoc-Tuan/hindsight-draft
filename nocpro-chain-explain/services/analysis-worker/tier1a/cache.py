"""Tier-1 cache (§3 principle 3, ADR-0014).

Cache key includes the chain fingerprint, exact snapshot identity, configuration,
and topology version, so a Kafka topology advance cannot reuse analysis built
against an older graph.

The fingerprint is derived from **membership**, not the raw chain ID: a chain
whose snapshot-local ID changed while its members stayed identical is the same
work (ADR-0020). Config version is part of the key because a threshold change
must produce a new entry rather than silently reusing an old explanation
(ADR-0025).

Tier separation (ADR-0014): Tier-1B must never wait for Tier-2, so entries are
stored per tier and a missing Tier-2 entry is simply absent rather than blocking.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar


class CacheTier(str, Enum):
    TIER_1A = "TIER_1A"
    TIER_1B = "TIER_1B"
    TIER_2 = "TIER_2"


def chain_fingerprint(member_ids: set[str] | frozenset[str]) -> str:
    """Stable fingerprint of a membership set.

    Sorted before hashing so member ordering cannot change the key.
    """
    joined = "\n".join(sorted(member_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class CacheKey:
    """Identity of one cached computation."""

    tier: CacheTier
    fingerprint: str
    snapshot_id: str
    snapshot_version: str
    config_version: str
    topology_version: str | None = None

    def as_tuple(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.tier.value,
            self.fingerprint,
            self.snapshot_id,
            self.snapshot_version,
            self.config_version,
            self.topology_version or "UNPINNED_TOPOLOGY",
        )


T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """One cached value plus the key that produced it."""

    key: CacheKey
    value: T
    #: Raw snapshot-local chain ID, kept for display and traceability.
    snapshot_chain_id: str | None = None


@dataclass
class Tier1Cache:
    """In-memory tier-aware cache.

    Deliberately a plain dict: persistence is a later concern (ADR-0004 lists
    PostgreSQL as *proposed*), and the semantics that matter now are the key
    composition and the tier separation.
    """

    entries: dict[tuple[str, str, str, str, str, str], CacheEntry[Any]] = field(
        default_factory=dict
    )
    hits: int = 0
    misses: int = 0
    max_entries: int = 5000

    def key_for(
        self,
        tier: CacheTier,
        *,
        member_ids: set[str] | frozenset[str],
        snapshot_id: str,
        snapshot_version: str,
        config_version: str,
        topology_version: str | None = None,
    ) -> CacheKey:
        return CacheKey(
            tier=tier,
            fingerprint=chain_fingerprint(member_ids),
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            config_version=config_version,
            topology_version=topology_version,
        )

    def get(self, key: CacheKey) -> Any | None:
        entry = self.entries.get(key.as_tuple())
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        return entry.value

    def put(
        self, key: CacheKey, value: Any, *, snapshot_chain_id: str | None = None
    ) -> None:
        tup = key.as_tuple()
        if tup not in self.entries and len(self.entries) >= self.max_entries:
            evict_count = max(1, self.max_entries // 10)
            for _ in range(evict_count):
                if self.entries:
                    oldest = next(iter(self.entries))
                    del self.entries[oldest]
        self.entries[tup] = CacheEntry(
            key=key, value=value, snapshot_chain_id=snapshot_chain_id
        )

    def has(self, key: CacheKey) -> bool:
        """Presence check that does not count as a hit or miss."""
        return key.as_tuple() in self.entries

    def invalidate_config(self, config_version: str) -> int:
        """Drop every entry produced under a given config version."""
        doomed = [
            k for k in self.entries if k[4] == config_version
        ]
        for key in doomed:
            del self.entries[key]
        return len(doomed)

    def invalidate_snapshot(self, snapshot_id: str) -> int:
        doomed = [k for k in self.entries if k[2] == snapshot_id]
        for key in doomed:
            del self.entries[key]
        return len(doomed)

    def tier_entries(self, tier: CacheTier) -> list[CacheEntry[Any]]:
        return [e for e in self.entries.values() if e.key.tier is tier]

    def __len__(self) -> int:
        return len(self.entries)
