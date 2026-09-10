"""Bounded, non-semantic tree projections of normalized topology relations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping

from ..loaders.topology_it_csv import TopologyRelationEdge, TopologyRelationNode

ReferenceKind = Literal["CYCLE", "MULTI_PARENT"]

_RELATION_PRIORITY = {
    "SERVICE_HAS_MODULE": 0,
    "MODULE_HAS_INSTANCE": 1,
    "MODULE_LINKS_DATABASE": 2,
    "DATABASE_LINKS_SERVICE": 3,
    "DATABASE_LINKS_INSTANCE": 4,
    "INSTANCE_LINKS_STORAGE": 5,
}
_TYPE_PRIORITY = {"SERVICE": 0, "MODULE": 1, "INSTANCE": 2, "DATABASE": 3, "STORAGE": 4}


@dataclass(frozen=True)
class TopologyProjectionNode:
    resource_id: str
    resource_type: str
    display_name: str
    relation_type: str | None
    source_table: str | None
    children: tuple["TopologyProjectionNode", ...] = ()
    hidden_child_count: int = 0
    reference_kind: ReferenceKind | None = None
    linked_parent_count: int = 0
    source_port: str | None = None
    target_port: str | None = None

    @property
    def expandable(self) -> bool:
        return self.reference_kind is None and bool(self.children or self.hidden_child_count)


@dataclass(frozen=True)
class TopologyTreeProjection:
    root: TopologyProjectionNode
    direction_kind: str
    dependency_semantics: str
    semantic_notice: str
    source_version: str


@dataclass(frozen=True)
class NavigationRelationEdge:
    """UI-only edge shape shared by source-relation and adjacency projections."""

    source_id: str
    target_id: str
    relation_type: str
    source_table: str
    source_version: str
    source_port: str | None = None
    target_port: str | None = None


def project_relation_tree(
    nodes: Iterable[TopologyRelationNode],
    edges: Iterable[TopologyRelationEdge | NavigationRelationEdge],
    *,
    root_id: str,
    max_depth: int = 3,
    max_children: int = 50,
) -> TopologyTreeProjection:
    """Return one deterministic navigation projection of a directed graph.

    The primary occurrence order is a rendering policy only.  It intentionally
    has no owner/dependency semantics.
    """
    if max_depth < 0 or max_children < 1:
        raise ValueError("max_depth must be >= 0 and max_children must be >= 1")
    node_map: Mapping[str, TopologyRelationNode] = {node.resource_id: node for node in nodes}
    if root_id not in node_map:
        raise ValueError(f"projection root does not exist: {root_id}")
    outgoing: dict[str, list[TopologyRelationEdge | NavigationRelationEdge]] = defaultdict(list)
    incoming_count: dict[str, int] = defaultdict(int)
    for edge in edges:
        if edge.source_id in node_map and edge.target_id in node_map:
            outgoing[edge.source_id].append(edge)
            incoming_count[edge.target_id] += 1
    for source_id, values in outgoing.items():
        values.sort(key=lambda edge: (_RELATION_PRIORITY.get(edge.relation_type, 99), _TYPE_PRIORITY.get(node_map[edge.target_id].resource_type, 99), edge.target_id, edge.source_table))

    primary_seen = {root_id}

    def build(node_id: str, relation: TopologyRelationEdge | NavigationRelationEdge | None, path: frozenset[str], depth: int) -> TopologyProjectionNode:
        node = node_map[node_id]
        src_port = getattr(relation, "source_port", None)
        tgt_port = getattr(relation, "target_port", None)
        if depth >= max_depth:
            return TopologyProjectionNode(
                node_id,
                node.resource_type,
                node.display_name,
                relation.relation_type if relation else None,
                relation.source_table if relation else None,
                source_port=src_port,
                target_port=tgt_port,
            )
        rendered: list[TopologyProjectionNode] = []
        hidden = 0
        for edge in outgoing.get(node_id, ()): 
            if len(rendered) >= max_children:
                hidden += 1
                continue
            child = node_map[edge.target_id]
            e_src_port = getattr(edge, "source_port", None)
            e_tgt_port = getattr(edge, "target_port", None)
            if child.resource_id in path:
                rendered.append(
                    TopologyProjectionNode(
                        child.resource_id,
                        child.resource_type,
                        child.display_name,
                        edge.relation_type,
                        edge.source_table,
                        reference_kind="CYCLE",
                        source_port=e_src_port,
                        target_port=e_tgt_port,
                    )
                )
                continue
            if child.resource_id in primary_seen:
                rendered.append(
                    TopologyProjectionNode(
                        child.resource_id,
                        child.resource_type,
                        child.display_name,
                        edge.relation_type,
                        edge.source_table,
                        reference_kind="MULTI_PARENT",
                        linked_parent_count=max(1, incoming_count[child.resource_id] - 1),
                        source_port=e_src_port,
                        target_port=e_tgt_port,
                    )
                )
                continue
            primary_seen.add(child.resource_id)
            rendered.append(build(child.resource_id, edge, path | {child.resource_id}, depth + 1))
        return TopologyProjectionNode(
            node_id,
            node.resource_type,
            node.display_name,
            relation.relation_type if relation else None,
            relation.source_table if relation else None,
            tuple(rendered),
            hidden,
            source_port=src_port,
            target_port=tgt_port,
        )

    source_version = next((edge.source_version for items in outgoing.values() for edge in items), "UNKNOWN")
    return TopologyTreeProjection(
        root=build(root_id, None, frozenset({root_id}), 0),
        direction_kind="SOURCE_RELATION",
        dependency_semantics="UNVERIFIED",
        semantic_notice="This relation-tree projection is for navigation. It does not imply dependency, causality, ownership, or propagation direction.",
        source_version=source_version,
    )


def project_adjacency_tree(
    nodes: Iterable[TopologyRelationNode],
    edges: Iterable[NavigationRelationEdge],
    *,
    root_id: str,
    max_depth: int = 3,
    max_children: int = 50,
) -> TopologyTreeProjection:
    """Project an undirected adjacency graph without claiming a hierarchy."""
    doubled = tuple(
        direction
        for edge in edges
        for direction in (
            edge,
            NavigationRelationEdge(
                edge.target_id,
                edge.source_id,
                edge.relation_type,
                edge.source_table,
                edge.source_version,
                source_port=edge.target_port,
                target_port=edge.source_port,
            ),
        )
    )
    projection = project_relation_tree(nodes, doubled, root_id=root_id, max_depth=max_depth, max_children=max_children)
    return TopologyTreeProjection(
        root=projection.root,
        direction_kind="NONE",
        dependency_semantics="UNAVAILABLE",
        semantic_notice="This adjacency-tree projection is for navigation. It does not imply dependency, causality, ownership, or propagation direction.",
        source_version=projection.source_version,
    )
