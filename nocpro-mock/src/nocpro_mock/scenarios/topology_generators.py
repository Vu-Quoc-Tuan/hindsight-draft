"""Synthetic topology generators (docs 06/07, P0.5).

These exist because the real exports cannot express the capabilities Explain
needs to be tested against: ``topoIP`` gives undirected adjacency only, with no
directed dependency, no active path and no failure domains.

Every emitted object carries ``source_kind=SYNTHETIC_TEST`` plus generation
metadata, so ADR-0010's stage-1 gate keeps it out of real validation.

Three rules enforced here:
- directed hierarchy edges are ``LOGICAL_DEPENDENCY`` and explicitly directed;
- active paths are stored as first-class node sequences, never inferred;
- failure domains stay hyperedges and are never clique-projected into pairs.
"""

from __future__ import annotations

from ..contract import (
    ActivePath,
    ChainingUsage,
    ChainingUsageAssessment,
    FailureDomain,
    FailureDomainType,
    GenerationMetadata,
    ProvenanceClass,
    ProvenanceSubtype,
    QualityStatus,
    RelationType,
    SourceKind,
    TopologyEdge,
    TopologyNode,
)
from .schema import ScenarioDefinition, ScenarioError, require_synthetic_identifiers

TOPOLOGY_LAYER_SYNTHETIC = "SYNTHETIC"


def _generation(
    scenario: ScenarioDefinition, *, rule: str, generator_version: str
) -> GenerationMetadata:
    return GenerationMetadata(
        scenario_id=scenario.scenario_id,
        seed=scenario.seed,
        generator_version=generator_version,
        generation_rule=rule,
        base_fixture_id=scenario.base_fixture,
    )


def _usage(scenario: ScenarioDefinition) -> ChainingUsageAssessment:
    """Synthetic topology was never seen by NocPro chaining.

    This is one of the few cases where CONFIRMED_NOT_USED is provable: the data
    did not exist when chaining ran. It still cannot validate, because the
    source-kind gate rejects SYNTHETIC_TEST first (ADR-0010).
    """
    source = scenario.topology_source
    if source is None:
        raise ScenarioError(
            f"scenario {scenario.scenario_id!r} has no topology_source"
        )
    return ChainingUsageAssessment(
        source_id=source.source_id,
        source_version=source.source_version,
        chaining_config_version=None,
        usage=ChainingUsage.CONFIRMED_NOT_USED.value,
        run_context="synthetic scenario; data absent from any chaining run",
    )


def _nodes(
    resource_ids: list[str], scenario: ScenarioDefinition, generation: GenerationMetadata
) -> tuple[TopologyNode, ...]:
    source = scenario.topology_source
    if source is None:
        raise ScenarioError(
            f"scenario {scenario.scenario_id!r} has no topology_source"
        )
    return tuple(
        TopologyNode(
            resource_id=resource_id,
            source_id=source.source_id,
            source_kind=SourceKind.SYNTHETIC_TEST,
            topology_layer=TOPOLOGY_LAYER_SYNTHETIC,
            source_version=source.source_version,
            generation=generation,
        )
        for resource_id in sorted(set(resource_ids))
    )


def generate_dependency_hierarchy(
    scenario: ScenarioDefinition, *, generator_version: str
) -> tuple[tuple[TopologyNode, ...], tuple[TopologyEdge, ...]]:
    """Directed logical dependency tree, enabling SHARED_ANCESTOR tests."""
    block = scenario.require_block("topology")
    raw_edges = block.get("edges") or []
    if not raw_edges:
        raise ScenarioError(f"scenario {scenario.scenario_id!r} declares no edges")

    declared_type = str(block.get("relation_type", RelationType.LOGICAL_DEPENDENCY.value))
    try:
        relation_type = RelationType(declared_type)
    except ValueError as exc:
        raise ScenarioError(f"unknown relation_type {declared_type!r}") from exc

    directed = bool(block.get("directed", False))
    if relation_type is RelationType.IP_ADJACENCY and directed:
        raise ScenarioError(
            "IP_ADJACENCY cannot be directed even in a synthetic scenario "
            "(ADR-MOCK-0005)"
        )
    if relation_type is RelationType.LOGICAL_DEPENDENCY and not directed:
        raise ScenarioError(
            "LOGICAL_DEPENDENCY hierarchy must declare directed=true, otherwise "
            "it cannot support SHARED_ANCESTOR"
        )

    pairs: list[tuple[str, str]] = []
    for entry in raw_edges:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ScenarioError(
                f"scenario {scenario.scenario_id!r}: each edge must be a "
                f"[source, target] pair, got {entry!r}"
            )
        pairs.append((str(entry[0]), str(entry[1])))

    flat = [node for pair in pairs for node in pair]
    require_synthetic_identifiers(flat, context=scenario.scenario_id)

    generation = _generation(
        scenario,
        rule=f"explicit directed {relation_type.value} edge list",
        generator_version=generator_version,
    )
    usage = _usage(scenario)
    source_meta = scenario.topology_source
    assert source_meta is not None

    edges: list[TopologyEdge] = []
    seen: set[tuple[str, str]] = set()
    for parent, target in pairs:
        if parent == target:
            raise ScenarioError(f"self-dependency is not meaningful: {parent!r}")
        if (parent, target) in seen:
            continue
        seen.add((parent, target))
        edges.append(
            TopologyEdge(
                edge_id=f"{scenario.scenario_id}:{parent}->{target}",
                source_resource_id=parent,
                target_resource_id=target,
                relation_type=relation_type,
                directed=directed,
                source_id=source_meta.source_id,
                source_kind=SourceKind.SYNTHETIC_TEST,
                source_version=source_meta.source_version,
                provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
                provenance_subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
                chaining_usage=usage,
                # Synthetic data has no real freshness to assess.
                quality_status=QualityStatus.UNKNOWN,
                generation=generation,
            )
        )

    return _nodes(flat, scenario, generation), tuple(edges)


