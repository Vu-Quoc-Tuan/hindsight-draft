"""Exact dependency-scope overlap statistics and independent orchestration."""

from __future__ import annotations

from dataclasses import replace

import pytest

from configuration import ConfiguredValue, DependencyScopeConfig, ParameterSource, PropagationConfig
from libs.contracts import IngestedAlarm, IngestedChain, IngestedPackage, IngestedSnapshot
from libs.provenance import ProvenanceClass, ProvenanceSubtype
from tier2.topology_hypotheses import (
    DependencyScopeResult,
    DirectedUniverse,
    DominatorResult,
    HypothesisStatus,
    ResourceDetails,
    TopologyHypothesesResult,
    TopologyHypothesisReason,
    analyze_common_dominator,
    analyze_dependency_scope,
    analyze_topology_hypotheses,
)


def _cv(path: str, value: int, source=ParameterSource.FROZEN_SPEC) -> ConfiguredValue:
    return ConfiguredValue(path=f"dependency_scope.{path}", value=value, source=source)


@pytest.fixture()
def scope_config() -> DependencyScopeConfig:
    return DependencyScopeConfig(
        max_scope_resources=_cv("limits.max_scope_resources", 20),
        max_materialized_resources=_cv("limits.max_materialized_resources", 20),
    )


def _edge(source: str, target: str) -> dict:
    return {
        "edge_id": f"synthetic-topology:{source}:{target}",
        "source_resource_id": source,
        "target_resource_id": target,
        "relation_type": "LOGICAL_DEPENDENCY",
        "directed": True,
        "source_id": "synthetic-topology",
        "source_version": "v1",
        "source_kind": "SYNTHETIC_TEST",
        "provenance_class": "EXTERNAL_OPERATIONAL",
        "provenance_subtype": "TOPOLOGY_EXTERNAL",
    }


def _mapping(alarm_id: str, resource_id: str) -> dict:
    return {
        "alarm_id": alarm_id,
        "resource_id": resource_id,
        "mapping_status": "EXACT",
        "mapping_method": "EXACT_IDENTITY",
    }


def _package(edges: list[dict], resources: dict[str, str]) -> IngestedPackage:
    alarms = {
        alarm_id: IngestedAlarm(
            alarm_id=alarm_id,
            snapshot_id="S1",
            raw={},
            canonical_start_time="2026-08-30T00:00:00Z",
        )
        for alarm_id in resources
    }
    return IngestedPackage(
        snapshot=IngestedSnapshot(
            snapshot_id="S1",
            snapshot_version="snapshot-v1",
            snapshot_time="2026-08-30T00:00:00Z",
            status="COMPLETE",
            source="synthetic-fixture",
            source_kind="SYNTHETIC_TEST",
            produced_at="2026-08-30T00:00:00Z",
            topology_version="topology-v1",
        ),
        alarms=alarms,
        chains={"C1": IngestedChain("C1", "S1", len(resources))},
        memberships={"C1": list(resources)},
        topology={
            "edges": edges,
            "mappings": [_mapping(alarm_id, resource) for alarm_id, resource in resources.items()],
        },
    )


def _dominator_fixture() -> IngestedPackage:
    return _package(
        [
            _edge("ROOT", "WITNESS"),
            _edge("WITNESS", "OBSERVED_A"),
            _edge("WITNESS", "OBSERVED_B"),
            _edge("WITNESS", "EXTRA_A"),
            _edge("WITNESS", "EXTRA_B"),
            _edge("WITNESS", "EXTRA_C"),
        ],
        {"A": "OBSERVED_A", "B": "OBSERVED_B", "C": "OUTSIDE"},
    )


def _manual_dominator(observed: tuple[str, ...], *, empty_scope: bool = False) -> DominatorResult:
    scope_nodes = ("OBSERVED_A", "OBSERVED_B", "EXTRA_A", "EXTRA_B", "EXTRA_C")
    nodes = ("ROOT", "WITNESS", *scope_nodes, "OUTSIDE")
    successors = {node: () for node in nodes}
    successors["ROOT"] = ("WITNESS",)
    if not empty_scope:
        successors["WITNESS"] = scope_nodes
    predecessors = {node: () for node in nodes}
    predecessors["WITNESS"] = ("ROOT",)
    for resource in scope_nodes:
        predecessors[resource] = ("WITNESS",) if not empty_scope else ()
    universe = DirectedUniverse(
        source_ref="synthetic-topology@v1",
        relation_type="LOGICAL_DEPENDENCY",
        nodes=nodes,
        predecessors=predecessors,
        successors=successors,
        provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
        provenance_subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
        source_kind="SYNTHETIC_TEST",
        source_version="v1",
    )
    return DominatorResult(
        status=HypothesisStatus.AVAILABLE,
        reason=None,
        semantic="UNAVOIDABLE_DEPENDENCY",
        witness_resource_id="WITNESS",
        covered_resource_ids=observed,
        source_ref=universe.source_ref,
        relation_type=universe.relation_type,
        provenance_class=universe.provenance_class,
        provenance_subtype=universe.provenance_subtype,
        source_kind=universe.source_kind,
        universe=universe,
    )


