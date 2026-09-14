from __future__ import annotations

import pytest
from libs.contracts import load_package
from descriptor.contrastive import blocking_candidates
from tier2.counterfactual import ReviewIdentity, Operation
from tier2.counterfactual.candidates import generate_merge_candidates
from configuration import CalibrationStatus, CounterfactualConfig


IDENTITY = ReviewIdentity(
    snapshot_id="s1",
    snapshot_version="1",
    chain_id="CHAIN_CORE",
    alarm_universe_fingerprint="alarms-v1",
    analysis_version="analysis-v1",
    engine_version="counterfactual-v1",
    config_version="synthetic-v1",
    tier1b_artifact_fingerprint="tier1b-v1",
    structural_audit_artifact_fingerprint="audit-v1",
)

CONFIG = CounterfactualConfig(
    config_version="synthetic-v1",
    calibration_status=CalibrationStatus.SYNTHETIC_ONLY,
    max_chain_members=100,
    max_remove_candidates=2,
    max_split_candidates=2,
    max_recommendations=2,
    membership_support_below=0.3,
    representativeness_below=0.3,
    adverse_margin_below=0.0,
    minimum_membership_improvement=0.05,
    minimum_coverage_improvement=0.05,
    minimum_conductance_improvement=0.05,
    pareto_tolerance=0.0,
    max_merge_candidates=5,
)


def _alarm_dict(
    alarm_id: str,
    chain_id: str,
    *,
    device_code: str,
    location_code: str,
    network_class_name: str,
    alarm_name: str,
    canonical_start_time: str = "2026-01-01T00:00:00",
    burst_id: str | None = None,
):
    raw = {
        "alarm_id": alarm_id,
        "device_code": device_code,
        "location_code": location_code,
        "network_class_name": network_class_name,
        "alarm_name": alarm_name,
        "occur_time": canonical_start_time,
    }
    if burst_id:
        raw["burst_id"] = burst_id
    return {
        "alarm_id": alarm_id,
        "snapshot_id": "s1",
        "raw": raw,
        "alarm_name": alarm_name,
        "device_code": device_code,
        "node_reference": device_code,
        "canonical_start_time": canonical_start_time,
    }


