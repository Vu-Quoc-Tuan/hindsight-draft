"""Bounded pair detail storage (visualization / WHY drill-down).

Lives in ``channels`` rather than ``groups`` on purpose: this is display-bounded
pair evidence, and nothing in the statistical path may read it. ``Fit_k``,
``Fit_g``, ``MembershipSupport``, role and audit counts all derive from
:class:`groups.statistics.ChannelStatistics` instead.

Keeping the two in separate modules also makes the boundary visible in the import
graph: ``groups`` never imports this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import ChannelValue


@dataclass
class PairChannelMatrix:
    """Stored channel values for a bounded set of pairs.

    Keyed by unordered pair. Directional detail such as ``T_delay`` is stored as
    evaluated, so the caller decides which ordering it asked for.
    """

    values: dict[tuple[str, str], list[ChannelValue]] = field(default_factory=dict)

    @staticmethod
    def _key(alarm_a: str, alarm_b: str) -> tuple[str, str]:
        return tuple(sorted((alarm_a, alarm_b)))  # type: ignore[return-value]

    def add(self, alarm_a: str, alarm_b: str, values: list[ChannelValue]) -> None:
        self.values[self._key(alarm_a, alarm_b)] = values

    def get(self, alarm_a: str, alarm_b: str) -> list[ChannelValue]:
        """Pair detail for one pair, empty when it was not retained."""
        return self.values.get(self._key(alarm_a, alarm_b), [])

    def channel_ids(self) -> list[str]:
        seen: dict[str, None] = {}
        for values in self.values.values():
            for value in values:
                seen.setdefault(value.channel_id, None)
        return sorted(seen)

    def __len__(self) -> int:
        return len(self.values)
