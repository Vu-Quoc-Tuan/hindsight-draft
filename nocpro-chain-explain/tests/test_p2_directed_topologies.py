"""Tests for directed interpretation of IP and IT topology in Tier-2 P2 hypotheses."""

from __future__ import annotations

from configuration import load_analysis_config
from libs.contracts import IngestedAlarm, IngestedChain, IngestedPackage, IngestedSnapshot
from tier2.topology_hypotheses import HypothesisStatus, analyze_topology_hypotheses


def test_ip_topology_with_hierarchy_direction_enables_p2_hypotheses():
    package = IngestedPackage(
        snapshot=IngestedSnapshot(
            snapshot_id="s_ip",
            snapshot_version="1",
            snapshot_time="2026-09-01T00:00:00Z",
            status="COMPLETE",
            source="ip_network_test",
            source_kind="SYNTHETIC_TEST",
            produced_at="2026-09-01T00:00:00Z",
        ),
        alarms={
            "a1": IngestedAlarm("a1", "s_ip", raw={}, canonical_start_time="2026-09-01T00:00:00Z"),
            "a2": IngestedAlarm("a2", "s_ip", raw={}, canonical_start_time="2026-09-01T00:00:05Z"),
        },
        chains={"C1": IngestedChain("C1", "s_ip", 2)},
        memberships={"C1": ["a1", "a2"]},
        topology={
            "assume_directed": True,
            "edges": [
                {
                    "edge_id": "e1",
                    "source_resource_id": "DNG0527SRT01",
                    "target_resource_id": "DNG0047AGG01",
                    "relation_type": "IP_ADJACENCY",
                    "directed": False,
                    "source_id": "topo_ip",
                    "source_version": "v1",
                    "source_kind": "REAL_EXPORT_REPLAY",
                    "provenance_class": "EXTERNAL_OPERATIONAL",
                },
                {
                    "edge_id": "e2",
                    "source_resource_id": "DNG0527SRT01",
                    "target_resource_id": "DNG0048AGG02",
                    "relation_type": "IP_ADJACENCY",
                    "directed": False,
                    "source_id": "topo_ip",
                    "source_version": "v1",
                    "source_kind": "REAL_EXPORT_REPLAY",
                    "provenance_class": "EXTERNAL_OPERATIONAL",
                },
            ],
            "mappings": [
                {
                    "alarm_id": "a1",
                    "resource_id": "DNG0047AGG01",
                    "mapping_status": "EXACT_RESOURCE_ID",
                    "mapping_method": "EXACT_IDENTITY",
                },
                {
                    "alarm_id": "a2",
                    "resource_id": "DNG0048AGG02",
                    "mapping_status": "UNIQUE_SOURCE_FIELD_MATCH",
                    "mapping_method": "EXACT_IDENTITY",
                },
            ],
        },
    )

    cfg = load_analysis_config("config/thresholds/calibrated.yaml")
    result = analyze_topology_hypotheses(package, "C1", cfg)

    assert result.dominator.status is HypothesisStatus.AVAILABLE
    assert result.dominator.witness_resource_id == "DNG0527SRT01"
    assert result.dominator.covered_resource_ids == ("DNG0047AGG01", "DNG0048AGG02")

    assert result.propagation.status is HypothesisStatus.AVAILABLE
    assert len(result.propagation.node_scores) == 2

    assert result.dependency_scope.status is HypothesisStatus.AVAILABLE
    assert result.dependency_scope.observed_coverage == 1.0


