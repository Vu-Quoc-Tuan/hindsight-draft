from __future__ import annotations

from libs.contracts.analysis_identity import AnalysisIdentity
from nocpro_api.evidence_projection import (
    StaleEvidenceCursor,
    attach_evidence_references,
    build_evidence_bundle,
    build_evidence_records,
)


def _identity(**overrides) -> AnalysisIdentity:
    values = {
        "snapshot_id": "snapshot-A",
        "snapshot_version": "7",
        "chain_id": "CHAIN-1",
        "topology_version": "topology-9",
        "analysis_config_version": "analysis-cfg-3",
        "review_config_version": "review-cfg-2",
        "pipeline_version": "DETERMINISTIC_QUALITY_V6",
        "input_fingerprint": "quality-fingerprint-1",
    }
    values.update(overrides)
    return AnalysisIdentity(**values)


def _overview(path: list[str] | None = None) -> dict:
    path = path or ["R-A", "R-B"]
    return {
        "analysis_identity": _identity().to_payload(),
        "topology": {
            "status": "AVAILABLE",
            "mapped": 5,
            "mapped_alarm_count": 5,
            "total": 5,
            "mapped_device_count": 4,
            "total_device_count": 4,
            "connected_pair_count": 1,
            "pair_total": 1,
            "mapped_resources": [path[0], path[-1]],
            "display_paths_truncated": False,
            "display_paths": [{
                "source": path[0],
                "target": path[-1],
                "source_devices": ["DEVICE-A"],
                "target_devices": ["DEVICE-B"],
                "hop_count": len(path) - 1,
                "max_hops": 4,
                "path": path,
                "relation_type": "IP_ADJACENCY",
                "traversal_semantic": "UNDIRECTED_STRUCTURAL_CONNECTIVITY",
                "mapping_statuses": ["EXACT", "VERIFIED_ALIAS"],
            }],
        },
        "quality_assessment": {
            "status": "EVALUATED",
            "readiness": "READY",
            "stars": 4,
            "reason_codes": [],
            "evidence_coverage": {
                "membership": {"evaluated": 5, "total": 5, "ratio": 1.0},
                "audit": {"status": "EVALUATED", "complete": True},
                "review": {"status": "COMPLETED"},
            },
        },
        "recommendations": {
            "status": "NO_CLEAR_ALTERNATIVE",
            "evaluation_completed": True,
            "evaluated_count": 0,
            "count": 0,
        },
    }


def _record(bundle: dict, kind: str, *, semantic: str | None = None) -> dict:
    matches = [record for record in bundle["records"] if record["kind"] == kind]
    if semantic is not None:
        matches = [
            record for record in matches
            if record.get("path", {}).get("traversal_semantic") == semantic
        ]
    assert matches
    return matches[0]


def test_four_hop_overview_witness_is_complete_and_stable():
    projection = _overview(["R-A", "X", "Y", "Z", "R-B"])
    first = build_evidence_bundle(
        identity=_identity(),
        overview_projection=projection,
        pair_evidence=None,
        audit_artifact=None,
        review_result=None,
    )
    second = build_evidence_bundle(
        identity=_identity(),
        overview_projection=projection,
        pair_evidence=None,
        audit_artifact=None,
        review_result=None,
    )

    witness = _record(
        first,
        "TOPOLOGY_PATH",
        semantic="UNDIRECTED_STRUCTURAL_CONNECTIVITY",
    )
    assert witness["path"] == {
        "resource_ids": ["R-A", "X", "Y", "Z", "R-B"],
        "relation_types": ["IP_ADJACENCY"] * 4,
        "hop_count": 4,
        "traversal_semantic": "UNDIRECTED_STRUCTURAL_CONNECTIVITY",
        "max_hops": 4,
        "topology_version": "topology-9",
        "mapping_statuses": ["EXACT", "VERIFIED_ALIAS"],
        "analysis_truncated": False,
    }
    assert witness["evidence_id"] == _record(
        second,
        "TOPOLOGY_PATH",
        semantic="UNDIRECTED_STRUCTURAL_CONNECTIVITY",
    )["evidence_id"]
    assert witness["analysis_identity"] == _identity().to_payload()


