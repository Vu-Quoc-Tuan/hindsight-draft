"""Layer 4 — synthetic scenario tests (docs 13).

Frozen criteria asserted here:
  - same seed => same output
  - synthetic resources use SYN-* IDs
  - synthetic source never becomes real validation
  - directed hierarchy enables only hierarchy capability
  - active-path scenario stores explicit paths
  - H_domain stays a set/hyperedge
"""

from __future__ import annotations

import pytest
import yaml

from nocpro_mock.contract import (
    FailureDomainType,
    MappingMethod,
    MappingStatus,
    ProvenanceClass,
    ProvenanceSubtype,
    RelationType,
    SourceKind,
    is_validation_eligible,
    package_to_json,
)
from nocpro_mock.scenarios import (
    ScenarioError,
    generate_active_paths,
    generate_dependency_hierarchy,
    generate_failure_domains,
    generate_integrated_topology,
    generate_operational_context,
    is_synthetic_identifier,
    load_scenario,
    load_scenarios,
    parse_scenario,
)
from tests.conftest import REPO_ROOT

SYNTHETIC_DIR = REPO_ROOT / "docs/examples/synthetic"
VERSION = "nocpro-mock-0.1.0"
TOPOLOGY_SOURCE = {
    "source_id": "synthetic-topology-test",
    "source_version": "syn-topo-test-v1",
}


@pytest.fixture()
def hierarchy():
    return load_scenario(SYNTHETIC_DIR / "scenario_dependency_hierarchy.yaml")


@pytest.fixture()
def active_path():
    return load_scenario(SYNTHETIC_DIR / "scenario_active_path.yaml")


@pytest.fixture()
def failure_domain():
    return load_scenario(SYNTHETIC_DIR / "scenario_failure_domain.yaml")


@pytest.fixture()
def context_scenario():
    return load_scenario(SYNTHETIC_DIR / "scenario_operational_context.yaml")


# --------------------------------------------------------------------------
# Scenario definitions
# --------------------------------------------------------------------------


def test_all_shipped_scenarios_load():
    scenarios = load_scenarios(SYNTHETIC_DIR)
    ids = {s.scenario_id for s in scenarios}
    assert {
        "synthetic_dependency_hierarchy_v1",
        "synthetic_active_path_v1",
        "synthetic_failure_domain_v1",
        "synthetic_operational_context_v1",
        "system_pair_metadata_semantics_v1",
    } <= ids
    assert all(s.source_kind is SourceKind.SYNTHETIC_TEST for s in scenarios)
    assert all(s.seed == 42 for s in scenarios)


def test_scenario_cannot_declare_a_real_source_kind():
    """A scenario claiming REAL_* would smuggle synthetic data past the gate."""
    with pytest.raises(ScenarioError, match="only be SYNTHETIC_TEST or BACKFILL"):
        parse_scenario(
            {"scenario_id": "x", "seed": 1, "source_kind": "REAL_EXPORT_REPLAY"}
        )


def test_scenario_requires_integer_seed():
    with pytest.raises(ScenarioError, match="seed must be an integer"):
        parse_scenario(
            {"scenario_id": "x", "seed": "42", "source_kind": "SYNTHETIC_TEST"}
        )


def test_missing_required_keys_are_reported():
    with pytest.raises(ScenarioError, match="missing required key"):
        parse_scenario({"scenario_id": "x"})


@pytest.mark.parametrize("derived_block", ["topology", "paths", "failure_domains"])
def test_topology_derived_scenario_requires_source_version(derived_block):
    with pytest.raises(ScenarioError, match="topology_source.source_version"):
        parse_scenario(
            {
                "scenario_id": "synthetic_missing_topology_version",
                "seed": 42,
                "source_kind": "SYNTHETIC_TEST",
                "topology_source": {"source_id": "synthetic-topology"},
                derived_block: {},
            }
        )


def test_scenario_without_topology_does_not_require_topology_source():
    scenario = parse_scenario(
        {
            "scenario_id": "synthetic_alarm_only",
            "seed": 42,
            "source_kind": "SYNTHETIC_TEST",
        }
    )

    assert scenario.topology_source is None


def test_topology_source_version_is_independent_from_generator_version(hierarchy):
    _, edges = generate_dependency_hierarchy(
        hierarchy, generator_version="mockgen-independent-v9"
    )

    assert {edge.source_version for edge in edges} == {
        hierarchy.topology_source.source_version
    }
    assert {edge.generation.generator_version for edge in edges} == {
        "mockgen-independent-v9"
    }