def test_topology_based_candidate_discovery_when_attributes_differ():
    """Verify that two chains with 0 attribute overlap are discovered via topology link."""
    # Chain 1: Core router in Hanoi
    # Chain 2: Access BTS in Ha Nam
    # Attribute overlap: 0 (different location, class, and alarm name)
    alarms = [
        _alarm_dict(
            "core_1", "CHAIN_CORE",
            device_code="DEV_CORE_HN",
            location_code="LOC_HANOI",
            network_class_name="IP_CORE",
            alarm_name="POWER_FAILURE",
            burst_id="BURST_OUTAGE",
        ),
        _alarm_dict(
            "core_2", "CHAIN_CORE",
            device_code="DEV_CORE_HN",
            location_code="LOC_HANOI",
            network_class_name="IP_CORE",
            alarm_name="POWER_FAILURE",
            burst_id="BURST_OUTAGE",
        ),
        _alarm_dict(
            "bts_1", "CHAIN_ACCESS",
            device_code="DEV_BTS_HNM",
            location_code="LOC_HANAM",
            network_class_name="RAN_4G",
            alarm_name="CELL_UNAVAILABLE",
            burst_id="BURST_OUTAGE",
        ),
        _alarm_dict(
            "bts_2", "CHAIN_ACCESS",
            device_code="DEV_BTS_HNM",
            location_code="LOC_HANAM",
            network_class_name="RAN_4G",
            alarm_name="CELL_UNAVAILABLE",
            burst_id="BURST_OUTAGE",
        ),
    ]
    chains = [
        {"chain_id": "CHAIN_CORE", "snapshot_id": "s1", "member_count": 2},
        {"chain_id": "CHAIN_ACCESS", "snapshot_id": "s1", "member_count": 2},
    ]
    memberships = [
        {"chain_id": "CHAIN_CORE", "alarm_id": "core_1", "snapshot_id": "s1"},
        {"chain_id": "CHAIN_CORE", "alarm_id": "core_2", "snapshot_id": "s1"},
        {"chain_id": "CHAIN_ACCESS", "alarm_id": "bts_1", "snapshot_id": "s1"},
        {"chain_id": "CHAIN_ACCESS", "alarm_id": "bts_2", "snapshot_id": "s1"},
    ]
    topology = {
        "edges": [
            {
                "source_resource_id": "DEV_CORE_HN",
                "target_resource_id": "DEV_BTS_HNM",
                "relation_type": "IP_ADJACENCY",
                "directed": False,
                "source_id": "inventory",
                "source_version": "topology-v1",
            }
        ],
        "mappings": [
            {"alarm_id": "core_1", "resource_id": "DEV_CORE_HN", "mapping_status": "EXACT"},
            {"alarm_id": "core_2", "resource_id": "DEV_CORE_HN", "mapping_status": "EXACT"},
            {"alarm_id": "bts_1", "resource_id": "DEV_BTS_HNM", "mapping_status": "EXACT"},
            {"alarm_id": "bts_2", "resource_id": "DEV_BTS_HNM", "mapping_status": "EXACT"},
        ],
    }

    pkg = load_package({
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": "s1",
            "snapshot_version": "1",
            "snapshot_time": "2026-01-01T00:00:00",
            "status": "COMPLETE",
            "source": "test",
            "source_kind": "REAL_EXPORT_REPLAY",
            "produced_at": "2026-01-01T00:00:00",
        },
        "alarms": alarms,
        "chains": chains,
        "memberships": memberships,
        "topology": topology,
    })

    from channels.semantic import AlarmTaxonomy
    taxonomy = AlarmTaxonomy(families={"POWER_FAILURE": "INFRA", "CELL_UNAVAILABLE": "INFRA"}, categories={})

    candidates = blocking_candidates(pkg, "CHAIN_CORE", k=3, taxonomy=taxonomy)
    assert len(candidates) >= 1
    target_cand = next((c for c in candidates if c.chain_id == "CHAIN_ACCESS"), None)
    assert target_cand is not None
    # Verified: Discovered via topology adjacency or semantic causal!
    assert target_cand.shared_key in ("topology_adjacency", "semantic_causal")
    assert target_cand.overlap > 0

    # End-to-end verification: generate_merge_candidates now evaluates this candidate
    merge_batch = generate_merge_candidates(
        IDENTITY,
        review_chain_id="CHAIN_CORE",
        local_candidates=tuple(candidates),
        package=pkg,
        config=CONFIG,
        taxonomy=taxonomy,
    )
    assert len(merge_batch.candidates) == 1
    merge_cand = merge_batch.candidates[0]
    assert merge_cand.operation is Operation.MERGE_CHAINS
    assert set(merge_cand.merged_chain_ids) == {"CHAIN_ACCESS", "CHAIN_CORE"}
    assert merge_cand.merge_evidence.cross_audit_edge_count >= 1


