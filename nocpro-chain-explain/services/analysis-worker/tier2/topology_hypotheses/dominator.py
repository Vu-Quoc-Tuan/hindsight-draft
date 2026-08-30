"""Deterministic exact common strict-dominator analysis for one alarm chain."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from channels.dependency import ResourceResolver
from libs.contracts import IngestedPackage
from libs.provenance import ProvenanceClass, ProvenanceSubtype

from .models import (
    DirectedUniverse,
    DominatorResult,
    HypothesisStatus,
    TopologyHypothesisReason,
)


ELIGIBLE_RELATION_TYPES = frozenset({"LOGICAL_DEPENDENCY", "SERVICE_DEPENDS_ON"})


def _source_ref(edge: dict) -> tuple[str, str] | None:
    """Return an exact source identity; never normalize or invent one."""
    source_id = edge.get("source_id")
    source_version = edge.get("source_version")
    if (
        not isinstance(source_id, str)
        or not isinstance(source_version, str)
        or not source_id.strip()
        or not source_version.strip()
    ):
        return None
    return f"{source_id}@{source_version}", source_version


def _provenance_signature(
    edges: Iterable[dict],
) -> tuple[ProvenanceClass, ProvenanceSubtype | None, str | None] | None:
    """Return one exact provenance signature, rejecting a mixed source group."""
    signatures: set[tuple[ProvenanceClass, ProvenanceSubtype | None, str | None]] = set()
    for edge in edges:
        try:
            provenance_class = ProvenanceClass(
                edge.get("provenance_class", ProvenanceClass.EXTERNAL_OPERATIONAL.value)
            )
            raw_subtype = (
                edge["provenance_subtype"]
                if "provenance_subtype" in edge
                else ProvenanceSubtype.TOPOLOGY_EXTERNAL.value
            )
            provenance_subtype = (
                ProvenanceSubtype(raw_subtype) if raw_subtype is not None else None
            )
        except ValueError:
            return None
        signatures.add((provenance_class, provenance_subtype, edge.get("source_kind")))
    return next(iter(signatures)) if len(signatures) == 1 else None


def build_directed_universes(package: IngestedPackage) -> tuple[DirectedUniverse, ...]:
    """Build isolated eligible directed universes from canonical topology edges.

    The grouping key intentionally includes both the source identity/version and
    relation type.  In particular, this function never infers direction and
    never accepts ``IP_ADJACENCY``.
    """
    grouped: dict[tuple[str, str, str | None], list[dict]] = {}
    for edge in package.topology.get("edges") or ():
        relation_type = edge.get("relation_type")
        if relation_type not in ELIGIBLE_RELATION_TYPES or not edge.get("directed"):
            continue
        source = edge.get("source_resource_id")
        target = edge.get("target_resource_id")
        if not source or not target:
            continue
        source_identity = _source_ref(edge)
        if source_identity is None:
            # A snapshot-wide version cannot establish that independently
            # supplied edges belong to one source/version universe.
            continue
        source_ref, source_version = source_identity
        grouped.setdefault((source_ref, relation_type, source_version), []).append(edge)

    universes: list[DirectedUniverse] = []
    for (source_ref, relation_type, source_version), edges in sorted(grouped.items()):
        provenance = _provenance_signature(edges)
        if provenance is None:
            # One universe cannot claim a provenance that its source did not
            # supply consistently, so it is not eligible for P2 semantics.
            continue
        provenance_class, provenance_subtype, source_kind = provenance
        nodes = sorted(
            {
                resource_id
                for edge in edges
                for resource_id in (
                    edge["source_resource_id"],
                    edge["target_resource_id"],
                )
            }
        )
        predecessor_sets = {node: set() for node in nodes}
        successor_sets = {node: set() for node in nodes}
        for edge in edges:
            source = edge["source_resource_id"]
            target = edge["target_resource_id"]
            successor_sets[source].add(target)
            predecessor_sets[target].add(source)
        universes.append(
            DirectedUniverse(
                source_ref=source_ref,
                relation_type=relation_type,
                nodes=tuple(nodes),
                predecessors={node: tuple(sorted(predecessor_sets[node])) for node in nodes},
                successors={node: tuple(sorted(successor_sets[node])) for node in nodes},
                provenance_class=provenance_class,
                provenance_subtype=provenance_subtype,
                source_kind=source_kind,
                source_version=source_version,
            )
        )
    return tuple(universes)


def _dominators(
    universe: DirectedUniverse,
) -> dict[str, set[str]] | None:
    """Compute real-node dominator sets via a virtual super-root fixed point."""
    roots = tuple(node for node in universe.nodes if not universe.predecessors[node])
    if not roots:
        return None

    virtual_root = object()
    successors: dict[object | str, tuple[object | str, ...]] = {
        node: universe.successors[node] for node in universe.nodes
    }
    successors[virtual_root] = roots
    reachable: set[object | str] = {virtual_root}
    queue: deque[object | str] = deque([virtual_root])
    while queue:
        node = queue.popleft()
        for successor in successors[node]:
            if successor not in reachable:
                reachable.add(successor)
                queue.append(successor)
    if any(node not in reachable for node in universe.nodes):
        return None

    predecessors: dict[object | str, tuple[object | str, ...]] = {
        node: universe.predecessors[node] for node in universe.nodes
    }
    for root in roots:
        predecessors[root] = (virtual_root,)
    all_nodes: set[object | str] = {virtual_root, *universe.nodes}
    dom: dict[object | str, set[object | str]] = {virtual_root: {virtual_root}}
    dom.update({node: set(all_nodes) for node in universe.nodes})

    changed = True
    while changed:
        changed = False
        for node in universe.nodes:
            predecessor_doms = [dom[parent] for parent in predecessors[node]]
            candidate: set[object | str] = {node} | set.intersection(*predecessor_doms)
            if candidate != dom[node]:
                dom[node] = candidate
                changed = True

    return {
        node: {dominator for dominator in dom[node] if isinstance(dominator, str)}
        for node in universe.nodes
    }


def _deepest_common_witness(
    dominators: dict[str, set[str]], resources: tuple[str, ...]
) -> tuple[str | None, bool]:
    """Return ``(witness, is_ambiguous)`` without applying a tie-break."""
    common = set.intersection(*(dominators[resource] - {resource} for resource in resources))
    if not common:
        return None, False
    deepest = [node for node in sorted(common) if common <= dominators[node]]
    return (deepest[0], False) if len(deepest) == 1 else (None, True)


def _unavailable(reason: TopologyHypothesisReason) -> DominatorResult:
    return DominatorResult(
        status=HypothesisStatus.UNAVAILABLE,
        reason=reason,
        semantic=None,
        witness_resource_id=None,
        covered_resource_ids=(),
        source_ref=None,
        relation_type=None,
        provenance_class=None,
        provenance_subtype=None,
        source_kind=None,
    )


def analyze_common_dominator(package: IngestedPackage, chain_id: str) -> DominatorResult:
    """Return an exact common strict dominator or a structured unavailable result."""
    resolver = ResourceResolver.from_package(package)
    member_alarm_ids = tuple(package.members_of(chain_id))
    resolved_resources = [
        resolver.resource_of(alarm_id) for alarm_id in member_alarm_ids
    ]
    if not member_alarm_ids or any(resource is None for resource in resolved_resources):
        return _unavailable(TopologyHypothesisReason.RESOURCE_MAPPING_UNAVAILABLE)
    mapped_resources = tuple(sorted(set(resolved_resources)))

    universes = build_directed_universes(package)
    if not universes:
        return _unavailable(TopologyHypothesisReason.DIRECTED_TOPOLOGY_UNAVAILABLE)

    candidates: list[tuple[DirectedUniverse, str]] = []
    ambiguous_within_universe = False
    for universe in universes:
        if any(resource not in universe.nodes for resource in mapped_resources):
            continue
        dominators = _dominators(universe)
        if dominators is None:
            continue
        witness, is_ambiguous = _deepest_common_witness(dominators, mapped_resources)
        ambiguous_within_universe = ambiguous_within_universe or is_ambiguous
        if witness is not None:
            candidates.append((universe, witness))

    if ambiguous_within_universe:
        return _unavailable(TopologyHypothesisReason.AMBIGUOUS_DOMINATOR_WITNESS)
    if not candidates:
        return _unavailable(TopologyHypothesisReason.COMMON_DOMINATOR_UNAVAILABLE)
    if len(candidates) != 1:
        return _unavailable(TopologyHypothesisReason.AMBIGUOUS_DOMINATOR_WITNESS)

    universe, witness = candidates[0]
    return DominatorResult(
        status=HypothesisStatus.AVAILABLE,
        reason=None,
        semantic="UNAVOIDABLE_DEPENDENCY",
        witness_resource_id=witness,
        covered_resource_ids=mapped_resources,
        source_ref=universe.source_ref,
        relation_type=universe.relation_type,
        provenance_class=universe.provenance_class,
        provenance_subtype=universe.provenance_subtype,
        source_kind=universe.source_kind,
        universe=universe,
    )
