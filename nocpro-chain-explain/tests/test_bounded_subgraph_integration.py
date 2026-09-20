"""Integration test verifying bounded topology subgraph and chain 6913556 structural cohesion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from configuration import load_analysis_config
from libs.contracts import load_validated_package
from nocpro_api.cohesion_advisor import build_deterministic_cohesion_narrative, extract_cohesion_context
from nocpro_api.workspace import Workspace
from tier2.audit_analysis import AuditExecutionPolicy, analyze_structural_audit
from tier2.jobs import Tier2JobManager


def test_real_alarm_ip_demo_contains_complete_hue_topology():
    """Verify that real_alarm_ip_demo.json contains all 1-hop relations without arbitrary truncation."""
    preset_path = Path("config/presets/real_alarm_ip_demo.json")
    assert preset_path.is_file()

    with preset_path.open(encoding="utf-8") as f:
        data = json.load(f)

    edges = data.get("topology", {}).get("edges", [])
    nodes = data.get("topology", {}).get("nodes", [])

    # Must contain the full 1-hop relations for all 141 alarm devices (not truncated to 500)
    assert len(edges) >= 3900
    assert len(nodes) >= 2000

    # Verify Hue devices are present
    node_ids = {n["resource_id"] for n in nodes}
    assert "TTH8001PRT01" in node_ids
    assert "TTH0145AGG01" in node_ids
    assert "TTH8003AGG01" in node_ids

    # Verify 2-hop path edges exist: PRT01 <-> AGG01 and AGG01 <-> AGG03
    edge_pairs = {
        (e["source_resource_id"], e["target_resource_id"]) for e in edges
    } | {
        (e["target_resource_id"], e["source_resource_id"]) for e in edges
    }

    assert ("TTH8001PRT01", "TTH0145AGG01") in edge_pairs
    assert ("TTH0145AGG01", "TTH8003AGG01") in edge_pairs


def test_chain_6913556_structural_audit_no_split():
    """Verify that chain 6913556 does NOT yield a false LOW_CONDUCTANCE_CUT or propose SPLIT_CHAIN."""
    preset_path = Path("config/presets/real_alarm_ip_demo.json")
    with preset_path.open(encoding="utf-8") as f:
        data = json.load(f)

    pkg = load_validated_package(data)
    analysis_config = load_analysis_config("config/thresholds/calibrated.yaml")

    tier2 = analyze_structural_audit(
        pkg,
        "6913556",
        policy=AuditExecutionPolicy(
            exact_max_members=int(analysis_config.value("audit.exact_max_members"))
        ),
        mining_config=analysis_config.mining_config(),
        epsilon=float(analysis_config.value("audit.global_weak_baseline")),
        rho=float(analysis_config.value("audit.rho")),
        min_side_size=int(analysis_config.value("audit.min_side_size")),
        small_chain_threshold=int(analysis_config.value("audit.small_chain_threshold")),
        delay_threshold=float(analysis_config.value("temporal.delay.support_threshold")),
        d_max=int(analysis_config.value("dependency.max_hop")),
        lambda_dep=float(analysis_config.value("dependency.lambda_dep")),
        common_dependency_threshold=float(analysis_config.value("dependency.common_support_threshold")),
        silent_gap_seconds=int(analysis_config.value("temporal.burst.gap_seconds")),
    )

    audit = tier2.structural_audit
    assert audit.verdict.value == "NO_LOW_CONDUCTANCE_CUT"
    assert "Phi=" in audit.reason
    assert "epsilon=0.3" in audit.reason

    # Verify Cohesion Narrative and Advisor Context
    ws = Workspace()
    try:
        ws.replace_snapshot(data)
        analysis = ws.analyze("6913556")
        artifact = Tier2JobManager._build_artifact(pkg, "6913556", tier2, analysis_config)
        ctx = extract_cohesion_context(ws, "6913556", analysis=analysis, audit_artifact=artifact)

        assert ctx["audit"]["status"] == "EVALUATED"
        assert ctx["audit"]["verdict"] == "NO_LOW_CONDUCTANCE_CUT"
        assert ctx["recommendations"]["split_recommended"] is False

        narrative = build_deterministic_cohesion_narrative(ctx, language="vi")
        assert "không có vết cắt độ dẫn thấp trên đồ thị" in narrative
    finally:
        ws.close()
