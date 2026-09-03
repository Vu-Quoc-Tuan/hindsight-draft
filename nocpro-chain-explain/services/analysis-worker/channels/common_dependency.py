"""CommonDependency capability engine (§4A, ADR-0032, D1-6, P1-Core item 1).

Three semantic tiers, strictly capability-gated:

    SHARED_ANCESTOR < SHARED_ACTIVE_PATH < UNAVOIDABLE_DEPENDENCY

That ``<`` is a **semantic strength** ordering, not a numeric constraint on the
score: a narrow ancestor may score higher than a shared active-core-path,
because ``CD`` depends on scope specificity and distance of the witnessing node,
not on which tier it belongs to. Do not fold the tier into ``CD`` as a hidden
multiplier; keep ``dependency_semantic`` and ``strength=CD`` separate.

Specificity is **scope-dependent**: ``Descendants(u)`` is only a natural scope
for the hierarchy tier. The active-path tier uses distinct traversing resources
within the same path-observation universe, never the whole topology inventory.

    Specificity_s(u) = log(1 + N_s / |Scope_s(u)|) / log(1 + N_s)   in [0,1]

Fail-closed: missing directed hierarchy => SHARED_ANCESTOR is UNAVAILABLE.
Missing verified ordered active-path data => SHARED_ACTIVE_PATH is UNAVAILABLE,
and a graph-adjacency shortest path is never substituted for it.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from libs.contracts import IngestedAlarm, IngestedPackage
from libs.provenance import ProvenanceClass, ProvenanceSubtype
from topology_source import (
    TOPOLOGY_SOURCE_VERSION_MISSING,
    TopologySourceTrace,
    consistent_topology_trace,
    topology_source_trace,
)

from .base import ChannelValue, unavailable
from .contracts import (
    ChannelFamily,
    DependencySemantic,
    dependency_derivation_tag,
)
from .dependency import ResourceResolver

ANCESTOR_CHANNEL_ID = "DepUpstreamAncestor"
ACTIVE_PATH_CHANNEL_ID = "DepUpstreamActivePath"

#: Decay scale for the exponential distance term. Distinct symbol from
#: history's lambda_H (docs 4A): dependency decay and history reliability are
#: unrelated quantities and must not share a threshold.
DEFAULT_LAMBDA_DEP = 2.0

#: Baseline threshold for CD to count as SUPPORT.
DEFAULT_THETA_CD = 0.3


# --------------------------------------------------------------------------
# Shared scope-specificity primitive
# --------------------------------------------------------------------------


def specificity(scope_size: int, universe_size: int) -> float:
    """``Specificity_s(u) = log(1 + N_s/|Scope_s(u)|) / log(1 + N_s)``.

    Bounded in [0,1] by construction; the old ``1/log(1+|Desc|)`` form could
    exceed 1 when ``|Desc|=1``, breaking the ``s+ in [0,1]`` contract.
    """
    if scope_size <= 0 or universe_size <= 0:
        raise ValueError("scope_size and universe_size must be positive")
    return math.log(1 + universe_size / scope_size) / math.log(1 + universe_size)


# --------------------------------------------------------------------------
# SHARED_ANCESTOR
# --------------------------------------------------------------------------


@dataclass
class DirectedHierarchy:
    """A directed dependency hierarchy: parent -> children.

    Built only from ``LOGICAL_DEPENDENCY`` (or similarly directed) edges. An
    undirected adjacency graph must never be passed here (ADR-MOCK-0005).
    """

    children_of: dict[str, set[str]] = field(default_factory=dict)
    parent_of: dict[str, str] = field(default_factory=dict)
    #: EXTERNAL_OPERATIONAL for inventory-sourced hierarchy, POST_HOC if
    #: derived from the alarm pipeline itself.
    provenance_class: ProvenanceClass = ProvenanceClass.EXTERNAL_OPERATIONAL
    provenance_subtype: ProvenanceSubtype | None = ProvenanceSubtype.TOPOLOGY_EXTERNAL

    @property
    def is_valid(self) -> bool:
        """A hierarchy needs at least one edge to support any ancestor claim."""
        return bool(self.parent_of)

    @property
    def total_resources(self) -> int:
        return len(set(self.parent_of) | set(self.children_of))

    def ancestors_of(self, node: str) -> list[str]:
        """Ordered ancestor chain, nearest first."""
        chain: list[str] = []
        current = node
        seen = {node}
        while current in self.parent_of:
            parent = self.parent_of[current]
            if parent in seen:
                # A cycle would make "ancestor" ill-defined; stop rather than loop.
                break
            chain.append(parent)
            seen.add(parent)
            current = parent
        return chain

    def descendants_of(self, node: str) -> set[str]:
        """All nodes reachable by following children, node excluded."""
        result: set[str] = set()
        queue: deque[str] = deque(self.children_of.get(node, ()))
        while queue:
            current = queue.popleft()
            if current in result:
                continue
            result.add(current)
            queue.extend(self.children_of.get(current, ()))
        return result


def build_directed_hierarchy(edges: list[dict]) -> DirectedHierarchy:
    """Build a hierarchy from ingested topology edges.

    Only edges with ``relation_type=LOGICAL_DEPENDENCY`` and ``directed=True``
    are accepted; anything else cannot support an ancestor claim.
    """
    hierarchy = DirectedHierarchy()
    for edge in edges:
        if edge.get("relation_type") != "LOGICAL_DEPENDENCY" or not edge.get("directed"):
            continue
        parent = edge.get("source_resource_id")
        child = edge.get("target_resource_id")
        if not parent or not child:
            continue
        hierarchy.children_of.setdefault(parent, set()).add(child)
        hierarchy.parent_of[child] = parent
        hierarchy.children_of.setdefault(child, set())
    return hierarchy


def _common_dependency_from_candidates(
    candidates: list[tuple[str, int, int, int, int]],
    *,
    lambda_dep: float,
) -> tuple[float, str] | None:
    """Shared scoring core: ``max_u Specificity(u) * exp(-(d_i+d_j)/lambda)``.

    Each candidate tuple is ``(node, scope_size, universe_size, dist_i, dist_j)``.
    """
    best: tuple[float, str] | None = None
    for node, scope_size, universe_size, dist_i, dist_j in candidates:
        score = specificity(scope_size, universe_size) * math.exp(
            -(dist_i + dist_j) / lambda_dep
        )
        if best is None or score > best[0]:
            best = (score, node)
    return best


def evaluate_shared_ancestor(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    *,
    hierarchy: DirectedHierarchy | None,
    resolver: ResourceResolver,
    lambda_dep: float = DEFAULT_LAMBDA_DEP,
    theta: float = DEFAULT_THETA_CD,
    source_ref: str = "unversioned",
    channel_id: str = ANCESTOR_CHANNEL_ID,
    source_trace: TopologySourceTrace | None = None,
    unavailable_reason: str | None = None,
) -> ChannelValue:
    """``CD_anc(i,j)``: SHARED_ANCESTOR, gated on a valid directed hierarchy."""

    def fail(reason: str) -> ChannelValue:
        return unavailable(
            channel_id,
            dependency_derivation_tag(source_ref),
            hierarchy.provenance_class if hierarchy else ProvenanceClass.EXTERNAL_OPERATIONAL,
            reason=reason,
            threshold=theta,
            provenance_subtype=(
                hierarchy.provenance_subtype
                if hierarchy
                else ProvenanceSubtype.TOPOLOGY_EXTERNAL
            ),
            channel_family=ChannelFamily.DEP_UPSTREAM,
            dependency_semantic=DependencySemantic.SHARED_ANCESTOR,
            source_ref=source_ref,
            source_id=source_trace.source_id if source_trace else None,
            source_version=source_trace.source_version if source_trace else None,
            scenario_id=source_trace.scenario_id if source_trace else None,
            generator_version=source_trace.generator_version if source_trace else None,
        )

    if unavailable_reason is not None:
        return fail(unavailable_reason)
    if hierarchy is None or not hierarchy.is_valid:
        return fail("no valid directed hierarchy; SHARED_ANCESTOR capability gate closed")

    resource_a = resolver.resource_of(alarm_a.alarm_id)
    resource_b = resolver.resource_of(alarm_b.alarm_id)
    if resource_a is None or resource_b is None:
        return fail("alarm->resource mapping unresolved (UNMAPPED/AMBIGUOUS)")

    ancestors_a = {node: i + 1 for i, node in enumerate(hierarchy.ancestors_of(resource_a))}
    ancestors_b = {node: i + 1 for i, node in enumerate(hierarchy.ancestors_of(resource_b))}
    shared = set(ancestors_a) & set(ancestors_b)
    if not shared:
        return fail("no shared ancestor in the directed hierarchy")

    universe = hierarchy.total_resources
    candidates = [
        (
            node,
            len(hierarchy.descendants_of(node)) or 1,
            universe,
            ancestors_a[node],
            ancestors_b[node],
        )
        for node in shared
    ]
    best = _common_dependency_from_candidates(candidates, lambda_dep=lambda_dep)
    assert best is not None
    score, witness = best

    return ChannelValue(
        channel_id=channel_id,
        derivation_tag=dependency_derivation_tag(source_ref),
        provenance_class=hierarchy.provenance_class,
        provenance_subtype=hierarchy.provenance_subtype,
        availability=True,
        positive_score=score,
        threshold=theta,
        detail=f"SHARED_ANCESTOR witness={witness}, CD={score:.4f}",
        channel_family=ChannelFamily.DEP_UPSTREAM,
        dependency_semantic=DependencySemantic.SHARED_ANCESTOR,
        source_ref=source_ref,
        source_id=source_trace.source_id if source_trace else None,
        source_version=source_trace.source_version if source_trace else None,
        scenario_id=source_trace.scenario_id if source_trace else None,
        generator_version=source_trace.generator_version if source_trace else None,
    )


@dataclass(frozen=True)
class DepUpstreamAncestor:
    """Capability-specific provider under the shared ``DEP_UPSTREAM`` family."""

    hierarchy: DirectedHierarchy | None
    resolver: ResourceResolver
    source_ref: str
    source_trace: TopologySourceTrace | None = None
    unavailable_reason: str | None = None
    lambda_dep: float = DEFAULT_LAMBDA_DEP
    theta: float = DEFAULT_THETA_CD

    @property
    def channel_id(self) -> str:
        """Opaque internal provider key; APIs serialize family + semantic."""
        return f"{ANCESTOR_CHANNEL_ID}@{self.source_ref}"

    def evaluate(self, alarm_a: IngestedAlarm, alarm_b: IngestedAlarm) -> ChannelValue:
        return evaluate_shared_ancestor(
            alarm_a,
            alarm_b,
            hierarchy=self.hierarchy,
            resolver=self.resolver,
            lambda_dep=self.lambda_dep,
            theta=self.theta,
            source_ref=self.source_ref,
            channel_id=self.channel_id,
            source_trace=self.source_trace,
            unavailable_reason=self.unavailable_reason,
        )


# --------------------------------------------------------------------------
# SHARED_ACTIVE_PATH
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedPath:
    """One verified, ordered active path for a resource.

    ``nodes`` is ordered from the resource outward, matching the mock's
    ``ActivePath.nodes`` shape (e.g. ``[SYN-DEA-A, SYN-R1, SYN-R2, SYN-CORE-X]``).
    Order is what makes hop distance meaningful; an unordered membership set is
    not enough (ADR-0032 fail-closed clause).
    """

    path_id: str
    resource_id: str
    nodes: tuple[str, ...]

    def hop_distance_to(self, node: str) -> int | None:
        """Hop count from ``resource_id`` to ``node`` along this path."""
        try:
            return self.nodes.index(node)
        except ValueError:
            return None


@dataclass
class ActivePathIndex:
    """All verified active paths at one path-context (snapshot/path-scope).

    ``paths_of`` maps resource_id -> its verified paths. Provenance follows the
    same rule as topology: EXTERNAL_OPERATIONAL when sourced from
    inventory/NMS, POST_HOC if derived from the alarm pipeline itself.
    """

    paths_of: dict[str, list[VerifiedPath]] = field(default_factory=dict)
    provenance_class: ProvenanceClass = ProvenanceClass.EXTERNAL_OPERATIONAL
    provenance_subtype: ProvenanceSubtype | None = ProvenanceSubtype.TOPOLOGY_EXTERNAL

    @property
    def is_valid(self) -> bool:
        return bool(self.paths_of)

    @property
    def observed_resource_count(self) -> int:
        """``N_path,t``: resources with a valid active-path observation here.

        Scoped to this path universe, never the whole topology inventory.
        """
        return len(self.paths_of)

    def traversing_resources(self, node: str) -> set[str]:
        """``Scope_path,t(node)``: distinct resources whose path passes through it.

        A resource counts once even if several of its ECMP paths pass through
        the node, so representation (path count) cannot inflate specificity.
        """
        return {
            resource
            for resource, paths in self.paths_of.items()
            if any(node in path.nodes for path in paths)
        }

    def min_hop_distance(self, resource_id: str, node: str) -> int | None:
        """``min`` over this resource's valid paths that pass through ``node``."""
        distances = [
            d
            for path in self.paths_of.get(resource_id, ())
            if (d := path.hop_distance_to(node)) is not None
        ]
        return min(distances) if distances else None