def test_same_generator_can_emit_distinct_topology_source_versions(hierarchy):
    changed = parse_scenario(
        {
            **hierarchy.raw,
            "topology_source": {
                "source_id": hierarchy.topology_source.source_id,
                "source_version": "syn-topo-hierarchy-v2",
            },
        }
    )

    _, first = generate_dependency_hierarchy(hierarchy, generator_version=VERSION)
    _, second = generate_dependency_hierarchy(changed, generator_version=VERSION)

    assert {edge.generation.generator_version for edge in first + second} == {VERSION}
    assert {edge.source_version for edge in first} == {"syn-topo-hierarchy-v1"}
    assert {edge.source_version for edge in second} == {"syn-topo-hierarchy-v2"}


def test_integrated_topology_keeps_capabilities_and_exact_mapping():
    scenario = parse_scenario(
        {
            "scenario_id": "synthetic_integrated_topology_v1",
            "source_kind": "SYNTHETIC_TEST",
            "seed": 42,
            "topology_source": {
                "source_id": "synthetic-topology",
                "source_version": "syn-topo-integrated-v1",
            },
            "topology": {
                "relation_type": "LOGICAL_DEPENDENCY",
                "directed": True,
                "edges": [
                    ["SYN-CORE-01", "SYN-AGG-01"],
                    ["SYN-AGG-01", "SYN-DEVICE-01"],
                    ["SYN-AGG-01", "SYN-DEVICE-02"],
                ],
            },
            "paths": [
                {
                    "path_id": "SYN-PATH-01",
                    "resource_id": "SYN-DEVICE-01",
                    "nodes": ["SYN-DEVICE-01", "SYN-AGG-01", "SYN-CORE-01"],
                },
                {
                    "path_id": "SYN-PATH-02",
                    "resource_id": "SYN-DEVICE-02",
                    "nodes": ["SYN-DEVICE-02", "SYN-AGG-01", "SYN-CORE-01"],
                },
            ],
            "failure_domains": [
                {
                    "failure_domain_id": "SRLG-SYN-INTEGRATED-01",
                    "domain_type": "SRLG",
                    "members": ["SYN-DEVICE-01", "SYN-DEVICE-02"],
                }
            ],
        }
    )

    topology = generate_integrated_topology(
        scenario,
        generator_version="mockgen-integrated-v1",
        alarm_resource_ids=("SYN-DEVICE-01", "SYN-DEVICE-02"),
    )

    assert len(topology.nodes) == 4
    assert len(topology.edges) == 3
    assert len(topology.active_paths) == 2
    assert len(topology.failure_domains) == 1
    assert {mapping.alarm_id for mapping in topology.mappings} == {
        "SYN-DEVICE-01",
        "SYN-DEVICE-02",
    }
    assert all(
        mapping.mapping_status is MappingStatus.EXACT
        for mapping in topology.mappings
    )
    assert all(
        mapping.mapping_method is MappingMethod.EXACT_IDENTITY
        for mapping in topology.mappings
    )
    assert all(mapping.mapping_confidence == 1.0 for mapping in topology.mappings)
    assert all(
        mapping.source_version == "syn-topo-integrated-v1"
        for mapping in topology.mappings
    )


def test_integrated_topology_refuses_mapping_to_absent_resource():
    scenario = parse_scenario(
        {
            "scenario_id": "synthetic_integrated_missing_resource_v1",
            "source_kind": "SYNTHETIC_TEST",
            "seed": 42,
            "topology_source": {
                "source_id": "synthetic-topology",
                "source_version": "syn-topo-integrated-v1",
            },
            "topology": {
                "relation_type": "LOGICAL_DEPENDENCY",
                "directed": True,
                "edges": [["SYN-CORE-01", "SYN-DEVICE-01"]],
            },
            "paths": [
                {
                    "path_id": "SYN-PATH-01",
                    "resource_id": "SYN-DEVICE-01",
                    "nodes": ["SYN-DEVICE-01", "SYN-CORE-01"],
                }
            ],
            "failure_domains": [
                {
                    "failure_domain_id": "SRLG-SYN-01",
                    "domain_type": "SRLG",
                    "members": ["SYN-DEVICE-01"],
                }
            ],
        }
    )

    with pytest.raises(ScenarioError, match="absent from generated topology"):
        generate_integrated_topology(
            scenario,
            generator_version="mockgen-integrated-v1",
            alarm_resource_ids=("SYN-DEVICE-02",),
        )


