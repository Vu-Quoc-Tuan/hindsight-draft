"""Tests for Cohesion Narrative generator and endpoint."""

import asyncio
import json
from types import SimpleNamespace

import httpx2
from nocpro_api import create_app
from nocpro_api.catalog import load_preset_payload
from nocpro_api.cohesion_advisor import (
    build_deterministic_cohesion_narrative,
    extract_cohesion_context,
)
from nocpro_api.workspace import Workspace
from tests.test_api import _payload


def test_chain_6335571_findings_are_evidence_bounded():
    payload, _profile = load_preset_payload("real_alarm_it_demo")
    workspace = Workspace()
    try:
        workspace.replace_snapshot(payload)
        context = extract_cohesion_context(workspace, "6335571")
    finally:
        workspace.close()

    findings = {
        item["finding_id"]: item for item in context["analytical_findings"]
    }
    assert findings["ALARM_CONCENTRATION"]["status"] == "AVAILABLE"
    assert "60/71" in findings["ALARM_CONCENTRATION"]["evidence"][0]
    assert findings["TEMPORAL_PROGRESSION"]["kind"] == "DERIVED"
    assert "6m 36s" in findings["TEMPORAL_PROGRESSION"]["claim"]
    assert "CAUSAL_DIRECTION_UNVERIFIED" in findings["TEMPORAL_PROGRESSION"]["limitations"]
    assert context["topology"]["mapped"] == 71
    assert context["topology"]["resource_types"] == ["IT"]
    assert context["topology"]["connected_pair_count"] == 21
    assert context["topology"]["max_path_hops"] == 4
    assert context["topology"]["dependency_verified"] is False
    assert findings["SHARED_TOPOLOGY_CONTEXT"]["status"] == "AVAILABLE"
    assert "21/21" in findings["SHARED_TOPOLOGY_CONTEXT"]["evidence"][0]
    assert "TRANSIT_CONNECTIVITY_IS_NOT_CAUSAL_DEPENDENCY" in findings["SHARED_TOPOLOGY_CONTEXT"]["limitations"]

    briefing = build_deterministic_cohesion_narrative(context, language="vi")
    assert briefing.count("Chuỗi 6335571") == 1
    assert "Cảnh báo tập trung mạnh" not in briefing
    assert "chưa xác nhận thiết bị khởi phát là nguyên nhân gốc" in briefing

    rendered = json.dumps(context, ensure_ascii=False)
    for unsupported in (
        "Root/Trigger",
        "kích hoạt chuỗi",
        "dependent servers",
        "không có điểm đứt gãy",
    ):
        assert unsupported not in rendered


def test_audit_finding_explains_no_low_conductance_cut_in_plain_language():
    payload, _profile = load_preset_payload("real_alarm_it_demo")
    workspace = Workspace()
    audit_artifact = SimpleNamespace(
        status="AVAILABLE",
        verdict="NO_LOW_CONDUCTANCE_CUT",
        reason=(
            "best candidate (device_code=10.210.48.136) UNION "
            "(device_code=10.210.48.96): Phi=0.6163 > epsilon=0.3000"
        ),
        epsilon=0.3,
        best_cut_index=0,
        scored_cuts=(
            SimpleNamespace(
                label="(device_code=10.210.48.136) UNION (device_code=10.210.48.96)",
                phi=0.6163,
            ),
        ),
    )
    try:
        workspace.replace_snapshot(payload)
        context = extract_cohesion_context(
            workspace,
            "6335571",
            audit_artifact=audit_artifact,
        )
    finally:
        workspace.close()

    finding = next(
        item for item in context["analytical_findings"]
        if item["finding_id"] == "AUDIT_COHESION"
    )
    assert "không tìm thấy ranh giới đủ yếu" in finding["claim"]
    assert any("0.616" in item and "0.300" in item for item in finding["evidence"])
    assert "Audit Graph đo độ gắn kết evidence" in finding["evidence"][-1]