def build_active_path_index(paths: list[dict]) -> ActivePathIndex:
    """Build an index from ingested topology active-path records.

    Expects the mock's ``ActivePath`` shape: ``path_id``, ``resource_id``,
    ``nodes`` (ordered). Records without an ordered node list are dropped,
    since an unordered membership claim cannot support a hop distance.
    """
    index = ActivePathIndex()
    for record in paths:
        resource_id = record.get("resource_id")
        nodes = record.get("nodes")
        if not resource_id or not nodes or len(nodes) < 1:
            continue
        path = VerifiedPath(
            path_id=str(record.get("path_id", "")),
            resource_id=resource_id,
            nodes=tuple(nodes),
        )
        index.paths_of.setdefault(resource_id, []).append(path)
    return index


def evaluate_shared_active_path(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    *,
    path_index: ActivePathIndex | None,
    resolver: ResourceResolver,
    lambda_dep: float = DEFAULT_LAMBDA_DEP,
    theta: float = DEFAULT_THETA_CD,
    source_ref: str = "unversioned",
    channel_id: str = ACTIVE_PATH_CHANNEL_ID,
    source_trace: TopologySourceTrace | None = None,
    unavailable_reason: str | None = None,
) -> ChannelValue:
    """``CD_path(i,j)``: SHARED_ACTIVE_PATH, gated on verified ordered paths.

    Deliberately does **not** return 1.0 for "any shared active path": a core
    node traversed by thousands of resources would then create the strongest
    possible dependency evidence for nearly the whole network, defeating the
    anti-hub principle Specificity exists to protect.
    """

    def fail(reason: str) -> ChannelValue:
        return unavailable(
            channel_id,
            dependency_derivation_tag(source_ref),
            path_index.provenance_class if path_index else ProvenanceClass.EXTERNAL_OPERATIONAL,
            reason=reason,
            threshold=theta,
            provenance_subtype=(
                path_index.provenance_subtype
                if path_index
                else ProvenanceSubtype.TOPOLOGY_EXTERNAL
            ),
            channel_family=ChannelFamily.DEP_UPSTREAM,
            dependency_semantic=DependencySemantic.SHARED_ACTIVE_PATH,
            source_ref=source_ref,
            source_id=source_trace.source_id if source_trace else None,
            source_version=source_trace.source_version if source_trace else None,
            scenario_id=source_trace.scenario_id if source_trace else None,
            generator_version=source_trace.generator_version if source_trace else None,
        )

    if unavailable_reason is not None:
        return fail(unavailable_reason)
    if path_index is None or not path_index.is_valid:
        return fail("no verified active-path data; SHARED_ACTIVE_PATH capability gate closed")

    resource_a = resolver.resource_of(alarm_a.alarm_id)
    resource_b = resolver.resource_of(alarm_b.alarm_id)
    if resource_a is None or resource_b is None:
        return fail("alarm->resource mapping unresolved (UNMAPPED/AMBIGUOUS)")

    paths_a = path_index.paths_of.get(resource_a)
    paths_b = path_index.paths_of.get(resource_b)
    if not paths_a or not paths_b:
        return fail("no verified active path for at least one resource")

    nodes_a = {node for path in paths_a for node in path.nodes}
    nodes_b = {node for path in paths_b for node in path.nodes}
    shared_nodes = nodes_a & nodes_b
    if not shared_nodes:
        return fail("no shared node across verified active paths")

    universe = path_index.observed_resource_count
    candidates = []
    for node in shared_nodes:
        dist_a = path_index.min_hop_distance(resource_a, node)
        dist_b = path_index.min_hop_distance(resource_b, node)
        if dist_a is None or dist_b is None:
            # Present in the node set but not resolvable to an ordered hop
            # distance; skip rather than guess.
            continue
        scope_size = len(path_index.traversing_resources(node)) or 1
        candidates.append((node, scope_size, universe, dist_a, dist_b))

    if not candidates:
        # Membership overlap exists but no path carries ordered hop semantics
        # for it: fail closed per ADR-0032, never fall back to graph distance.
        return fail(
            "shared node has path membership but no ordered hop distance; "
            "normalized CD is unavailable, not derived from graph adjacency"
        )

    best = _common_dependency_from_candidates(candidates, lambda_dep=lambda_dep)
    assert best is not None
    score, witness = best

    return ChannelValue(
        channel_id=channel_id,
        derivation_tag=dependency_derivation_tag(source_ref),
        provenance_class=path_index.provenance_class,
        provenance_subtype=path_index.provenance_subtype,
        availability=True,
        positive_score=score,
        threshold=theta,
        detail=f"SHARED_ACTIVE_PATH witness={witness}, CD={score:.4f}",
        channel_family=ChannelFamily.DEP_UPSTREAM,
        dependency_semantic=DependencySemantic.SHARED_ACTIVE_PATH,
        source_ref=source_ref,
        source_id=source_trace.source_id if source_trace else None,
        source_version=source_trace.source_version if source_trace else None,
        scenario_id=source_trace.scenario_id if source_trace else None,
        generator_version=source_trace.generator_version if source_trace else None,
    )