def test_every_topology_derived_record_carries_declared_source_identity(
    hierarchy, active_path, failure_domain
):
    generated = (
        (hierarchy, generate_dependency_hierarchy(hierarchy, generator_version=VERSION)),
        (active_path, generate_active_paths(active_path, generator_version=VERSION)),
        (
            failure_domain,
            generate_failure_domains(failure_domain, generator_version=VERSION),
        ),
    )

    for scenario, (nodes, records) in generated:
        assert {
            (item.source_id, item.source_version) for item in (*nodes, *records)
        } == {
            (
                scenario.topology_source.source_id,
                scenario.topology_source.source_version,
            )
        }


# --------------------------------------------------------------------------
# SYN-* naming
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("SYN-CORE-01", True),
        ("SRLG-SYN-001", True),
        ("TICKET-SYN-001", True),
        ("DEHL01", False),
        ("HLC9102DEA01", False),
        # 'SYNTHETIC' is not the SYN token; only a real segment counts.
        ("SYNTHETIC01", False),
    ],
)
def test_synthetic_identifier_detection(identifier, expected):
    assert is_synthetic_identifier(identifier) is expected


def test_real_looking_identifiers_are_refused(tmp_path):
    """docs 07: never reuse real-looking IDs to make a demo look realistic."""
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenario_id": "bad_v1",
                "source_kind": "SYNTHETIC_TEST",
                "seed": 42,
                "topology_source": TOPOLOGY_SOURCE,
                "topology": {
                    "relation_type": "LOGICAL_DEPENDENCY",
                    "directed": True,
                    # Attaching real Golden resources to synthetic topology.
                    "edges": [["DEHL01", "DEHT01"]],
                },
            }
        ),
        encoding="utf-8",
    )
    scenario = load_scenario(path)
    with pytest.raises(ScenarioError, match="obviously synthetic"):
        generate_dependency_hierarchy(scenario, generator_version=VERSION)


# --------------------------------------------------------------------------
# Directed hierarchy
# --------------------------------------------------------------------------


def test_hierarchy_edges_are_directed_logical_dependency(hierarchy):
    nodes, edges = generate_dependency_hierarchy(hierarchy, generator_version=VERSION)
    assert len(nodes) == 7
    assert len(edges) == 6
    assert all(e.relation_type is RelationType.LOGICAL_DEPENDENCY for e in edges)
    assert all(e.directed for e in edges)
    assert all(e.source_kind is SourceKind.SYNTHETIC_TEST for e in edges)


def test_hierarchy_enables_only_hierarchy_capability(hierarchy):
    """The fixture declares dep_hop/shared_ancestor only; nothing else."""
    capability = hierarchy.expected_capability
    assert capability["dep_hop"] is True
    assert capability["shared_ancestor"] is True
    assert capability["shared_active_path"] is False
    assert capability["unavoidable_dependency"] is False

    # No active paths or failure domains are produced by this generator.
    _, edges = generate_dependency_hierarchy(hierarchy, generator_version=VERSION)
    assert all(e.relation_type is not RelationType.IP_ADJACENCY for e in edges)


def test_hierarchy_shares_an_ancestor(hierarchy):
    """SYN-DEA-HN-01 and -02 must share SYN-AGG-HN-01, else the fixture is useless."""
    _, edges = generate_dependency_hierarchy(hierarchy, generator_version=VERSION)
    parents: dict[str, set[str]] = {}
    for edge in edges:
        parents.setdefault(edge.target_resource_id, set()).add(edge.source_resource_id)
    assert parents["SYN-DEA-HN-01"] == {"SYN-AGG-HN-01"}
    assert parents["SYN-DEA-HN-02"] == {"SYN-AGG-HN-01"}
    assert parents["SYN-AGG-HN-01"] == {"SYN-CORE-01"}