def test_deterministic_cohesion_narrative_natural_tone():
    """Verify that narrative is domain-appropriate, natural, and never stiff or hallucinated."""
    # Scenario A: IP Core chain with candidate cut
    context_a = {
        "chain": {"chain_id": "6892935", "alarm_count": 44, "duration_seconds": 31, "is_singleton": False},
        "alarm_summary": {
            "top_alarm_types": [["OPTICAL_POWER_RX_LOW", 8], ["LOSS_OF_SIGNAL", 2]],
            "network_classes": ["IP_CORE"],
            "devices": ["ROUTER-01", "ROUTER-02"],
        },
        "topology": {
            "mapped": 31,
            "total": 44,
            "resource_types": ["IP_ROUTER", "OPTICAL_PORT"],
        },
        "audit": {"status": "EVALUATED", "verdict": "CANDIDATE_SPLIT", "candidate_cut": True, "conductance": 0.12},
        "recommendations": {"split_recommended": False},
    }
    narrative_a = build_deterministic_cohesion_narrative(context_a)
    assert "6892935" in narrative_a
    assert "IP_CORE" in narrative_a
    assert "OPTICAL_POWER_RX_LOW" in narrative_a
    assert "Structural audit detected a low-conductance separation boundary" in narrative_a
    assert "conductance 0.12" in narrative_a
    assert "DWDM" not in narrative_a
    assert "passive fiber" not in narrative_a

    # Scenario B: Single alarm singleton - strictly neutral without speculative isolation claims
    context_b = {
        "chain": {"chain_id": "6892337", "alarm_count": 1, "duration_seconds": None, "is_singleton": True},
        "alarm_summary": {
            "top_alarm_types": [["REPT-LKF: not aligned", 1]],
            "network_classes": ["CORE"],
            "devices": ["STPV01"],
        },
        "topology": {"mapped": 0, "total": 1, "resource_types": []},
        "audit": {"status": "NOT_EVALUATED", "verdict": None, "candidate_cut": False, "conductance": None},
        "recommendations": {"split_recommended": False},
    }
    narrative_b = build_deterministic_cohesion_narrative(context_b)
    assert "This chain contains one observed alarm" in narrative_b
    assert "Multi-member cohesion and propagation analysis are not applicable" in narrative_b
    assert "isolated" not in narrative_b
    assert "no cross-device" not in narrative_b
    assert "DWDM" not in narrative_b

    # Scenario C: Recommended split
    context_c = {
        "chain": {"chain_id": "C-SPLIT", "alarm_count": 20, "duration_seconds": 120, "is_singleton": False},
        "alarm_summary": {
            "top_alarm_types": [["BGP_DOWN", 10], ["LINK_DOWN", 10]],
            "network_classes": ["IP_CORE"],
            "devices": ["CORE-PE1", "CORE-PE2"],
        },
        "topology": {"mapped": 20, "total": 20, "resource_types": ["ROUTER"]},
        "audit": {"status": "EVALUATED", "verdict": "CANDIDATE_SPLIT", "candidate_cut": True, "conductance": 0.05},
        "recommendations": {"split_recommended": True},
    }
    narrative_c = build_deterministic_cohesion_narrative(context_c)
    assert "split alternative has been recommended for review" in narrative_c

    # Scenario D: Evaluated with NO_LOW_CONDUCTANCE_CUT
    context_d = {
        "chain": {"chain_id": "C-SOLID", "alarm_count": 10, "duration_seconds": 15, "is_singleton": False},
        "alarm_summary": {"top_alarm_types": [["LINK_DOWN", 10]], "network_classes": ["IP_CORE"], "devices": ["PE-01"]},
        "topology": {"mapped": 10, "total": 10, "resource_types": ["ROUTER"]},
        "audit": {"status": "EVALUATED", "verdict": "NO_LOW_CONDUCTANCE_CUT", "candidate_cut": False, "conductance": None},
        "recommendations": {"split_recommended": False},
    }
    narrative_d = build_deterministic_cohesion_narrative(context_d)
    assert "Structural audit evaluated candidate partitions and detected no low-conductance partition boundaries" in narrative_d

    # Scenario E: SKIPPED_SMALL_CHAIN
    context_e = {
        "chain": {"chain_id": "C-SMALL", "alarm_count": 3, "duration_seconds": 10, "is_singleton": False},
        "alarm_summary": {"top_alarm_types": [["LINK_DOWN", 3]], "network_classes": ["IP_CORE"], "devices": ["PE-01"]},
        "topology": {"mapped": 3, "total": 3, "resource_types": ["ROUTER"]},
        "audit": {"status": "NOT_APPLICABLE", "verdict": "SKIPPED_SMALL_CHAIN", "candidate_cut": False, "conductance": None},
        "recommendations": {"split_recommended": False},
    }
    narrative_e = build_deterministic_cohesion_narrative(context_e)
    assert "Structural audit balance constraints are not applicable for this small chain structure" in narrative_e

    # Scenario F: Not Evaluated Audit (Honest data truth)
    context_f = {
        "chain": {"chain_id": "C-NO-AUDIT", "alarm_count": 10, "duration_seconds": 15, "is_singleton": False},
        "alarm_summary": {"top_alarm_types": [["LINK_DOWN", 10]], "network_classes": ["IP_CORE"], "devices": ["PE-01"]},
        "topology": {"mapped": 0, "total": 10, "resource_types": []},
        "audit": {"status": "NOT_EVALUATED", "verdict": None, "candidate_cut": False, "conductance": None},
        "recommendations": {"split_recommended": False},
    }
    narrative_f = build_deterministic_cohesion_narrative(context_f)
    assert "Tier-2 structural audit has not been performed for this chain" in narrative_f