def test_scope_aggregates_and_complete_details_use_observed_minus_scope_signs(scope_config):
    package = _dominator_fixture()
    dominator = _manual_dominator(("OBSERVED_A", "OBSERVED_B", "OUTSIDE"))
    result = analyze_dependency_scope(package, dominator, scope_config)

    assert result.status is HypothesisStatus.AVAILABLE
    assert result.intersection_count == 2
    assert result.union_count == 6
    assert result.observed_resource_count == 3
    assert result.scope_resource_count == 5
    assert result.missing_resource_count == 1
    assert result.extra_resource_count == 3
    assert result.observed_coverage == pytest.approx(2 / 3)
    assert result.scope_precision == pytest.approx(2 / 5)
    assert result.jaccard == pytest.approx(2 / 6)
    assert result.resource_details.status is HypothesisStatus.AVAILABLE
    assert result.resource_details.missing_resources == ("OUTSIDE",)
    assert result.resource_details.extra_resources == ("EXTRA_A", "EXTRA_B", "EXTRA_C")


def test_scope_aggregates_remain_exact_when_details_are_too_large(scope_config):
    package = _dominator_fixture()
    dominator = _manual_dominator(("OBSERVED_A", "OBSERVED_B", "OUTSIDE"))
    config = replace(
        scope_config,
        max_materialized_resources=_cv(
            "limits.max_materialized_resources", 1
        ),
    )
    result = analyze_dependency_scope(package, dominator, config)

    assert result.status is HypothesisStatus.AVAILABLE
    assert result.intersection_count == 2
    assert result.missing_resource_count == 1
    assert result.extra_resource_count == 3
    assert result.resource_details.status is HypothesisStatus.UNAVAILABLE
    assert result.resource_details.reason is TopologyHypothesisReason.MATERIALIZATION_LIMIT_EXCEEDED
    assert result.resource_details.missing_resources is None
    assert result.resource_details.extra_resources is None


def test_scope_empty_observed_and_empty_scope_are_explicit_unavailable(scope_config):
    package = _package([_edge("ROOT", "WITNESS")], {"A": "WITNESS"})
    dominator = _manual_dominator(("WITNESS",), empty_scope=True)
    result = analyze_dependency_scope(package, dominator, scope_config)
    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.DEPENDENCY_SCOPE_UNAVAILABLE


def test_scope_computation_ceiling_keeps_actual_count_without_sampling(scope_config):
    package = _dominator_fixture()
    dominator = _manual_dominator(("OBSERVED_A", "OBSERVED_B", "OUTSIDE"))
    config = replace(
        scope_config,
        max_scope_resources=_cv("limits.max_scope_resources", 2),
        max_materialized_resources=_cv("limits.max_materialized_resources", 2),
    )
    result = analyze_dependency_scope(package, dominator, config)
    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.SCOPE_LIMIT_EXCEEDED
    assert result.scope_resource_count == 5
    assert result.resource_details.missing_resources is None


def test_orchestration_keeps_independent_results_and_missing_configs(scope_config):
    package = _package(
        [_edge("ROOT", "WITNESS"), _edge("WITNESS", "OBSERVED_A"), _edge("WITNESS", "OBSERVED_B")],
        {"A": "OBSERVED_A", "B": "OBSERVED_B"},
    )
    from configuration import P2TopologyConfig
    result = analyze_topology_hypotheses(
        package,
        "C1",
        P2TopologyConfig(None, "missing", scope_config, None),
    )
    assert isinstance(result, TopologyHypothesesResult)
    assert result.dominator.status is HypothesisStatus.AVAILABLE
    assert result.scope.status is HypothesisStatus.AVAILABLE
    assert result.propagation.status is HypothesisStatus.UNAVAILABLE
    assert result.propagation.reason is TopologyHypothesisReason.PROPAGATION_CONFIG_INCOMPLETE
