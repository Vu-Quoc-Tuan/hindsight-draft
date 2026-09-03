"""A directed source-record relation must never promote itself into P2."""

from __future__ import annotations

from channels import build_dep_upstream_providers, build_directed_hierarchy
from channels.dependency import PHYSICAL_RELATIONS, build_topology_graph
from configuration import ConfiguredValue, DependencyScopeConfig, ParameterSource, PropagationConfig
from libs.contracts import IngestedAlarm, IngestedChain, IngestedPackage, IngestedSnapshot
from tier2.topology_hypotheses import (
    HypothesisStatus,
    analyze_common_dominator,
    analyze_dependency_scope,
    analyze_propagation,
    build_directed_universes,
)


def _configured(path: str, value: int | float) -> ConfiguredValue:
    return ConfiguredValue(path=path, value=value, source=ParameterSource.FROZEN_SPEC)


def _source_relation_package() -> IngestedPackage:
    return IngestedPackage(
        snapshot=IngestedSnapshot(
            snapshot_id="IT-RELATION-S1",
            snapshot_version="1",
            snapshot_time="2026-09-03T00:00:00Z",
            status="COMPLETE",
            source="it-source-relation-fixture",
            source_kind="SYNTHETIC_TEST",
            produced_at="2026-09-03T00:00:01Z",
        ),
        alarms={
            "A": IngestedAlarm("A", "IT-RELATION-S1", raw={}, canonical_start_time="2026-09-03T00:00:00Z"),
            "B": IngestedAlarm("B", "IT-RELATION-S1", raw={}, canonical_start_time="2026-09-03T00:00:05Z"),
        },
        chains={"C1": IngestedChain("C1", "IT-RELATION-S1", 2)},
        memberships={"C1": ["A", "B"]},
        topology={
            "edges": [
                {
                    "edge_id": "it:service:orders->it:module:billing",
                    "source_resource_id": "it:service:orders",
                    "target_resource_id": "it:module:billing",
                    "relation_type": "SOURCE_RELATION",
                    "directed": True,
                    "source_id": "topoIT",
                    "source_version": "fixture-v1",
                    "source_kind": "SYNTHETIC_TEST",
                    "provenance_class": "EXTERNAL_OPERATIONAL",
                    "provenance_subtype": "TOPOLOGY_EXTERNAL",
                }
            ],
            "mappings": [
                {"alarm_id": "A", "resource_id": "it:service:orders", "mapping_status": "EXACT", "mapping_method": "EXACT_IDENTITY"},
                {"alarm_id": "B", "resource_id": "it:module:billing", "mapping_status": "EXACT", "mapping_method": "EXACT_IDENTITY"},
            ],
        },
    )


def test_directed_source_relation_stays_navigation_only_for_all_p2_capabilities() -> None:
    package = _source_relation_package()
    propagation_config = PropagationConfig(
        config_version="source-relation-boundary-v1",
        restart_probability=_configured("propagation.rwr.restart_probability", 0.2),
        convergence_tolerance=_configured("propagation.rwr.convergence_tolerance", 1e-9),
        max_iterations=_configured("propagation.rwr.max_iterations", 100),
        decay_type="exponential",
        decay_parameter=_configured("propagation.temporal.decay_parameter", 10.0),
        score_threshold=_configured("propagation.acceptance.score_threshold", 0.5),
        max_candidate_edges=_configured("propagation.limits.max_candidate_edges", 10),
    )
    scope_config = DependencyScopeConfig(
        max_scope_resources=_configured("dependency_scope.limits.max_scope_resources", 10),
        max_materialized_resources=_configured("dependency_scope.limits.max_materialized_resources", 10),
    )

    # Arrow shape is deliberately insufficient: every operational provider
    # filters to its own explicitly promoted relation family.
    assert build_topology_graph(package, relation_types=PHYSICAL_RELATIONS).adjacency == {}
    assert build_directed_hierarchy(package.topology["edges"]).is_valid is False
    # Providers remain present so Pair WHY can explain *why* the capability is
    # unavailable; each one must still yield an unavailable channel value.
    assert all(
        provider.evaluate(package.alarms["A"], package.alarms["B"]).availability is False
        for provider in build_dep_upstream_providers(package)
    )
    assert build_directed_universes(package) == ()

    dominator = analyze_common_dominator(package, "C1")
    propagation = analyze_propagation(package, "C1", propagation_config)
    scope_overlap = analyze_dependency_scope(package, dominator, scope_config)

    assert dominator.status is HypothesisStatus.UNAVAILABLE
    assert propagation.status is HypothesisStatus.UNAVAILABLE
    assert scope_overlap.status is HypothesisStatus.UNAVAILABLE