def test_api_cohesion_narrative_endpoint(monkeypatch):
    """Verify endpoint runs in offline isolation and accurately reports un-evaluated audit."""
    # Ensure provider doesn't hit external network by clearing API keys and forcing deterministic rendering
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OPENAI_COMPATIBLE")

    from nocpro_api import grounded_llm

    def fake_render_grounded(draft: str, facts: dict, fact_refs: list, purpose: str = "ADVISOR"):
        return grounded_llm.GroundedRenderResult(
            message=draft,
            model="DETERMINISTIC_EVIDENCE",
            provider_status="DISABLED",
        )

    # Patch the exact import target inside cohesion_advisor
    monkeypatch.setattr("nocpro_api.cohesion_advisor.render_grounded", fake_render_grounded)

    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                loaded = await client.post("/api/v1/snapshots", json=_payload())
                assert loaded.status_code == 201

                narrative_resp = await client.get("/api/v1/chains/C1/cohesion-narrative")
                assert narrative_resp.status_code == 200
                res_json = narrative_resp.json()
                assert res_json["chain_id"] == "C1"
                assert len(res_json["narrative"]) > 10
                assert "context" in res_json
                assert "alarm_summary" in res_json["context"]
                assert "why" in res_json["context"]
                assert "topology" in res_json["context"]
                assert "audit" in res_json["context"]
                # Must be NOT_EVALUATED since Tier-2 Deep Dive hasn't run
                assert res_json["context"]["audit"]["status"] == "NOT_EVALUATED"
                assert "Tier-2 structural audit has not been performed" in res_json["narrative"]
                assert "recommendations" in res_json["context"]
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_cohesion_narrative_rich_p2_and_operational_insights():
    """Verify that P2 deep dive facts enrich context, findings, and generate actionable operational insights."""
    payload, _profile = load_preset_payload("real_alarm_it_demo")
    workspace = Workspace()
    try:
        workspace.replace_snapshot(payload)
        deep_dive_analysis = SimpleNamespace(
            topology_hypotheses=SimpleNamespace(
                dominator=SimpleNamespace(
                    status=SimpleNamespace(value="AVAILABLE"),
                    witness_resource_id="10.210.48.136",
                    covered_resource_ids=("10.210.48.136", "10.210.48.96"),
                    semantic="DOMINATOR",
                    relation_type="TRANSIT",
                ),
                propagation=SimpleNamespace(
                    status=SimpleNamespace(value="AVAILABLE"),
                    candidate_node_count=2,
                    candidate_edge_count=1,
                    node_scores=(SimpleNamespace(alarm_id="ALM-1", score=0.75),),
                    hypotheses=(
                        SimpleNamespace(
                            source_alarm_id="6335571",
                            target_alarm_id="6335572",
                            score=0.88,
                            transition_probability=0.85,
                            temporal_delta_seconds=12.5,
                        ),
                    ),
                ),
                dependency_scope=None,
            ),
            evidence_attribution=SimpleNamespace(
                status=SimpleNamespace(value="AVAILABLE"),
                total_coverage=0.92,
                contributions=(
                    SimpleNamespace(
                        group_id="TEMPORAL_BURST",
                        derivation_tag="BURST",
                        attribution=0.65,
                        supported_pair_count=18,
                    ),
                    SimpleNamespace(
                        group_id="TOPOLOGY_TRANSIT",
                        derivation_tag="TRANSIT",
                        attribution=0.27,
                        supported_pair_count=8,
                    ),
                ),
            ),
            over_merge=SimpleNamespace(
                structural_separation=False,
                cross_evidence_agreement=False,
                strength=SimpleNamespace(value="NONE"),
                narrative="Chuỗi có tính gắn kết bằng chứng cao",
                driving_evidence=(),
            ),
            structural_roles={},
        )
        audit_artifact = SimpleNamespace(
            status="AVAILABLE",
            verdict="NO_LOW_CONDUCTANCE_CUT",
            reason="Phi=0.6163 > epsilon=0.3000",
            epsilon=0.3,
            best_cut_index=0,
            scored_cuts=(
                SimpleNamespace(
                    label="Part A vs Part B",
                    phi=0.6163,
                ),
            ),
        )

        context = extract_cohesion_context(
            workspace,
            "6335571",
            audit_artifact=audit_artifact,
            deep_dive_analysis=deep_dive_analysis,
        )

        # 1. Verify P2 enriched facts
        assert "tier2_p2" in context
        p2 = context["tier2_p2"]
        assert p2["dominator"]["witness_resource_id"] == "10.210.48.136"
        assert len(p2["dominator"]["covered_resource_ids"]) == 2
        assert p2["propagation"]["hypotheses"][0]["prob"] == 0.85
        assert len(p2["evidence_attribution"]["contributions"]) == 2

        # 2. Verify Operational Insights
        assert "operational_insights" in context
        op = context["operational_insights"]
        assert op["primary_focus"] is not None
        assert op["cohesion_verdict"] == "STRONG"
        assert op["actionable_takeaway"] is not None
        assert "tập trung xử lý tại thiết bị khởi phát" in op["actionable_takeaway"]

        # 3. Verify Analytical Findings include Dominator & Propagation
        findings = {item["finding_id"]: item for item in context["analytical_findings"]}
        assert "TOPOLOGY_DOMINATOR_WITNESS" in findings
        assert "10.210.48.136" in findings["TOPOLOGY_DOMINATOR_WITNESS"]["claim"]
        assert "TOPOLOGY_PROPAGATION_FLOW" in findings
        assert findings["TOPOLOGY_PROPAGATION_FLOW"]["status"] == "AVAILABLE"

        # 4. Verify Comprehensive 4-pillar Deterministic Narrative
        briefing = build_deterministic_cohesion_narrative(context, language="vi")
        assert "Chuỗi 6335571" in briefing
        assert "10.210.48.136" in briefing
        assert "Audit Graph không tìm thấy ranh giới đủ yếu" in briefing
        assert "khuyến nghị kỹ sư NOC" in briefing
    finally:
        workspace.close()

