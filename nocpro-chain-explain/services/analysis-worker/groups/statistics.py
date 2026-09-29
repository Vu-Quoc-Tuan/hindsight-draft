"""Exact per-member channel statistics (§4B, §6 three-graph rule, ADR-0015).

Separates two things that must never be conflated:

    STATISTICAL truth   exact counts over the full pair space, no sparsification
    PAIR DETAIL         bounded listing for WHY drill-down / visualization

``Fit_k``, ``Fit_g``, ``MembershipSupport``, role and audit counts read from the
statistics here. They must be identical no matter how small the pair-detail cap
is. Computing them from a truncated pair list would silently make the verdict a
function of a display budget.

Memory is O(members x channels), not O(pairs): counts are accumulated in a
streaming pass, so nothing is materialized. ADR-0015 prohibits unguarded pair
*materialization*, not exact aggregation.

Above :data:`EXACT_STATISTICS_MAX_MEMBERS` even a streaming pass is too costly,
so the result is marked ``exact=False``. This module does not build an
approximation; callers must surface the relevant capability as unavailable or
skip the exact-only operation. It never degrades silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Protocol, runtime_checkable


@runtime_checkable
class ChannelVerdict(Protocol):
    """Structural view of a channel value.

    Declared as a Protocol so ``groups`` never imports ``channels``: the
    dependency runs one way (channels -> groups), which keeps the statistical
    layer independent of how evidence is produced.
    """

    channel_id: str
    derivation_tag: str
    availability: bool

    @property
    def supports(self) -> bool: ...

#: Chains up to this size get exact statistics over the full pair space.
#: §6 sets the audit-graph exact bound at roughly 2k members.
EXACT_STATISTICS_MAX_MEMBERS = 2_000


@dataclass
class ChannelCounts:
    """``|D_k(x,C)|`` and the supporting count for one (member, channel)."""

    domain_size: int = 0
    supporting: int = 0
    derivation_tag: str = ""

    @property
    def fit(self) -> float | None:
        """``Fit_k``; ``None`` (⊥) when the domain is empty."""
        if self.domain_size == 0:
            return None
        return self.supporting / self.domain_size


@dataclass
class ChannelStatistics:
    """Exact per-member, per-channel counts for one chain."""

    chain_id: str
    members: tuple[str, ...]
    #: (alarm_id, channel_id) -> counts
    counts: dict[tuple[str, str], ChannelCounts] = field(default_factory=dict)
    #: Channel metadata needed for derivation grouping.
    channel_meta: dict[str, ChannelVerdict] = field(default_factory=dict)
    #: Pairs actually visited. Equals C(n,2) when exact.
    pairs_counted: int = 0
    #: False when the chain exceeded the exact bound and a policy is required.
    exact: bool = True

    @property
    def full_pair_space(self) -> int:
        n = len(self.members)
        return n * (n - 1) // 2

    def channel_ids(self) -> list[str]:
        return sorted(self.channel_meta)

    def counts_for(self, alarm_id: str, channel_id: str) -> ChannelCounts:
        return self.counts.get((alarm_id, channel_id), ChannelCounts())

    def record(self, alarm_a: str, alarm_b: str, values: list[ChannelVerdict]) -> None:
        """Accumulate one pair's channel verdicts into both endpoints."""
        for value in values:
            self.channel_meta.setdefault(value.channel_id, value)
            if not value.availability:
                # ⊥ contributes to neither the domain nor the numerator.
                continue
            supports = value.supports
            for alarm_id in (alarm_a, alarm_b):
                key = (alarm_id, value.channel_id)
                entry = self.counts.get(key)
                if entry is None:
                    entry = ChannelCounts(derivation_tag=value.derivation_tag)
                    self.counts[key] = entry
                entry.domain_size += 1
                if supports:
                    entry.supporting += 1


def pair_iterator(members: list[str]):
    """All unordered member pairs."""
    return combinations(members, 2)


def statistics_are_exact(member_count: int) -> bool:
    return member_count <= EXACT_STATISTICS_MAX_MEMBERS
