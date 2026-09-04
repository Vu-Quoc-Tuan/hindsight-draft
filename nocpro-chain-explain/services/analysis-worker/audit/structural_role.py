"""STRUCTURAL role axis: CONNECTOR / NON_CONNECTOR (§4B).

    CONNECTOR <=> articulation/bridge on the audit graph AND support to >= 2 blocks
    otherwise NON_CONNECTOR

Uses the same ``AuditGraph`` as the audit engine (never the top-K visualization
graph, per the three-graph rule), so structural role and over-merge audit are
computed from one consistent evidence graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from collections.abc import Iterator

from .graph import AuditGraph


class StructuralRole(str, Enum):
    CONNECTOR = "CONNECTOR"
    NON_CONNECTOR = "NON_CONNECTOR"
    #: The graph has too few audit-eligible edges to test connectivity.
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class StructuralRoleResult:
    alarm_id: str
    role: StructuralRole
    is_articulation_point: bool
    blocks_supported: int
    reason: str


def _articulation_analysis(graph: AuditGraph) -> tuple[set[str], dict[str, int]]:
    """Return articulation points and exact component counts after removal.

    Audit is exact up to the configured member ceiling (currently 2,000), so a
    valid sparse graph can contain a path deeper than Python's recursion limit.
    This iterative Tarjan traversal also derives the component count after
    removing each node, avoiding a separate graph traversal for every member.
    """
    adjacency = {
        node: tuple(sorted(neighbours))
        for node, neighbours in graph.adjacency.items()
    }
    for node in graph.members:
        adjacency.setdefault(node, ())

    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    child_count: dict[str, int] = {}
    separating_child_count: dict[str, int] = {}
    articulation: set[str] = set()
    timer = 0
    original_component_count = 0
    for node in graph.members:
        if node in discovery:
            continue
        original_component_count += 1
        parent[node] = None
        child_count[node] = 0
        separating_child_count[node] = 0
        discovery[node] = low[node] = timer
        timer += 1
        stack: list[tuple[str, Iterator[str]]] = [(node, iter(adjacency[node]))]

        while stack:
            current, neighbours = stack[-1]
            try:
                neighbour = next(neighbours)
            except StopIteration:
                stack.pop()
                current_parent = parent[current]
                if current_parent is None:
                    if child_count[current] > 1:
                        articulation.add(current)
                    continue

                low[current_parent] = min(low[current_parent], low[current])
                if low[current] >= discovery[current_parent]:
                    separating_child_count[current_parent] += 1
                    if parent[current_parent] is not None:
                        articulation.add(current_parent)
                continue

            if neighbour == parent[current]:
                continue
            if neighbour in discovery:
                low[current] = min(low[current], discovery[neighbour])
                continue

            parent[neighbour] = current
            child_count[current] += 1
            child_count[neighbour] = 0
            separating_child_count[neighbour] = 0
            discovery[neighbour] = low[neighbour] = timer
            timer += 1
            stack.append((neighbour, iter(adjacency[neighbour])))

    components_after_removal: dict[str, int] = {}
    for node in graph.members:
        if parent[node] is None:
            component_parts_after_removal = child_count[node]
        else:
            component_parts_after_removal = separating_child_count[node] + 1
        components_after_removal[node] = (
            original_component_count - 1 + component_parts_after_removal
        )
    return articulation, components_after_removal


def find_articulation_points(graph: AuditGraph) -> set[str]:
    """Return classic articulation points over the exact audit graph."""
    articulation, _components_after_removal = _articulation_analysis(graph)
    return articulation


def connected_components(graph: AuditGraph, *, exclude: str | None = None) -> list[set[str]]:
    """Connected components of the audit graph, optionally excluding one node."""
    remaining = [m for m in graph.members if m != exclude]
    visited: set[str] = set()
    components: list[set[str]] = []

    for start in remaining:
        if start in visited:
            continue
        stack = [start]
        component: set[str] = set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            visited.add(node)
            for neighbour in graph.neighbours(node):
                if neighbour != exclude and neighbour not in component:
                    stack.append(neighbour)
        components.append(component)

    return components


def _structural_role_result(
    alarm_id: str,
    *,
    articulation_points: set[str],
    blocks_supported: int,
) -> StructuralRoleResult:
    """Build one role result from precomputed exact Tarjan facts."""
    is_articulation = alarm_id in articulation_points

    if is_articulation and blocks_supported >= 2:
        return StructuralRoleResult(
            alarm_id=alarm_id,
            role=StructuralRole.CONNECTOR,
            is_articulation_point=True,
            blocks_supported=blocks_supported,
            reason=(
                f"removing this member splits the audit graph into "
                f"{blocks_supported} components"
            ),
        )

    return StructuralRoleResult(
        alarm_id=alarm_id,
        role=StructuralRole.NON_CONNECTOR,
        is_articulation_point=is_articulation,
        blocks_supported=blocks_supported,
        reason="removal does not increase the number of audit-graph components to >= 2",
    )


def classify_structural_roles(graph: AuditGraph) -> dict[str, StructuralRoleResult]:
    """Classify all graph members from one exact traversal.

    Equivalent to the single-member API for every member, but avoids an
    accidental O(|C| * (|V| + |E|)) Audit role-assembly path.
    """
    if not graph.edges:
        return {
            alarm_id: StructuralRoleResult(
                alarm_id=alarm_id,
                role=StructuralRole.NOT_APPLICABLE,
                is_articulation_point=False,
                blocks_supported=0,
                reason="no audit-eligible edges in this chain",
            )
            for alarm_id in graph.members
        }
    articulation_points, components_after_removal = _articulation_analysis(graph)
    return {
        alarm_id: _structural_role_result(
            alarm_id,
            articulation_points=articulation_points,
            blocks_supported=components_after_removal[alarm_id],
        )
        for alarm_id in graph.members
    }


def classify_structural_role(
    alarm_id: str, graph: AuditGraph
) -> StructuralRoleResult:
    """Classify one member's structural role."""
    if alarm_id not in graph.members:
        return StructuralRoleResult(
            alarm_id=alarm_id,
            role=StructuralRole.NOT_APPLICABLE,
            is_articulation_point=False,
            blocks_supported=0,
            reason="alarm is not a member of this chain's audit graph",
        )
    return classify_structural_roles(graph)[alarm_id]
