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
from libs.provenance import ProvenanceClass, ProvenanceSubtype

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
    #: EXTERNAL_OPERATIONAL for inventory/NMS exports, POST_HOC if alarm-derived.
    provenance_class: ProvenanceClass = ProvenanceClass.EXTERNAL_OPERATIONAL
    provenance_subtype: ProvenanceSubtype | None = ProvenanceSubtype.TOPOLOGY_EXTERNAL

    def neighbours(self, node: str) -> set[str]:
        return self.adjacency.get(node, set())

    def hop_distance(self, source: str, target: str, *, max_depth: int) -> int | None:
        """BFS distance, or ``None`` when unreachable within ``max_depth``."""
        if source == target:
            return 0
        if source not in self.adjacency or target not in self.adjacency:
            return None

        seen = {source}
        queue: deque[tuple[str, int]] = deque([(source, 0)])
        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbour in self.neighbours(node):
                if neighbour == target:
                    return depth + 1
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append((neighbour, depth + 1))
        return None


def build_topology_graph(
    package: IngestedPackage,
    *,
    relation_types: frozenset[str] = PHYSICAL_RELATIONS,
) -> TopologyGraph:
    """Build a graph from ingested topology edges for one relation family."""
    graph = TopologyGraph(relation_types=relation_types)
    directed_seen = False

    for edge in package.topology.get("edges") or ():
        relation = edge.get("relation_type")
        if relation not in relation_types:
            # Mixing relation families would invent semantics.
            continue
        source = edge.get("source_resource_id")
        target = edge.get("target_resource_id")
        if not source or not target:
            continue

        graph.adjacency.setdefault(source, set()).add(target)
        if edge.get("directed"):
            directed_seen = True
            graph.adjacency.setdefault(target, set())
        else:
            graph.adjacency.setdefault(target, set()).add(source)

    graph.directed = directed_seen
    return graph


@dataclass
class ResourceResolver:
    """alarm_id -> resource_id, honouring ingested mapping status.

    Only EXACT and VERIFIED_ALIAS mappings resolve. UNMAPPED and AMBIGUOUS do
    not, which is what forces ``Dep_hop`` to ⊥.
    """

    resolved: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_package(cls, package: IngestedPackage) -> ResourceResolver:
        resolved: dict[str, str] = {}
        for mapping in package.topology.get("mappings") or ():
            status = mapping.get("mapping_status")
            resource_id = mapping.get("resource_id")
            alarm_id = mapping.get("alarm_id")
            if not alarm_id or not resource_id:
                continue
            if status in ("EXACT", "VERIFIED_ALIAS"):
                resolved[alarm_id] = resource_id
        return cls(resolved=resolved)

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
        )

    if graph is None or not graph.adjacency:
        return fail("no topology loaded for this relation type")

    resource_a = resolver.resource_of(alarm_a.alarm_id)
    resource_b = resolver.resource_of(alarm_b.alarm_id)
    if resource_a is None or resource_b is None:
        # The DEHL01/DEHT01 case: mapping failed, so no topology evidence.
        return fail("alarm->resource mapping unresolved (UNMAPPED/AMBIGUOUS)")

    distance = graph.hop_distance(resource_a, resource_b, max_depth=d_max)
    if distance is None:
        # Reachability beyond D_max is genuinely unknown here, not "far".
        return fail(f"no path within D_max={d_max}")

    return ChannelValue(
        channel_id=CHANNEL_ID,
        derivation_tag=DERIVATION_TAG,
        provenance_class=graph.provenance_class,
        provenance_subtype=graph.provenance_subtype,
        availability=True,
        positive_score=1.0 / (1.0 + distance),
        threshold=threshold,
        detail=f"hop distance {distance} over {sorted(graph.relation_types)}",
    )