def generate_active_paths(
    scenario: ScenarioDefinition, *, generator_version: str
) -> tuple[tuple[TopologyNode, ...], tuple[ActivePath, ...]]:
    """Explicit path membership, enabling SHARED_ACTIVE_PATH tests.

    Paths are stored verbatim. Nothing is derived from adjacency or shortest
    path, which is exactly what ADR-MOCK-0005 forbids.
    """
    raw_paths = scenario.require_block("paths")
    if not raw_paths:
        raise ScenarioError(f"scenario {scenario.scenario_id!r} declares no paths")

    generation = _generation(
        scenario,
        rule="explicit active path node sequence",
        generator_version=generator_version,
    )
    source = scenario.topology_source
    assert source is not None

    paths: list[ActivePath] = []
    all_nodes: list[str] = []
    for entry in raw_paths:
        path_id = str(entry.get("path_id") or "")
        resource_id = str(entry.get("resource_id") or "")
        nodes = [str(n) for n in (entry.get("nodes") or [])]
        if not path_id or not resource_id:
            raise ScenarioError(
                f"scenario {scenario.scenario_id!r}: path needs path_id and resource_id"
            )
        if len(nodes) < 2:
            raise ScenarioError(f"path {path_id!r} needs at least two nodes")
        if len(set(nodes)) != len(nodes):
            raise ScenarioError(f"path {path_id!r} repeats a node")

        require_synthetic_identifiers([path_id, resource_id, *nodes], context=path_id)
        all_nodes.extend(nodes)
        paths.append(
            ActivePath(
                path_id=path_id,
                resource_id=resource_id,
                nodes=tuple(nodes),
                source_id=source.source_id,
                source_kind=SourceKind.SYNTHETIC_TEST,
                source_version=source.source_version,
                generation=generation,
            )
        )

    return _nodes(all_nodes, scenario, generation), tuple(paths)


def generate_failure_domains(
    scenario: ScenarioDefinition, *, generator_version: str
) -> tuple[tuple[TopologyNode, ...], tuple[FailureDomain, ...]]:
    """SRLG/power/rack/service-instance membership as hyperedges.

    Members stay a set. Clique projection into pairwise edges is refused: it
    would collapse ``H_domain`` into ``K_pair`` (ADR-0011).
    """
    raw_domains = scenario.require_block("failure_domains")
    if not raw_domains:
        raise ScenarioError(
            f"scenario {scenario.scenario_id!r} declares no failure domains"
        )

    if scenario.rules.get("clique_project"):
        raise ScenarioError(
            "clique_project=true is refused: failure domains are hyperedges and "
            "must not be projected into pairwise edges (ADR-0011)"
        )

    generation = _generation(
        scenario,
        rule="explicit failure-domain member set (hyperedge, not clique-projected)",
        generator_version=generator_version,
    )
    source = scenario.topology_source
    assert source is not None

    domains: list[FailureDomain] = []
    all_members: list[str] = []
    for entry in raw_domains:
        domain_id = str(entry.get("failure_domain_id") or "")
        raw_type = str(entry.get("domain_type") or "")
        members = [str(m) for m in (entry.get("members") or [])]
        if not domain_id:
            raise ScenarioError("failure domain needs a failure_domain_id")
        try:
            domain_type = FailureDomainType(raw_type)
        except ValueError as exc:
            raise ScenarioError(
                f"unknown domain_type {raw_type!r} for {domain_id!r}"
            ) from exc
        if not members:
            raise ScenarioError(f"failure domain {domain_id!r} has no members")
        if len(set(members)) != len(members):
            raise ScenarioError(f"failure domain {domain_id!r} repeats a member")

        require_synthetic_identifiers([domain_id, *members], context=domain_id)
        all_members.extend(members)
        domains.append(
            FailureDomain(
                failure_domain_id=domain_id,
                domain_type=domain_type,
                members=tuple(members),
                source_id=source.source_id,
                source_kind=SourceKind.SYNTHETIC_TEST,
                source_version=source.source_version,
                provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
                provenance_subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
                quality_status=QualityStatus.UNKNOWN,
                generation=generation,
            )
        )

    return _nodes(all_members, scenario, generation), tuple(domains)