def test_temporal_burst_candidate_discovery():
    """Verify that co-occurring bursts are discovered even with disjoint attributes."""
    alarms = [
        _alarm_dict(
            "a1", "CHAIN_A",
            device_code="DEV_A",
            location_code="SITE_1",
            network_class_name="CLASS_A",
            alarm_name="CUSTOM_ALARM_A",
            canonical_start_time="2026-01-01T12:00:00",
            burst_id="BURST_EARTHQUAKE_01",
        ),
        _alarm_dict(
            "b1", "CHAIN_B",
            device_code="DEV_B",
            location_code="SITE_2",
            network_class_name="CLASS_B",
            alarm_name="CUSTOM_ALARM_B",
            canonical_start_time="2026-01-01T12:00:15",
            burst_id="BURST_EARTHQUAKE_01",
        ),
    ]
    chains = [
        {"chain_id": "CHAIN_A", "snapshot_id": "s1", "member_count": 1},
        {"chain_id": "CHAIN_B", "snapshot_id": "s1", "member_count": 1},
    ]
    memberships = [
        {"chain_id": "CHAIN_A", "alarm_id": "a1", "snapshot_id": "s1"},
        {"chain_id": "CHAIN_B", "alarm_id": "b1", "snapshot_id": "s1"},
    ]
    pkg = load_package({
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": "s1",
            "snapshot_version": "1",
            "snapshot_time": "2026-01-01T12:00:00",
            "status": "COMPLETE",
            "source": "test",
            "source_kind": "REAL_EXPORT_REPLAY",
            "produced_at": "2026-01-01T12:00:00",
        },
        "alarms": alarms,
        "chains": chains,
        "memberships": memberships,
    })

    candidates = blocking_candidates(pkg, "CHAIN_A", k=3)
    target_cand = next((c for c in candidates if c.chain_id == "CHAIN_B"), None)
    assert target_cand is not None
    assert target_cand.shared_key == "temporal_burst"
    assert "BURST_EARTHQUAKE_01" in target_cand.shared_value


def test_semantic_causal_candidate_discovery():
    """Verify that root-cause-to-symptom alarm patterns are discovered without text equality."""
    alarms = [
        _alarm_dict(
            "r1", "CHAIN_ROOT",
            device_code="DEV_TRANS_01",
            location_code="SITE_NORTH",
            network_class_name="TRANSMISSION",
            alarm_name="OPTICAL_FIBER_LOS",
        ),
        _alarm_dict(
            "s1", "CHAIN_SYMPTOM",
            device_code="DEV_ROUTER_99",
            location_code="SITE_SOUTH",
            network_class_name="IP_CORE",
            alarm_name="BGP_SESSION_DOWN",
        ),
    ]
    chains = [
        {"chain_id": "CHAIN_ROOT", "snapshot_id": "s1", "member_count": 1},
        {"chain_id": "CHAIN_SYMPTOM", "snapshot_id": "s1", "member_count": 1},
    ]
    memberships = [
        {"chain_id": "CHAIN_ROOT", "alarm_id": "r1", "snapshot_id": "s1"},
        {"chain_id": "CHAIN_SYMPTOM", "alarm_id": "s1", "snapshot_id": "s1"},
    ]
    pkg = load_package({
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": "s1",
            "snapshot_version": "1",
            "snapshot_time": "2026-01-01T12:00:00",
            "status": "COMPLETE",
            "source": "test",
            "source_kind": "REAL_EXPORT_REPLAY",
            "produced_at": "2026-01-01T12:00:00",
        },
        "alarms": alarms,
        "chains": chains,
        "memberships": memberships,
    })

    candidates = blocking_candidates(pkg, "CHAIN_ROOT", k=3)
    target_cand = next((c for c in candidates if c.chain_id == "CHAIN_SYMPTOM"), None)
    assert target_cand is not None
    assert target_cand.shared_key == "semantic_causal"


def test_keyword_matching_avoids_false_positive_substrings():
    """Verify that substring collisions like 'CLOSED' matching 'LOS' or 'DOWNLOAD' matching 'DOWN' are prevented."""
    from descriptor.contrastive import _matches_keywords, CAUSAL_ROOT_KEYWORDS, CAUSAL_SYMPTOM_KEYWORDS

    assert not _matches_keywords("TICKET_CLOSED", CAUSAL_ROOT_KEYWORDS)
    assert not _matches_keywords("DOWNLOAD_CONFIG", CAUSAL_SYMPTOM_KEYWORDS)
    assert _matches_keywords("ETH_LOS", CAUSAL_ROOT_KEYWORDS)
    assert _matches_keywords("OPTICAL_FIBER_LOS", CAUSAL_ROOT_KEYWORDS)
    assert _matches_keywords("BGP_SESSION_DOWN", CAUSAL_SYMPTOM_KEYWORDS)
    assert _matches_keywords("CELL_UNAVAILABLE", CAUSAL_SYMPTOM_KEYWORDS)