def test_undirected_logical_dependency_is_refused(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenario_id": "s_v1",
                "source_kind": "SYNTHETIC_TEST",
                "seed": 42,
                "topology_source": TOPOLOGY_SOURCE,
                "topology": {
                    "relation_type": "LOGICAL_DEPENDENCY",
                    "directed": False,
                    "edges": [["SYN-A", "SYN-B"]],
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError, match="must declare directed=true"):
        generate_dependency_hierarchy(load_scenario(path), generator_version=VERSION)


def test_directed_ip_adjacency_is_refused_even_in_scenarios(tmp_path):
    """ADR-MOCK-0005 holds for synthetic data too."""
    path = tmp_path / "s.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenario_id": "s_v1",
                "source_kind": "SYNTHETIC_TEST",
                "seed": 42,
                "topology_source": TOPOLOGY_SOURCE,
                "topology": {
                    "relation_type": "IP_ADJACENCY",
                    "directed": True,
                    "edges": [["SYN-A", "SYN-B"]],
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError, match="IP_ADJACENCY cannot be directed"):
        generate_dependency_hierarchy(load_scenario(path), generator_version=VERSION)


# --------------------------------------------------------------------------
# Active path
# --------------------------------------------------------------------------


def test_active_paths_are_stored_explicitly(active_path):
    """Paths are verbatim node sequences, not inferred shortest paths."""
    _, paths = generate_active_paths(active_path, generator_version=VERSION)
    assert len(paths) == 2
    by_id = {p.path_id: p for p in paths}
    assert by_id["SYN-PATH-A"].nodes == ("SYN-DEA-A", "SYN-R1", "SYN-R2", "SYN-CORE-X")
    assert by_id["SYN-PATH-B"].nodes == ("SYN-DEA-B", "SYN-R3", "SYN-R2", "SYN-CORE-X")


def test_active_paths_share_the_declared_node(active_path):
    _, paths = generate_active_paths(active_path, generator_version=VERSION)
    shared = set(paths[0].nodes) & set(paths[1].nodes)
    assert active_path.expected_capability["shared_node"] in shared


def test_active_path_generator_emits_no_edges(active_path):
    """A path must not be silently expanded into adjacency edges."""
    nodes, paths = generate_active_paths(active_path, generator_version=VERSION)
    assert all(hasattr(p, "nodes") for p in paths)
    assert {n.resource_id for n in nodes} == {
        "SYN-DEA-A",
        "SYN-DEA-B",
        "SYN-R1",
        "SYN-R2",
        "SYN-R3",
        "SYN-CORE-X",
    }


def test_single_node_path_is_refused(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenario_id": "s_v1",
                "source_kind": "SYNTHETIC_TEST",
                "seed": 42,
                "topology_source": TOPOLOGY_SOURCE,
                "paths": [
                    {"path_id": "SYN-P1", "resource_id": "SYN-A", "nodes": ["SYN-A"]}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError, match="at least two nodes"):
        generate_active_paths(load_scenario(path), generator_version=VERSION)


# --------------------------------------------------------------------------
# Failure domains / H_domain
# --------------------------------------------------------------------------


def test_failure_domains_stay_hyperedges(failure_domain):
    """H_domain keeps set semantics; no pairwise edge is produced (ADR-0011)."""
    nodes, domains = generate_failure_domains(
        failure_domain, generator_version=VERSION
    )
    assert len(domains) == 2
    by_id = {d.failure_domain_id: d for d in domains}
    assert by_id["SRLG-SYN-001"].members == ("SYN-DEA-A", "SYN-DEA-B", "SYN-DEA-C")
    assert by_id["SRLG-SYN-001"].domain_type is FailureDomainType.SRLG
    assert by_id["POWER-SYN-01"].members == ("SYN-DEA-B", "SYN-DEA-D")
    # The generator returns nodes and domains only, never edges.
    assert all(hasattr(d, "members") for d in domains)
    assert len(nodes) == 4


def test_clique_projection_is_refused(tmp_path):
    """A 3-member SRLG must not become C(3,2)=3 pair edges."""
    path = tmp_path / "s.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenario_id": "s_v1",
                "source_kind": "SYNTHETIC_TEST",
                "seed": 42,
                "topology_source": TOPOLOGY_SOURCE,
                "failure_domains": [
                    {
                        "failure_domain_id": "SRLG-SYN-001",
                        "domain_type": "SRLG",
                        "members": ["SYN-A", "SYN-B", "SYN-C"],
                    }
                ],
                "rules": {"clique_project": True},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError, match="hyperedges"):
        generate_failure_domains(load_scenario(path), generator_version=VERSION)


def test_shipped_failure_domain_fixture_disables_clique_projection(failure_domain):
    assert failure_domain.rules["clique_project"] is False


def test_unknown_domain_type_is_refused(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenario_id": "s_v1",
                "source_kind": "SYNTHETIC_TEST",
                "seed": 42,
                "topology_source": TOPOLOGY_SOURCE,
                "failure_domains": [
                    {
                        "failure_domain_id": "X-SYN-1",
                        "domain_type": "MADE_UP",
                        "members": ["SYN-A"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError, match="unknown domain_type"):
        generate_failure_domains(load_scenario(path), generator_version=VERSION)


# --------------------------------------------------------------------------
# Operational context
# --------------------------------------------------------------------------


def test_context_entries_carry_matching_subtypes(context_scenario):
    contexts = generate_operational_context(
        context_scenario, generator_version=VERSION
    )
    assert len(contexts) == 2
    by_id = {c.context_id: c for c in contexts}
    assert by_id["MAINT-SYN-001"].provenance_subtype is ProvenanceSubtype.MAINTENANCE
    assert by_id["TICKET-SYN-001"].provenance_subtype is ProvenanceSubtype.TICKET
    assert all(
        c.provenance_class is ProvenanceClass.EXTERNAL_OPERATIONAL for c in contexts
    )


def test_context_claiming_real_validation_is_refused(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenario_id": "s_v1",
                "source_kind": "SYNTHETIC_TEST",
                "seed": 42,
                "context": [
                    {
                        "context_id": "TICKET-SYN-9",
                        "type": "TICKET",
                        "affected_resources": ["SYN-A"],
                    }
                ],
                "validation": {"eligible_as_real_operational_validation": True},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError, match="refused"):
        generate_operational_context(load_scenario(path), generator_version=VERSION)


def test_shipped_context_fixture_denies_real_validation(context_scenario):
    assert (
        context_scenario.validation["eligible_as_real_operational_validation"] is False
    )


# --------------------------------------------------------------------------
# Synthetic never validates
# --------------------------------------------------------------------------


def test_every_generated_object_is_synthetic_and_cannot_validate(
    hierarchy, active_path, failure_domain, context_scenario
):
    """The central anti-circularity check for all four generators."""
    produced = []
    nodes, edges = generate_dependency_hierarchy(hierarchy, generator_version=VERSION)
    produced.extend([*nodes, *edges])
    nodes, paths = generate_active_paths(active_path, generator_version=VERSION)
    produced.extend([*nodes, *paths])
    nodes, domains = generate_failure_domains(failure_domain, generator_version=VERSION)
    produced.extend([*nodes, *domains])
    produced.extend(generate_operational_context(context_scenario, generator_version=VERSION))

    assert produced
    for obj in produced:
        assert obj.source_kind is SourceKind.SYNTHETIC_TEST
        assert not is_validation_eligible(obj.source_kind)
        assert obj.generation is not None
        assert obj.generation.scenario_id
        assert obj.generation.generation_rule
        assert obj.generation.generator_version == VERSION
        assert obj.generation.seed == 42


def test_synthetic_topology_declares_confirmed_not_used(hierarchy):
    """Provable here: the data did not exist during any chaining run."""
    _, edges = generate_dependency_hierarchy(hierarchy, generator_version=VERSION)
    assert {e.chaining_usage.usage for e in edges} == {"CONFIRMED_NOT_USED"}
    # It still cannot validate, because the source-kind gate rejects it first.
    assert not is_validation_eligible(edges[0].source_kind)


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_same_seed_produces_identical_output(
    hierarchy, active_path, failure_domain, context_scenario
):
    """docs 07/13: same input + seed => byte-equivalent output."""
    for scenario, generator in (
        (hierarchy, generate_dependency_hierarchy),
        (active_path, generate_active_paths),
        (failure_domain, generate_failure_domains),
    ):
        first = generator(scenario, generator_version=VERSION)
        second = generator(scenario, generator_version=VERSION)
        assert first == second

    assert generate_operational_context(
        context_scenario, generator_version=VERSION
    ) == generate_operational_context(context_scenario, generator_version=VERSION)


def test_reloading_a_scenario_gives_identical_output(hierarchy):
    """Determinism must survive a fresh parse, not just a repeated call."""
    reloaded = load_scenario(SYNTHETIC_DIR / "scenario_dependency_hierarchy.yaml")
    assert generate_dependency_hierarchy(
        hierarchy, generator_version=VERSION
    ) == generate_dependency_hierarchy(reloaded, generator_version=VERSION)


def test_generated_objects_serialize_deterministically(failure_domain):
    from nocpro_mock.contract import Topology

    _, domains = generate_failure_domains(failure_domain, generator_version=VERSION)
    topology = Topology(failure_domains=domains)
    assert package_to_json(topology) == package_to_json(topology)