def test_it_topology_hierarchical_relations_enable_p2_hypotheses():
    package = IngestedPackage(
        snapshot=IngestedSnapshot(
            snapshot_id="s_it",
            snapshot_version="1",
            snapshot_time="2026-09-01T00:00:00Z",
            status="COMPLETE",
            source="it_services_test",
            source_kind="SYNTHETIC_TEST",
            produced_at="2026-09-01T00:00:00Z",
        ),
        alarms={
            "a1": IngestedAlarm("a1", "s_it", raw={}, canonical_start_time="2026-09-01T00:00:00Z"),
            "a2": IngestedAlarm("a2", "s_it", raw={}, canonical_start_time="2026-09-01T00:00:05Z"),
        },
        chains={"C1": IngestedChain("C1", "s_it", 2)},
        memberships={"C1": ["a1", "a2"]},
        topology={
            "assume_directed": True,
            "edges": [
                {
                    "edge_id": "e1",
                    "source_resource_id": "it:service:billing",
                    "target_resource_id": "it:module:payments",
                    "relation_type": "SERVICE_HAS_MODULE",
                    "directed": True,
                    "source_id": "topoIT",
                    "source_version": "v1",
                    "source_kind": "REAL_EXPORT_REPLAY",
                    "provenance_class": "EXTERNAL_OPERATIONAL",
                },
                {
                    "edge_id": "e2",
                    "source_resource_id": "it:module:payments",
                    "target_resource_id": "it:instance:srv1",
                    "relation_type": "MODULE_HAS_INSTANCE",
                    "directed": True,
                    "source_id": "topoIT",
                    "source_version": "v1",
                    "source_kind": "REAL_EXPORT_REPLAY",
                    "provenance_class": "EXTERNAL_OPERATIONAL",
                },
                {
                    "edge_id": "e3",
                    "source_resource_id": "it:module:payments",
                    "target_resource_id": "it:instance:srv2",
                    "relation_type": "MODULE_HAS_INSTANCE",
                    "directed": True,
                    "source_id": "topoIT",
                    "source_version": "v1",
                    "source_kind": "REAL_EXPORT_REPLAY",
                    "provenance_class": "EXTERNAL_OPERATIONAL",
                },
            ],
            "mappings": [
                {
                    "alarm_id": "a1",
                    "resource_id": "it:instance:srv1",
                    "mapping_status": "EXACT_RESOURCE_ID",
                    "mapping_method": "EXACT_IDENTITY",
                },
                {
                    "alarm_id": "a2",
                    "resource_id": "it:instance:srv2",
                    "mapping_status": "VERIFIED_ALIAS",
                    "mapping_method": "VERIFIED_ALIAS_TABLE",
                },
            ],
        },
    )

    cfg = load_analysis_config("config/thresholds/calibrated.yaml")
    result = analyze_topology_hypotheses(package, "C1", cfg)

    assert result.dominator.status is HypothesisStatus.AVAILABLE
    assert result.dominator.witness_resource_id == "it:module:payments"
    assert result.dominator.covered_resource_ids == ("it:instance:srv1", "it:instance:srv2")

    assert result.propagation.status is HypothesisStatus.AVAILABLE
    assert result.dependency_scope.status is HypothesisStatus.AVAILABLE
    assert result.dependency_scope.observed_coverage == 1.0


def test_fail_closed_boundary_preserved_without_directed_flag():
    package = IngestedPackage(
        snapshot=IngestedSnapshot(
            snapshot_id="s_raw",
            snapshot_version="1",
            snapshot_time="2026-09-01T00:00:00Z",
            status="COMPLETE",
            source="raw_test",
            source_kind="SYNTHETIC_TEST",
            produced_at="2026-09-01T00:00:00Z",
        ),
        alarms={
            "a1": IngestedAlarm("a1", "s_raw", raw={}, canonical_start_time="2026-09-01T00:00:00Z"),
            "a2": IngestedAlarm("a2", "s_raw", raw={}, canonical_start_time="2026-09-01T00:00:05Z"),
        },
        chains={"C1": IngestedChain("C1", "s_raw", 2)},
        memberships={"C1": ["a1", "a2"]},
        topology={
            # assume_directed is False by default
            "edges": [
                {
                    "edge_id": "e1",
                    "source_resource_id": "DNG0527SRT01",
                    "target_resource_id": "DNG0047AGG01",
                    "relation_type": "IP_ADJACENCY",
                    "directed": False,
                    "source_id": "topo_ip",
                    "source_version": "v1",
                    "source_kind": "REAL_EXPORT_REPLAY",
                    "provenance_class": "EXTERNAL_OPERATIONAL",
                },
            ],
            "mappings": [
                {"alarm_id": "a1", "resource_id": "DNG0047AGG01", "mapping_status": "EXACT", "mapping_method": "EXACT_IDENTITY"},
                {"alarm_id": "a2", "resource_id": "DNG0047AGG01", "mapping_status": "EXACT", "mapping_method": "EXACT_IDENTITY"},
            ],
        },
    )

    cfg = load_analysis_config("config/thresholds/calibrated.yaml")
    result = analyze_topology_hypotheses(package, "C1", cfg)

    # Must remain UNAVAILABLE when undirected and assume_directed is not explicitly turned on
    assert result.dominator.status is HypothesisStatus.UNAVAILABLE