@dataclass(frozen=True)
class DepUpstreamActivePath:
    """Active-path provider with independent capability and distance semantics."""

    path_index: ActivePathIndex | None
    resolver: ResourceResolver
    source_ref: str
    source_trace: TopologySourceTrace | None = None
    unavailable_reason: str | None = None
    lambda_dep: float = DEFAULT_LAMBDA_DEP
    theta: float = DEFAULT_THETA_CD

    @property
    def channel_id(self) -> str:
        """Opaque internal provider key; APIs serialize family + semantic."""
        return f"{ACTIVE_PATH_CHANNEL_ID}@{self.source_ref}"

    def evaluate(self, alarm_a: IngestedAlarm, alarm_b: IngestedAlarm) -> ChannelValue:
        return evaluate_shared_active_path(
            alarm_a,
            alarm_b,
            path_index=self.path_index,
            resolver=self.resolver,
            lambda_dep=self.lambda_dep,
            theta=self.theta,
            source_ref=self.source_ref,
            channel_id=self.channel_id,
            source_trace=self.source_trace,
            unavailable_reason=self.unavailable_reason,
        )


DependencyProvider = DepUpstreamAncestor | DepUpstreamActivePath


def _group_by_source(
    records: list[dict],
) -> tuple[dict[str, tuple[TopologySourceTrace, list[dict]]], list[dict]]:
    """Group only exact source identities; incomplete records stay separate.

    ``snapshot.topology_version`` and generator metadata are deliberately not
    source-version fallbacks. A foreign payload missing record-level identity
    degrades only the affected topology capability.
    """
    grouped_records: dict[str, list[dict]] = {}
    traces: dict[str, TopologySourceTrace] = {}
    incomplete: list[dict] = []
    for record in records:
        trace = topology_source_trace(record)
        if trace is None:
            incomplete.append(record)
            continue
        grouped_records.setdefault(trace.source_ref, []).append(record)
        traces.setdefault(trace.source_ref, trace)

    grouped: dict[str, tuple[TopologySourceTrace, list[dict]]] = {}
    for source_ref, source_records in grouped_records.items():
        trace = consistent_topology_trace(source_records)
        if trace is None:
            incomplete.extend(source_records)
            continue
        grouped[source_ref] = (trace, source_records)
    return grouped, incomplete


