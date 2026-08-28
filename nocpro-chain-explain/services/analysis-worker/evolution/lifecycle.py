"""Step 1-2 of the evolution pipeline: alarm lifecycle and ``Active_both`` (§7).

    NEW / CLEARED by alarm ID
    Active_both = alarms present in both snapshots

Chain correspondence is restricted to ``Active_both`` so lineage measures how the
grouping of *surviving* alarms changed, rather than being confounded by alarms
that simply appeared or cleared.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedPackage


@dataclass(frozen=True)
class AlarmLifecycle:
    """Alarm-level difference between two snapshots."""

    previous_snapshot_id: str
    current_snapshot_id: str
    new_alarms: frozenset[str]
    cleared_alarms: frozenset[str]
    active_both: frozenset[str]

    @property
    def turnover(self) -> int:
        """Total alarm churn.

        Reported separately from size change: +10 new and -10 cleared leaves
        ``delta_size = 0`` while turnover is 20, and hiding that would make a
        heavily churning chain look static.
        """
        return len(self.new_alarms) + len(self.cleared_alarms)


def alarm_lifecycle(
    previous: IngestedPackage, current: IngestedPackage
) -> AlarmLifecycle:
    """Compute NEW / CLEARED / ``Active_both`` by alarm ID."""
    previous_ids = set(previous.alarms)
    current_ids = set(current.alarms)
    return AlarmLifecycle(
        previous_snapshot_id=previous.snapshot.snapshot_id,
        current_snapshot_id=current.snapshot.snapshot_id,
        new_alarms=frozenset(current_ids - previous_ids),
        cleared_alarms=frozenset(previous_ids - current_ids),
        active_both=frozenset(previous_ids & current_ids),
    )


def restrict_to_active_both(
    package: IngestedPackage, active_both: frozenset[str]
) -> dict[str, frozenset[str]]:
    """Chain -> members, keeping only alarms active in both snapshots.

    Chains left with no surviving member are dropped: they cannot participate in
    correspondence.
    """
    restricted: dict[str, frozenset[str]] = {}
    for chain_id, members in package.memberships.items():
        surviving = frozenset(m for m in members if m in active_both)
        if surviving:
            restricted[chain_id] = surviving
    return restricted
