"""Deterministic bounded read-model for displaying an exact Audit graph.

This module is downstream of every structural computation.  Its output is a
VISUALIZATION projection only and must never be passed back into Audit, roles,
or Counterfactual evaluation (ADR-0016).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from audit import AuditGraph, StructuralAuditResult, StructuralRoleResult


AUDIT_VISUALIZATION_VERSION = "audit-visualization-v1"
AUDIT_VISUALIZATION_MAX_NODES = 80
AUDIT_VISUALIZATION_MAX_EDGES = 160
AUDIT_VISUALIZATION_SELECTION_STRATEGY = "BEST_CUT_BALANCED_WEIGHTED_DEGREE_V1"

CutSide = Literal["A", "B", "NONE"]


@dataclass(frozen=True)
class AuditVisualizationNode:
    alarm_id: str
    weighted_degree: float
    cut_side: CutSide
    structural_role: str | None


@dataclass(frozen=True)
class AuditVisualizationEdge:
    source_alarm_id: str
    target_alarm_id: str
    weight: float
    supporting_groups: tuple[str, ...]
    crosses_best_cut: bool


@dataclass(frozen=True)
class AuditVisualization:
    status: str
    reason: str | None
    projection_version: str
    selection_strategy: str
    max_nodes: int
    max_edges: int
    total_node_count: int
    shown_node_count: int
    hidden_node_count: int
    total_edge_count: int
    shown_edge_count: int
    hidden_edge_count: int
    truncated: bool
    nodes: tuple[AuditVisualizationNode, ...]
    edges: tuple[AuditVisualizationEdge, ...]


def unavailable_audit_visualization(
    reason: str,
    *,
    total_node_count: int = 0,
) -> AuditVisualization:
    return AuditVisualization(
        status="UNAVAILABLE",
        reason=reason,
        projection_version=AUDIT_VISUALIZATION_VERSION,
        selection_strategy=AUDIT_VISUALIZATION_SELECTION_STRATEGY,
        max_nodes=AUDIT_VISUALIZATION_MAX_NODES,
        max_edges=AUDIT_VISUALIZATION_MAX_EDGES,
        total_node_count=total_node_count,
        shown_node_count=0,
        hidden_node_count=total_node_count,
        total_edge_count=0,
        shown_edge_count=0,
        hidden_edge_count=0,
        truncated=total_node_count > 0,
        nodes=(),
        edges=(),
    )


def _ranked_members(
    members: set[str], weighted_degree: Mapping[str, float]
) -> list[str]:
    return sorted(members, key=lambda alarm_id: (-weighted_degree[alarm_id], alarm_id))


def _select_members(
    members: set[str],
    weighted_degree: Mapping[str, float],
    side_a: set[str] | None,
) -> set[str]:
    if len(members) <= AUDIT_VISUALIZATION_MAX_NODES:
        return members
    if side_a and side_a < members:
        side_b = members - side_a
        side_slots = AUDIT_VISUALIZATION_MAX_NODES // 2
        selected_a = _ranked_members(side_a, weighted_degree)[:side_slots]
        selected_b = _ranked_members(side_b, weighted_degree)[:side_slots]
        unused = AUDIT_VISUALIZATION_MAX_NODES - len(selected_a) - len(selected_b)
        if unused:
            remaining = (side_a | side_b) - set(selected_a) - set(selected_b)
            extra = _ranked_members(remaining, weighted_degree)[:unused]
            return set(selected_a) | set(selected_b) | set(extra)
        return set(selected_a) | set(selected_b)
    return set(_ranked_members(members, weighted_degree)[:AUDIT_VISUALIZATION_MAX_NODES])


def build_audit_visualization(
    graph: AuditGraph,
    structural_audit: StructuralAuditResult,
    structural_roles: Mapping[str, StructuralRoleResult],
) -> AuditVisualization:
    """Project an exact graph into the frozen presentation bounds."""
    members = set(graph.members)
    weighted_degree = {
        alarm_id: sum(graph.neighbours(alarm_id).values()) for alarm_id in members
    }
    best_cut = structural_audit.best_cut
    side_a = set(best_cut.candidate.members) & members if best_cut is not None else None
    selected = _select_members(members, weighted_degree, side_a)

    nodes = tuple(
        AuditVisualizationNode(
            alarm_id=alarm_id,
            weighted_degree=weighted_degree[alarm_id],
            cut_side=(
                "NONE"
                if side_a is None
                else "A"
                if alarm_id in side_a
                else "B"
            ),
            structural_role=(
                structural_roles[alarm_id].role.value
                if alarm_id in structural_roles
                else None
            ),
        )
        for alarm_id in sorted(selected)
    )

    eligible_edges: list[AuditVisualizationEdge] = []
    for edge in graph.edges:
        source, target = sorted((edge.node_a, edge.node_b))
        if source not in selected or target not in selected:
            continue
        eligible_edges.append(
            AuditVisualizationEdge(
                source_alarm_id=source,
                target_alarm_id=target,
                weight=edge.weight,
                supporting_groups=tuple(sorted(set(edge.supporting_groups))),
                crosses_best_cut=(
                    side_a is not None and ((source in side_a) != (target in side_a))
                ),
            )
        )
    eligible_edges.sort(
        key=lambda edge: (-edge.weight, edge.source_alarm_id, edge.target_alarm_id)
    )
    edges = tuple(eligible_edges[:AUDIT_VISUALIZATION_MAX_EDGES])
    total_nodes = len(members)
    total_edges = len(graph.edges)
    return AuditVisualization(
        status="AVAILABLE",
        reason=None,
        projection_version=AUDIT_VISUALIZATION_VERSION,
        selection_strategy=AUDIT_VISUALIZATION_SELECTION_STRATEGY,
        max_nodes=AUDIT_VISUALIZATION_MAX_NODES,
        max_edges=AUDIT_VISUALIZATION_MAX_EDGES,
        total_node_count=total_nodes,
        shown_node_count=len(nodes),
        hidden_node_count=total_nodes - len(nodes),
        total_edge_count=total_edges,
        shown_edge_count=len(edges),
        hidden_edge_count=total_edges - len(edges),
        truncated=total_nodes != len(nodes) or total_edges != len(edges),
        nodes=nodes,
        edges=edges,
    )
