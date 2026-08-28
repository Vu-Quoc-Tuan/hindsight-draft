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


def find_articulation_points(graph: AuditGraph) -> set[str]:
    """Classic articulation-point DFS over the audit graph's adjacency.

    A node whose removal increases the number of connected components.
    """
    adjacency = {node: set(neighbours) for node, neighbours in graph.adjacency.items()}
    for node in graph.members:
        adjacency.setdefault(node, set())

    visited: set[str] = set()
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    articulation: set[str] = set()
    timer = [0]

    def dfs(node: str, parent: str | None) -> None:
        visited.add(node)
        discovery[node] = low[node] = timer[0]
        timer[0] += 1
        child_count = 0

        for neighbour in adjacency.get(node, ()):
            if neighbour == parent:
                continue
            if neighbour in visited:
                low[node] = min(low[node], discovery[neighbour])
                continue
            child_count += 1
            dfs(neighbour, node)
            low[node] = min(low[node], low[neighbour])
            if parent is not None and low[neighbour] >= discovery[node]:
                articulation.add(node)

        if parent is None and child_count > 1:
            # A root with >= 2 DFS subtrees is itself an articulation point.
            articulation.add(node)

    for node in graph.members:
        if node not in visited:
            dfs(node, None)

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

    if not graph.edges:
        return StructuralRoleResult(
            alarm_id=alarm_id,
            role=StructuralRole.NOT_APPLICABLE,
            is_articulation_point=False,
            blocks_supported=0,
            reason="no audit-eligible edges in this chain",
        )

    articulation_points = find_articulation_points(graph)
    is_articulation = alarm_id in articulation_points
    components_without = connected_components(graph, exclude=alarm_id)
    blocks_supported = len(components_without)

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
