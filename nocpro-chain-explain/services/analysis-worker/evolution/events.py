"""Step 5-6: event classification and joined/left decomposition (§7, ADR-0020).

Events: CONTINUE / GROW / SHRINK / SPLIT / MERGE / NEW / DISSOLVE / RECOMBINATION.

Classification is by **evolving chain**, not raw chain ID: 123 -> 984 with the
same membership is CONTINUE, because a snapshot-local identifier changing is not
an incident changing.

Every CONTINUE / GROW / SHRINK carries four decomposition lines:

    joined_new         joined and newly appeared
    joined_reassigned  joined but was already active elsewhere
    left_cleared       left because the alarm cleared
    left_reassigned    left but is still active in another chain

Without these, +10 new and -10 cleared shows ``delta_size = 0`` and hides a
turnover of 20.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .lifecycle import AlarmLifecycle
from .lineage import LineageAssignment, LineageComponent


class EvolutionEvent(str, Enum):
    CONTINUE = "CONTINUE"
    GROW = "GROW"
    SHRINK = "SHRINK"
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    NEW = "NEW"
    DISSOLVE = "DISSOLVE"
    RECOMBINATION = "RECOMBINATION"


class MembershipStability(str, Enum):
    """Per-alarm persistence label (§7: 0.9 stable / 0.3 boundary)."""

    STABLE = "STABLE"
    BOUNDARY = "BOUNDARY"
    UNSTABLE = "UNSTABLE"


#: Persistence thresholds from §7.
STABLE_THRESHOLD = 0.9
BOUNDARY_THRESHOLD = 0.3


@dataclass(frozen=True)
class Decomposition:
    """The four joined/left lines."""

    joined_new: int
    joined_reassigned: int
    left_cleared: int
    left_reassigned: int

    @property
    def joined_total(self) -> int:
        return self.joined_new + self.joined_reassigned

    @property
    def left_total(self) -> int:
        return self.left_cleared + self.left_reassigned

    @property
    def delta_size(self) -> int:
        return self.joined_total - self.left_total

    @property
    def turnover(self) -> int:
        """Total churn, which stays visible even when ``delta_size`` is zero."""
        return self.joined_total + self.left_total


@dataclass(frozen=True)
class ChainEvolution:
    """Evolution verdict for one current-snapshot chain."""

    snapshot_chain_id: str
    event: EvolutionEvent
    lineage_component_id: str | None
    branch_id: str | None
    previous_chain_ids: tuple[str, ...]
    decomposition: Decomposition | None
    jaccard: float | None
    reason: str

    @property
    def is_identifier_change_only(self) -> bool:
        """CONTINUE across a changed raw chain ID."""
        return (
            self.event is EvolutionEvent.CONTINUE
            and bool(self.previous_chain_ids)
            and self.snapshot_chain_id not in self.previous_chain_ids
        )


def decompose(
    previous_members: frozenset[str],
    current_members: frozenset[str],
    lifecycle: AlarmLifecycle,
    *,
    previous_owner: dict[str, str],
    current_owner: dict[str, str],
    chain_id: str,
) -> Decomposition:
    """Split joined/left into the four reasons."""
    joined = current_members - previous_members
    left = previous_members - current_members

    joined_new = sum(1 for a in joined if a in lifecycle.new_alarms)
    # Already active last snapshot, so it moved rather than appeared.
    joined_reassigned = sum(
        1
        for a in joined
        if a not in lifecycle.new_alarms and previous_owner.get(a) not in (None, chain_id)
    )
    left_cleared = sum(1 for a in left if a in lifecycle.cleared_alarms)
    left_reassigned = sum(
        1
        for a in left
        if a not in lifecycle.cleared_alarms
        and current_owner.get(a) not in (None, chain_id)
    )
    return Decomposition(
        joined_new=joined_new,
        joined_reassigned=joined_reassigned,
        left_cleared=left_cleared,
        left_reassigned=left_reassigned,
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def classify_events(
    previous_members: dict[str, frozenset[str]],
    current_members: dict[str, frozenset[str]],
    components: list[LineageComponent],
    assignments: dict[str, LineageAssignment],
    lifecycle: AlarmLifecycle,
) -> list[ChainEvolution]:
    """Classify every current chain, plus dissolved previous chains.

    ``previous_members`` / ``current_members`` are the **full** partitions, so
    decomposition sees cleared and new alarms. Lineage itself was computed on
    ``Active_both``.
    """
    previous_owner = {
        alarm: chain for chain, members in previous_members.items() for alarm in members
    }
    current_owner = {
        alarm: chain for chain, members in current_members.items() for alarm in members
    }
    by_component = {c.lineage_component_id: c for c in components}

    results: list[ChainEvolution] = []
    surviving_parents: set[str] = set()

    for chain_id in sorted(current_members):
        assignment = assignments.get(chain_id)
        members = current_members[chain_id]

        if assignment is None or not assignment.has_lineage:
            results.append(
                ChainEvolution(
                    snapshot_chain_id=chain_id,
                    event=EvolutionEvent.NEW,
                    lineage_component_id=None,
                    branch_id=None,
                    previous_chain_ids=(),
                    decomposition=None,
                    jaccard=None,
                    reason="no lineage edge to any previous chain",
                )
            )
            continue

        component = by_component[assignment.lineage_component_id]
        surviving_parents.update(component.parents)

        # Union of parents in this component, from the full previous partition.
        parent_union: frozenset[str] = frozenset()
        for parent_id in component.parents:
            parent_union |= previous_members.get(parent_id, frozenset())

        decomposition = decompose(
            parent_union,
            members,
            lifecycle,
            previous_owner=previous_owner,
            current_owner=current_owner,
            chain_id=chain_id,
        )
        jaccard = _jaccard(parent_union, members)

        if component.is_recombination:
            event = EvolutionEvent.RECOMBINATION
            reason = (
                f"{len(component.parents)} parents and {len(component.children)} "
                "children in one lineage component"
            )
        elif component.is_split:
            event = EvolutionEvent.SPLIT
            reason = f"one parent split into {len(component.children)} chains"
        elif component.is_merge:
            event = EvolutionEvent.MERGE
            reason = f"{len(component.parents)} parents merged into one chain"
        else:
            delta = decomposition.delta_size
            if delta > 0:
                event, reason = (
                    EvolutionEvent.GROW,
                    f"membership grew by {delta}",
                )
            elif delta < 0:
                event, reason = (
                    EvolutionEvent.SHRINK,
                    f"membership shrank by {-delta}",
                )
            else:
                # Same membership size. A changed raw ID is still CONTINUE.
                event = EvolutionEvent.CONTINUE
                reason = (
                    "membership preserved"
                    if chain_id in component.parents
                    else "membership preserved under a new snapshot chain ID"
                )

        results.append(
            ChainEvolution(
                snapshot_chain_id=chain_id,
                event=event,
                lineage_component_id=assignment.lineage_component_id,
                branch_id=assignment.branch_id,
                previous_chain_ids=component.parents,
                decomposition=decomposition,
                jaccard=jaccard,
                reason=reason,
            )
        )

    # Previous chains with no surviving lineage dissolved.
    for chain_id in sorted(previous_members):
        if chain_id in surviving_parents:
            continue
        results.append(
            ChainEvolution(
                snapshot_chain_id=chain_id,
                event=EvolutionEvent.DISSOLVE,
                lineage_component_id=None,
                branch_id=None,
                previous_chain_ids=(chain_id,),
                decomposition=None,
                jaccard=None,
                reason="no lineage edge to any current chain",
            )
        )

    return results


def membership_stability(persistence: float) -> MembershipStability:
    """Label per-alarm persistence."""
    if persistence >= STABLE_THRESHOLD:
        return MembershipStability.STABLE
    if persistence >= BOUNDARY_THRESHOLD:
        return MembershipStability.BOUNDARY
    return MembershipStability.UNSTABLE