def build_dep_upstream_providers(
    package: IngestedPackage,
    *,
    resolver: ResourceResolver | None = None,
    lambda_dep: float = DEFAULT_LAMBDA_DEP,
    theta: float = DEFAULT_THETA_CD,
) -> tuple[DependencyProvider, ...]:
    """Build capability-specific providers grouped by underlying source/model.

    Providers from the same ``source_ref`` intentionally share one derivation
    tag, so ancestor and active-path detail remain visible while contributing at
    most one normalized derivation-group vote.
    """
    resolved = resolver or ResourceResolver.from_package(package)
    logical_records: list[dict] = []
    for edge in package.topology.get("edges") or ():
        if edge.get("relation_type") != "LOGICAL_DEPENDENCY" or not edge.get(
            "directed"
        ):
            continue
        logical_records.append(edge)

    path_records = list(package.topology.get("active_paths") or ())
    logical_by_source, incomplete_logical = _group_by_source(logical_records)
    paths_by_source, incomplete_paths = _group_by_source(path_records)

    providers: list[DependencyProvider] = [
        DepUpstreamAncestor(
            hierarchy=build_directed_hierarchy(records),
            resolver=resolved,
            source_ref=source_ref,
            source_trace=trace,
            lambda_dep=lambda_dep,
            theta=theta,
        )
        for source_ref, (trace, records) in sorted(logical_by_source.items())
    ]
    if incomplete_logical:
        providers.append(
            DepUpstreamAncestor(
                hierarchy=None,
                resolver=resolved,
                source_ref="topology-source-unavailable",
                unavailable_reason=TOPOLOGY_SOURCE_VERSION_MISSING,
                lambda_dep=lambda_dep,
                theta=theta,
            )
        )
    elif not providers:
        providers.append(
            DepUpstreamAncestor(
                hierarchy=None,
                resolver=resolved,
                source_ref="topology-capability-unavailable",
                lambda_dep=lambda_dep,
                theta=theta,
            )
        )

    active_path_providers = [
        DepUpstreamActivePath(
            path_index=build_active_path_index(records),
            resolver=resolved,
            source_ref=source_ref,
            source_trace=trace,
            lambda_dep=lambda_dep,
            theta=theta,
        )
        for source_ref, (trace, records) in sorted(paths_by_source.items())
    ]
    providers.extend(active_path_providers)
    if incomplete_paths:
        providers.append(
            DepUpstreamActivePath(
                path_index=None,
                resolver=resolved,
                source_ref="topology-source-unavailable",
                unavailable_reason=TOPOLOGY_SOURCE_VERSION_MISSING,
                lambda_dep=lambda_dep,
                theta=theta,
            )
        )
    elif not active_path_providers:
        providers.append(
            DepUpstreamActivePath(
                path_index=None,
                resolver=resolved,
                source_ref="topology-capability-unavailable",
                lambda_dep=lambda_dep,
                theta=theta,
            )
        )
    return tuple(providers)