def test_pair_why_three_hop_witness_is_not_equal_to_overview_path():
    projection = _overview(["R-A", "X", "Y", "R-B"])
    pair_evidence = [{
        "alarm_id_a": "ALARM-A",
        "alarm_id_b": "ALARM-B",
        "evidence": [{
            "channel_family": "Dep_hop",
            "state": "SUPPORT",
            "source_id": "nms-export",
            "source_version": "inventory-14",
            "evidence_metadata": {
                "topology_path": {
                    "nodes": ["R-A", "X", "Y", "R-B"],
                    "hop_count": 3,
                    "max_hops": 3,
                    "relation_types": ["IP_ADJACENCY"],
                    "edge_relation_types": ["IP_ADJACENCY"] * 3,
                    "traversal_semantic": "STRUCTURAL_TOPOLOGY_PATH_NOT_CAUSAL",
                    "direction_policy": "SOURCE_EDGE_DIRECTION_PRESERVED",
                    "mapping_statuses": ["EXACT", "VERIFIED_ALIAS"],
                },
            },
        }],
    }]

    bundle = build_evidence_bundle(
        identity=_identity(),
        overview_projection=projection,
        pair_evidence=pair_evidence,
        audit_artifact=None,
        review_result=None,
    )
    records = [
        record for record in bundle["records"]
        if record["kind"] == "TOPOLOGY_PATH"
    ]
    overview = next(
        record for record in records
        if record["path"]["traversal_semantic"] == "UNDIRECTED_STRUCTURAL_CONNECTIVITY"
    )
    pair = next(
        record for record in records
        if record["path"]["traversal_semantic"] == "STRUCTURAL_TOPOLOGY_PATH_NOT_CAUSAL"
    )

    assert pair["path"]["hop_count"] == 3
    assert pair["path"]["max_hops"] == 3
    assert len(pair["path"]["relation_types"]) == 3
    assert pair["path"]["mapping_statuses"] == ["EXACT", "VERIFIED_ALIAS"]
    assert pair["evidence_id"] != overview["evidence_id"]


def test_display_truncation_is_not_mislabeled_as_analysis_truncation():
    projection = _overview()
    projection["topology"]["status"] = "PARTIAL"
    projection["topology"]["display_paths_truncated"] = True
    projection["topology"]["analysis_truncated"] = False

    bundle = build_evidence_bundle(
        identity=_identity(),
        overview_projection=projection,
        pair_evidence=None,
        audit_artifact=None,
        review_result=None,
    )
    witness = _record(
        bundle,
        "TOPOLOGY_PATH",
        semantic="UNDIRECTED_STRUCTURAL_CONNECTIVITY",
    )
    assert witness["path"]["analysis_truncated"] is False
    assert "TOPOLOGY_SOURCE_PARTIAL" in witness["reason_codes"]

    projection["topology"]["analysis_truncated"] = True
    truncated = build_evidence_bundle(
        identity=_identity(),
        overview_projection=projection,
        pair_evidence=None,
        audit_artifact=None,
        review_result=None,
    )
    truncated_witness = _record(
        truncated,
        "TOPOLOGY_PATH",
        semantic="UNDIRECTED_STRUCTURAL_CONNECTIVITY",
    )
    assert truncated_witness["path"]["analysis_truncated"] is True
    assert "TOPOLOGY_ANALYSIS_TRUNCATED" in truncated_witness["reason_codes"]


