"""Evolution pipeline (§7, ADR-0020).

Runs the six steps in the frozen order, which matters: REASSIGNED is decided
**after** lineage, so an alarm moving between chains is not misread as
clear-then-appear.

    1. NEW / CLEARED by alarm ID
    2. restrict to Active_both
    3. bipartite lineage edges
    4. evolving-chain components / branches
    5. RETAINED / REASSIGNED by evolving chain
    6. events with joined/left decomposition
"""

from __future__ import annotations

from dataclasses import dataclass, field

from libs.contracts import IngestedPackage

from .events import ChainEvolution, EvolutionEvent, classify_events
from .lifecycle import AlarmLifecycle, alarm_lifecycle, restrict_to_active_both
from .lineage import (
    LineageAssignment,
    LineageComponent,
    LineageConfig,
    LineageEdge,
    assign_identifiers,
    build_lineage_components,
    build_lineage_edges,
)


@dataclass
class EvolutionResult:
    """Complete evolution analysis between two snapshots."""

    previous_snapshot_id: str
    current_snapshot_id: str
    lifecycle: AlarmLifecycle
    edges: tuple[LineageEdge, ...]
    components: tuple[LineageComponent, ...]
    assignments: dict[str, LineageAssignment]
    chains: tuple[ChainEvolution, ...]
    config_version: str
    retained: frozenset[str] = field(default_factory=frozenset)
    reassigned: frozenset[str] = field(default_factory=frozenset)

    def event_of(self, chain_id: str) -> EvolutionEvent | None:
        for chain in self.chains:
            if chain.snapshot_chain_id == chain_id:
                return chain.event
        return None

    def event_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for chain in self.chains:
            counts[chain.event.value] = counts.get(chain.event.value, 0) + 1
        return counts

    def by_lineage_component(self) -> dict[str, list[ChainEvolution]]:
        grouped: dict[str, list[ChainEvolution]] = {}
        for chain in self.chains:
            if chain.lineage_component_id:
                grouped.setdefault(chain.lineage_component_id, []).append(chain)
        return grouped


def _full_partition(package: IngestedPackage) -> dict[str, frozenset[str]]:
    return {
        chain_id: frozenset(members)
        for chain_id, members in package.memberships.items()
    }


def analyze_evolution(
    previous: IngestedPackage,
    current: IngestedPackage,
    *,
    config: LineageConfig,
) -> EvolutionResult:
    """Run the evolution pipeline between two consecutive snapshots."""
    # Steps 1-2.
    lifecycle = alarm_lifecycle(previous, current)
    previous_active = restrict_to_active_both(previous, lifecycle.active_both)
    current_active = restrict_to_active_both(current, lifecycle.active_both)

    # Steps 3-4.
    edges = build_lineage_edges(previous_active, current_active, config)
    components = build_lineage_components(edges)
    assignments = assign_identifiers(components, set(current.memberships))

    # Step 5: RETAINED / REASSIGNED by evolving chain, after lineage exists.
    previous_owner = {
        alarm: chain for chain, members in previous_active.items() for alarm in members
    }
    component_of_child = {
        child: component.lineage_component_id
        for component in components
        for child in component.children
    }
    component_of_parent = {
        parent: component.lineage_component_id
        for component in components
        for parent in component.parents
    }

    retained: set[str] = set()
    reassigned: set[str] = set()
    for chain_id, members in current_active.items():
        current_component = component_of_child.get(chain_id)
        for alarm_id in members:
            previous_chain = previous_owner.get(alarm_id)
            if previous_chain is None:
                continue
            previous_component = component_of_parent.get(previous_chain)
            if (
                current_component is not None
                and previous_component == current_component
            ):
                # Same evolving chain, so a changed raw ID is not a reassignment.
                retained.add(alarm_id)
            else:
                reassigned.add(alarm_id)

    # Step 6.
    chains = classify_events(
        _full_partition(previous),
        _full_partition(current),
        components,
        assignments,
        lifecycle,
    )

    return EvolutionResult(
        previous_snapshot_id=previous.snapshot.snapshot_id,
        current_snapshot_id=current.snapshot.snapshot_id,
        lifecycle=lifecycle,
        edges=tuple(edges),
        components=tuple(components),
        assignments=assignments,
        chains=tuple(chains),
        config_version=config.config_version,
        retained=frozenset(retained),
        reassigned=frozenset(reassigned),
    )
