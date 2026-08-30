"""Exact fail-closed P2 common-dominator annotations (ADR-0033)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from libs.contracts import (
    IngestedAlarm,
    IngestedChain,
    IngestedPackage,
    IngestedSnapshot,
    load_validated_package,
)
from libs.provenance import ProvenanceClass, ProvenanceSubtype
from tier2.topology_hypotheses import (
    DirectedUniverse,
    DominatorResult,
    HypothesisStatus,
    TopologyHypothesisReason,
    analyze_common_dominator,
    build_directed_universes,
)


def _package(
    edges: list[dict],
    mappings: list[dict],
    *,
    members: tuple[str, ...] = ("A", "B"),
) -> IngestedPackage:
    snapshot = IngestedSnapshot(
        snapshot_id="S1",
        snapshot_version="snapshot-v1",
        snapshot_time="2026-08-30T00:00:00Z",
        status="COMPLETE",
        source="synthetic-fixture",
        source_kind="SYNTHETIC_TEST",
        produced_at="2026-08-30T00:00:00Z",
        topology_version="topology-v1",
    )
    alarms = {
        alarm_id: IngestedAlarm(alarm_id=alarm_id, snapshot_id="S1", raw={})
        for alarm_id in members
    }
    return IngestedPackage(
        snapshot=snapshot,
        alarms=alarms,
        chains={"C1": IngestedChain("C1", "S1", len(members))},
        memberships={"C1": list(members)},
        topology={"edges": edges, "mappings": mappings},
    )


def _edge(
    source: str,
    target: str,
    *,
    edge_id: str | None = None,
    source_id: str = "synthetic-topology",
    source_version: str = "v1",
    relation_type: str = "LOGICAL_DEPENDENCY",
    directed: bool = True,
    source_kind: str = "SYNTHETIC_TEST",
) -> dict:
    return {
        "edge_id": edge_id or f"{source}-{target}",
        "source_resource_id": source,
        "target_resource_id": target,
        "relation_type": relation_type,
        "directed": directed,
        "source_id": source_id,
        "source_version": source_version,
        "source_kind": source_kind,
        "provenance_class": "EXTERNAL_OPERATIONAL",
        "provenance_subtype": "TOPOLOGY_EXTERNAL",
    }


def _mapping(alarm_id: str, resource_id: str | None, status: str = "EXACT") -> dict:
    return {
        "alarm_id": alarm_id,
        "resource_id": resource_id,
        "mapping_status": status,
        "mapping_method": "EXACT_IDENTITY" if status == "EXACT" else "NONE",
    }


@pytest.fixture()
def package() -> IngestedPackage:
    return _package(
        [
            _edge("ROOT", "CORE"),
            _edge("CORE", "LEAF_A"),
            _edge("CORE", "LEAF_B"),
        ],
        [_mapping("A", "LEAF_A"), _mapping("B", "LEAF_B")],
    )


def test_chain_common_strict_dominator_is_annotation_only(package: IngestedPackage):
    result = analyze_common_dominator(package, "C1")

    assert result.status is HypothesisStatus.AVAILABLE
    assert result.reason is None
    assert result.semantic == "UNAVOIDABLE_DEPENDENCY"
    assert result.witness_resource_id == "CORE"
    assert result.covered_resource_ids == ("LEAF_A", "LEAF_B")
    assert result.source_ref == "synthetic-topology@v1"
    assert result.relation_type == "LOGICAL_DEPENDENCY"
    assert result.source_kind == "SYNTHETIC_TEST"
    assert not hasattr(result, "positive_score")


def test_directed_universes_are_isolated_by_source_and_relation(
    package: IngestedPackage,
):
    service_edge = _edge(
        "SERVICE_ROOT",
        "SERVICE_LEAF",
        source_id="service-cmdb",
        source_version="v9",
        relation_type="SERVICE_DEPENDS_ON",
    )
    universes = build_directed_universes(
        replace(package, topology={**package.topology, "edges": [*package.topology["edges"], service_edge]})
    )

    assert [(u.source_ref, u.relation_type) for u in universes] == [
        ("service-cmdb@v9", "SERVICE_DEPENDS_ON"),
        ("synthetic-topology@v1", "LOGICAL_DEPENDENCY"),
    ]
    assert universes[0].nodes == ("SERVICE_LEAF", "SERVICE_ROOT")
    assert universes[1].nodes == ("CORE", "LEAF_A", "LEAF_B", "ROOT")
    assert universes[1].predecessors["LEAF_A"] == ("CORE",)
    assert universes[1].successors["CORE"] == ("LEAF_A", "LEAF_B")


def test_public_result_models_normalize_mutable_collections_to_immutable_tuples():
    universe = DirectedUniverse(
        source_ref="source@v1",
        relation_type="LOGICAL_DEPENDENCY",
        nodes=["ROOT"],
        predecessors={"ROOT": []},
        successors={"ROOT": []},
        provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
        provenance_subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
        source_kind="SYNTHETIC_TEST",
        source_version="v1",
    )
    result = DominatorResult(
        status=HypothesisStatus.AVAILABLE,
        reason=None,
        semantic="UNAVOIDABLE_DEPENDENCY",
        witness_resource_id="ROOT",
        covered_resource_ids=["ROOT"],
        source_ref="source@v1",
        relation_type="LOGICAL_DEPENDENCY",
        provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
        provenance_subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
        source_kind="SYNTHETIC_TEST",
    )

    assert universe.nodes == ("ROOT",)
    assert universe.predecessors["ROOT"] == ()
    assert universe.successors["ROOT"] == ()
    assert result.covered_resource_ids == ("ROOT",)


def test_missing_topology_source_identity_cannot_create_a_dominator_universe(
    package: IngestedPackage,
):
    source_unknown_edges = [
        {**edge, "source_id": "", "source_version": ""}
        for edge in package.topology["edges"]
    ]

    result = analyze_common_dominator(
        replace(package, topology={**package.topology, "edges": source_unknown_edges}),
        "C1",
    )

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.DIRECTED_TOPOLOGY_UNAVAILABLE


def test_whitespace_distinct_source_identities_cannot_be_merged_into_a_witness():
    package = _package(
        [
            _edge("ROOT", "CORE", source_id="source"),
            _edge("CORE", "LEAF_A", source_id="source"),
            _edge("CORE", "LEAF_B", source_id=" source"),
        ],
        [_mapping("A", "LEAF_A"), _mapping("B", "LEAF_B")],
    )

    result = analyze_common_dominator(package, "C1")

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.COMMON_DOMINATOR_UNAVAILABLE


def test_validated_omitted_topology_subtype_uses_the_contract_default():
    payload = {
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": "S2",
            "snapshot_version": "snapshot-v2",
            "snapshot_time": "2026-08-30T00:00:00Z",
            "status": "COMPLETE",
            "source": "real-export-fixture",
            "source_kind": "REAL_EXPORT_REPLAY",
            "produced_at": "2026-08-30T00:00:00Z",
            "topology_version": "topology-v2",
        },
        "alarms": [
            {
                "alarm_id": alarm_id,
                "snapshot_id": "S2",
                "source_kind": "REAL_EXPORT_REPLAY",
                "provenance_class": "SYSTEM_FACT",
                "raw": {},
            }
            for alarm_id in ("A", "B")
        ],
        "chains": [
            {
                "chain_id": "C1",
                "snapshot_id": "S2",
                "member_count": 2,
                "source_kind": "REAL_EXPORT_REPLAY",
                "provenance_class": "SYSTEM_FACT",
            }
        ],
        "memberships": [
            {
                "chain_id": "C1",
                "alarm_id": alarm_id,
                "snapshot_id": "S2",
                "source_kind": "REAL_EXPORT_REPLAY",
            }
            for alarm_id in ("A", "B")
        ],
        "topology": {
            "edges": [
                {
                    "edge_id": edge_id,
                    "source_resource_id": source,
                    "target_resource_id": target,
                    "relation_type": "LOGICAL_DEPENDENCY",
                    "directed": True,
                    "source_id": "topology-source",
                    "source_version": "v2",
                    "source_kind": "REAL_EXPORT_REPLAY",
                }
                for edge_id, source, target in (
                    ("E1", "ROOT", "CORE"),
                    ("E2", "CORE", "LEAF_A"),
                    ("E3", "CORE", "LEAF_B"),
                )
            ],
            "mappings": [
                _mapping("A", "LEAF_A"),
                _mapping("B", "LEAF_B"),
            ],
        },
    }

    result = analyze_common_dominator(load_validated_package(payload), "C1")

    assert result.status is HypothesisStatus.AVAILABLE
    assert result.provenance_subtype is ProvenanceSubtype.TOPOLOGY_EXTERNAL


def test_cycle_reachable_from_a_root_has_an_exact_common_dominator():
    package = _package(
        [
            _edge("ROOT", "CORE"),
            _edge("CORE", "LEAF_A"),
            _edge("LEAF_A", "LEAF_B"),
            _edge("LEAF_B", "LEAF_A"),
        ],
        [_mapping("A", "LEAF_A"), _mapping("B", "LEAF_B")],
    )

    result = analyze_common_dominator(package, "C1")

    assert result.status is HypothesisStatus.AVAILABLE
    assert result.witness_resource_id == "CORE"


def test_unreachable_directed_cycle_fails_closed():
    package = _package(
        [
            _edge("ROOT", "CORE"),
            _edge("CORE", "LEAF_A"),
            _edge("CORE", "LEAF_B"),
            _edge("ORPHAN_A", "ORPHAN_B"),
            _edge("ORPHAN_B", "ORPHAN_A"),
        ],
        [_mapping("A", "LEAF_A"), _mapping("B", "LEAF_B")],
    )

    result = analyze_common_dominator(package, "C1")

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.COMMON_DOMINATOR_UNAVAILABLE


def test_multiple_roots_without_a_common_real_witness_is_unavailable():
    package = _package(
        [_edge("ROOT_A", "LEAF_A"), _edge("ROOT_B", "LEAF_B")],
        [_mapping("A", "LEAF_A"), _mapping("B", "LEAF_B")],
    )

    result = analyze_common_dominator(package, "C1")

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.COMMON_DOMINATOR_UNAVAILABLE


@pytest.mark.parametrize("status", ["UNMAPPED", "AMBIGUOUS"])
def test_unmapped_or_ambiguous_chain_member_is_unavailable(
    package: IngestedPackage, status: str
):
    mappings = [_mapping("A", "LEAF_A"), _mapping("B", None, status)]

    result = analyze_common_dominator(
        replace(package, topology={**package.topology, "mappings": mappings}), "C1"
    )

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.RESOURCE_MAPPING_UNAVAILABLE


def test_two_eligible_universes_with_different_witnesses_are_ambiguous():
    package = _package(
        [
            _edge("ROOT", "CORE_ONE", source_id="source-one"),
            _edge("CORE_ONE", "LEAF_A", source_id="source-one"),
            _edge("CORE_ONE", "LEAF_B", source_id="source-one"),
            _edge("ROOT", "CORE_TWO", source_id="source-two"),
            _edge("CORE_TWO", "LEAF_A", source_id="source-two"),
            _edge("CORE_TWO", "LEAF_B", source_id="source-two"),
        ],
        [_mapping("A", "LEAF_A"), _mapping("B", "LEAF_B")],
    )

    result = analyze_common_dominator(package, "C1")

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.AMBIGUOUS_DOMINATOR_WITNESS


def test_ip_adjacency_cannot_enable_dominator(package: IngestedPackage):
    production_style_package = replace(
        package,
        topology={
            **package.topology,
            "edges": [
                _edge(
                    "ROOT",
                    "CORE",
                    relation_type="IP_ADJACENCY",
                    directed=False,
                    source_kind="REAL_EXPORT_REPLAY",
                ),
                _edge(
                    "CORE",
                    "LEAF_A",
                    relation_type="IP_ADJACENCY",
                    directed=False,
                    source_kind="REAL_EXPORT_REPLAY",
                ),
                _edge(
                    "CORE",
                    "LEAF_B",
                    relation_type="IP_ADJACENCY",
                    directed=False,
                    source_kind="REAL_EXPORT_REPLAY",
                ),
            ],
        },
    )

    result = analyze_common_dominator(production_style_package, "C1")

    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.DIRECTED_TOPOLOGY_UNAVAILABLE