def test_absent_sources_are_explicit_and_never_fabricated_as_available():
    projection = _overview()
    projection["topology"] = None
    projection["quality_assessment"]["evidence_coverage"]["membership"] = None
    projection["quality_assessment"]["evidence_coverage"]["audit"] = {
        "status": "NOT_EVALUATED",
        "complete": False,
    }
    projection["recommendations"] = {"status": "NOT_EVALUATED", "count": 0}

    bundle = build_evidence_bundle(
        identity=_identity(),
        overview_projection=projection,
        pair_evidence=None,
        audit_artifact=None,
        review_result=None,
    )

    for kind in ("MAPPING", "MEMBERSHIP", "TOPOLOGY_PATH", "AUDIT", "REVIEW"):
        assert _record(bundle, kind)["status"] in {"UNAVAILABLE", "NOT_EVALUATED"}
        assert _record(bundle, kind)["reason_codes"]


def test_deterministic_claims_link_only_identity_bound_supporting_records():
    identity = _identity()
    projection = _overview()
    projection["quality_assessment"]["reason_codes"] = [
        "INSUFFICIENT_ROLE_COVERAGE",
        "AUDIT_NOT_EVALUATED",
        "REVIEW_NOT_COMPLETED",
    ]
    records = build_evidence_records(
        identity=identity,
        overview_projection=projection,
        pair_evidence=None,
        audit_artifact=None,
        review_result=None,
    )
    assessment = projection["quality_assessment"]
    findings = [
        {"finding_id": "SHARED_TOPOLOGY_CONTEXT"},
        {"finding_id": "AUDIT_EVIDENCE_GAP"},
        {"finding_id": "TEMPORAL_PROGRESSION"},
    ]

    attach_evidence_references(
        identity=identity,
        quality_assessment=assessment,
        analytical_findings=findings,
        records=records,
    )

    by_id = {record["evidence_id"]: record for record in records}
    assert set(assessment["evidence_ids"]) <= set(by_id)
    assert set(assessment["reason_evidence_ids"]["INSUFFICIENT_ROLE_COVERAGE"]) <= {
        record["evidence_id"] for record in records if record["kind"] == "MEMBERSHIP"
    }
    assert set(assessment["reason_evidence_ids"]["AUDIT_NOT_EVALUATED"]) <= {
        record["evidence_id"] for record in records if record["kind"] == "AUDIT"
    }
    assert findings[0]["evidence_ids"]
    assert all(by_id[item]["kind"] in {"MAPPING", "TOPOLOGY_PATH"} for item in findings[0]["evidence_ids"])
    assert findings[1]["evidence_ids"] == [
        record["evidence_id"] for record in records
        if record["kind"] == "AUDIT" and record["status"] != "AVAILABLE"
    ]
    assert findings[2]["evidence_ids"] == []

    other_identity = _identity(snapshot_version="another-snapshot-version")
    attach_evidence_references(
        identity=other_identity,
        quality_assessment=assessment,
        analytical_findings=findings,
        records=records,
    )
    assert assessment["evidence_ids"] == []
    assert all(not finding["evidence_ids"] for finding in findings)


def test_cursor_pages_by_evidence_id_and_rejects_a_different_identity():
    identity = _identity()
    first = build_evidence_bundle(
        identity=identity,
        overview_projection=_overview(["R-A", "X", "Y", "Z", "R-B"]),
        pair_evidence=None,
        audit_artifact=None,
        review_result=None,
        limit=2,
    )
    assert first["truncated"] is True
    assert first["next_cursor"]

    second = build_evidence_bundle(
        identity=identity,
        overview_projection=_overview(["R-A", "X", "Y", "Z", "R-B"]),
        pair_evidence=None,
        audit_artifact=None,
        review_result=None,
        limit=2,
        cursor=first["next_cursor"],
    )
    assert {record["evidence_id"] for record in first["records"]}.isdisjoint(
        {record["evidence_id"] for record in second["records"]}
    )

    try:
        build_evidence_bundle(
            identity=_identity(snapshot_version="8"),
            overview_projection=_overview(["R-A", "X", "Y", "Z", "R-B"]),
            pair_evidence=None,
            audit_artifact=None,
            review_result=None,
            limit=2,
            cursor=first["next_cursor"],
        )
    except StaleEvidenceCursor:
        pass
    else:
        raise AssertionError("cursor from another analysis identity must be rejected")
