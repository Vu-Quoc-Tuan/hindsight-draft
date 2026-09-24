"""Dependency channel ``Dep_hop`` (§4A, P0).

    s+ = 1/(1+d), edge <=> d <= D_max

Hard constraints:
- alarm->resource mapping is mandatory; unmapped => ⊥ (never 0.0);
- PHYSICAL / LOGICAL / SERVICE relation types are never mixed;
- undirected adjacency yields hop distance only. It must not enable
  SHARED_ACTIVE_PATH or dominator claims (ADR-MOCK-0005, ADR-0032).

Provenance depends on where the topology came from: ``TOPOLOGY_EXTERNAL`` when it
is inventory/NMS/export outside the alarm pipeline, ``POST_HOC`` when it was
inferred from the alarm data itself. Those are different derivation groups.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from libs.contracts import IngestedAlarm, IngestedPackage
from libs.contracts.topology_mapping import resolve_topology_mappings
from libs.contracts.topology_paths import shortest_path as find_shortest_path
from libs.provenance import ProvenanceClass, ProvenanceSubtype
from topology_source import (
    TOPOLOGY_SOURCE_VERSION_MISSING,
    consistent_topology_trace,
    has_missing_topology_source,
)

from .base import ChannelValue, unavailable

CHANNEL_ID = "Dep_hop"
DERIVATION_TAG = "dependency_hop"

#: Default max hop distance for an edge to exist.
DEFAULT_D_MAX = 3

#: Relation families that must never be mixed in one traversal.
PHYSICAL_RELATIONS = frozenset({"IP_ADJACENCY"})
LOGICAL_RELATIONS = frozenset({"LOGICAL_DEPENDENCY"})
SERVICE_RELATIONS = frozenset({"SERVICE_DEPENDS_ON"})


@dataclass
class TopologyGraph:
    """Adjacency for one relation family.

    ``directed`` reflects the source. An undirected graph supports distance only.
    """

    relation_types: frozenset[str]
    adjacency: dict[str, set[str]] = field(default_factory=dict)
    directed: bool = False
    edge_relation_types: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    directed_edges: set[tuple[str, str]] = field(default_factory=set)
    #: EXTERNAL_OPERATIONAL for inventory/NMS exports, POST_HOC if alarm-derived.
    provenance_class: ProvenanceClass = ProvenanceClass.EXTERNAL_OPERATIONAL
    provenance_subtype: ProvenanceSubtype | None = ProvenanceSubtype.TOPOLOGY_EXTERNAL
    unavailable_reason: str | None = None
    source_ref: str | None = None
    source_id: str | None = None
    source_version: str | None = None
    scenario_id: str | None = None
    generator_version: str | None = None

    def neighbours(self, node: str) -> set[str]:
        return self.adjacency.get(node, set())

    def reachable_within(self, source: str, *, max_depth: int) -> set[str]:
        """Resources reachable from ``source`` within the bounded relation graph."""
        reached = {source}
        queue: deque[tuple[str, int]] = deque([(source, 0)])
        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbour in self.neighbours(node):
                if neighbour in reached:
                    continue
                reached.add(neighbour)
                queue.append((neighbour, depth + 1))
        return reached

    def hop_distance(self, source: str, target: str, *, max_depth: int) -> int | None:
        """BFS distance, or ``None`` when unreachable within ``max_depth``."""
        path = self.path(source, target, max_hops=max_depth)
        return len(path) - 1 if path is not None else None

    def path(self, source: str, target: str, *, max_hops: int) -> list[str] | None:
        """Return the same bounded witness used to derive the hop distance."""
        return find_shortest_path(
            self.adjacency, source, target, max_hops=max_hops
        )


def build_topology_graph(
    package: IngestedPackage,
    *,
    relation_types: frozenset[str] = PHYSICAL_RELATIONS,
) -> TopologyGraph:
    """Build a graph from ingested topology edges for one relation family."""
    graph = TopologyGraph(relation_types=relation_types)
    directed_seen = False
    eligible_edges: list[dict] = []
    signatures: set[tuple[ProvenanceClass, ProvenanceSubtype | None]] = set()

    for edge in package.topology.get("edges") or ():
        relation = edge.get("relation_type")
        if relation not in relation_types:
            # Mixing relation families would invent semantics.
            continue
        source = edge.get("source_resource_id")
        target = edge.get("target_resource_id")
        if not source or not target:
            continue

        try:
            provenance_class = ProvenanceClass(
                edge.get("provenance_class", ProvenanceClass.EXTERNAL_OPERATIONAL.value)
            )
            provenance_subtype = (
                ProvenanceSubtype(
                    edge.get(
                        "provenance_subtype",
                        ProvenanceSubtype.TOPOLOGY_EXTERNAL.value,
                    )
                )
                if provenance_class is ProvenanceClass.EXTERNAL_OPERATIONAL
                else None
            )
        except ValueError:
            graph.unavailable_reason = "invalid topology provenance metadata"
            return graph
        signatures.add((provenance_class, provenance_subtype))
        eligible_edges.append(edge)

    if len(signatures) > 1:
        graph.unavailable_reason = (
            "mixed provenance in one topology relation family; split providers "
            "before computing Dep_hop"
        )
        return graph
    if eligible_edges and has_missing_topology_source(eligible_edges):
        graph.unavailable_reason = TOPOLOGY_SOURCE_VERSION_MISSING
        return graph
    traces = {
        consistent_topology_trace((edge,)) for edge in eligible_edges
    }
    if len(traces) > 1:
        graph.unavailable_reason = (
            "mixed topology source identities in one relation family"
        )
        return graph
    if traces:
        trace = next(iter(traces))
        assert trace is not None
        graph.source_ref = trace.source_ref
        graph.source_id = trace.source_id
        graph.source_version = trace.source_version
        graph.scenario_id = trace.scenario_id
        graph.generator_version = trace.generator_version
    if signatures:
        graph.provenance_class, graph.provenance_subtype = next(iter(signatures))

    for edge in eligible_edges:
        source = edge["source_resource_id"]
        target = edge["target_resource_id"]
        relation = str(edge["relation_type"])
        graph.adjacency.setdefault(source, set()).add(target)
        graph.edge_relation_types.setdefault((source, target), set()).add(relation)
        if edge.get("directed"):
            directed_seen = True
            graph.directed_edges.add((source, target))
            graph.adjacency.setdefault(target, set())
        else:
            graph.adjacency.setdefault(target, set()).add(source)
            graph.edge_relation_types.setdefault((target, source), set()).add(relation)

    graph.directed = directed_seen
    return graph


@dataclass
class ResourceResolver:
    """alarm_id -> resource_id, honouring ingested mapping status.

    Only unique, recognized mapping claims resolve. Conflicting, UNMAPPED,
    and AMBIGUOUS claims force ``Dep_hop`` to ⊥.
    """

    resolved: dict[str, str] = field(default_factory=dict)
    mapping_statuses: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_package(cls, package: IngestedPackage) -> ResourceResolver:
        resolved_rows = resolve_topology_mappings(
            package.topology.get("mappings") or ()
        ) or {}
        return cls(
            resolved={alarm_id: row["resource_id"] for alarm_id, row in resolved_rows.items()},
            mapping_statuses={
                alarm_id: str(getattr(row.get("mapping_status"), "value", row.get("mapping_status")))
                for alarm_id, row in resolved_rows.items()
            },
        )

    def resource_of(self, alarm_id: str) -> str | None:
        return self.resolved.get(alarm_id)


def evaluate_dep_hop_channel(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    *,
    graph: TopologyGraph | None,
    resolver: ResourceResolver,
    d_max: int = DEFAULT_D_MAX,
) -> ChannelValue:
    """Evaluate ``Dep_hop`` for a pair."""
    threshold = 1.0 / (1.0 + d_max)

    def fail(reason: str) -> ChannelValue:
        return unavailable(
            CHANNEL_ID,
            DERIVATION_TAG,
            graph.provenance_class if graph else ProvenanceClass.EXTERNAL_OPERATIONAL,
            reason=reason,
            threshold=threshold,
            provenance_subtype=(
                graph.provenance_subtype
                if graph
                else ProvenanceSubtype.TOPOLOGY_EXTERNAL
            ),
            source_ref=graph.source_ref if graph else None,
            source_id=graph.source_id if graph else None,
            source_version=graph.source_version if graph else None,
            scenario_id=graph.scenario_id if graph else None,
            generator_version=graph.generator_version if graph else None,
        )

    if graph is None or not graph.adjacency:
        return fail(
            graph.unavailable_reason
            if graph and graph.unavailable_reason
            else "no topology loaded for this relation type"
        )

    resource_a = resolver.resource_of(alarm_a.alarm_id)
    resource_b = resolver.resource_of(alarm_b.alarm_id)
    if resource_a is None or resource_b is None:
        # The DEHL01/DEHT01 case: mapping failed, so no topology evidence.
        return fail("alarm->resource mapping unresolved (UNMAPPED/AMBIGUOUS)")

    path = graph.path(resource_a, resource_b, max_hops=d_max)
    if path is None:
        # Reachability beyond D_max is genuinely unknown here, not "far".
        return fail(f"no path within D_max={d_max}")
    distance = len(path) - 1
    path_relation_types = {
        relation
        for source, target in zip(path, path[1:])
        for relation in graph.edge_relation_types.get((source, target), ())
    }
    if not path_relation_types:
        # Compatibility for small in-memory graphs created without edge metadata.
        path_relation_types = set(graph.relation_types)
    edge_relation_types: list[str] = []
    for source, target in zip(path, path[1:]):
        edge_relations = graph.edge_relation_types.get((source, target), set())
        if not edge_relations:
            edge_relations = set(graph.relation_types)
        if len(edge_relations) != 1:
            edge_relation_types = []
            break
        edge_relation_types.append(next(iter(edge_relations)))
    path_uses_directed_edge = any(
        (source, target) in graph.directed_edges
        for source, target in zip(path, path[1:])
    )

    return ChannelValue(
        channel_id=CHANNEL_ID,
        derivation_tag=DERIVATION_TAG,
        provenance_class=graph.provenance_class,
        provenance_subtype=graph.provenance_subtype,
        availability=True,
        positive_score=1.0 / (1.0 + distance),
        threshold=threshold,
        detail=f"hop distance {distance} over {sorted(path_relation_types)}",
        source_ref=graph.source_ref,
        source_id=graph.source_id,
        source_version=graph.source_version,
        scenario_id=graph.scenario_id,
        generator_version=graph.generator_version,
        evidence_metadata={
            "topology_path": {
                "nodes": path,
                "hop_count": distance,
                "max_hops": d_max,
                "relation_types": sorted(path_relation_types),
                "edge_relation_types": edge_relation_types,
                "mapping_statuses": sorted({
                    status
                    for alarm_id in (alarm_a.alarm_id, alarm_b.alarm_id)
                    if (status := resolver.mapping_statuses.get(alarm_id))
                }),
                "traversal_semantic": "STRUCTURAL_TOPOLOGY_PATH_NOT_CAUSAL",
                "direction_policy": (
                    "SOURCE_EDGE_DIRECTION_PRESERVED"
                    if path_uses_directed_edge else "UNDIRECTED"
                ),
            }
        },
    )
