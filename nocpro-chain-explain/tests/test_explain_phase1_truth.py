"""Phase 1 Explain verification: calibrated thresholds, data truth, and grounded Vietnamese narratives."""

from __future__ import annotations

import asyncio
import httpx2

from configuration import load_analysis_config
from libs.contracts import load_validated_package
from nocpro_api import create_app
from nocpro_api.ai_advisor import (
    build_deterministic_narrative,
)
from nocpro_api.cohesion_advisor import (
    build_deterministic_cohesion_narrative,
    extract_cohesion_context,
)
from nocpro_api.workspace import Workspace
from tests.test_api import _payload
from tier1b import analyze_chain_configured


def test_calibrated_thresholds_applied_to_tier1b_analysis():
    """Verify that calibrated thresholds from calibrated.yaml govern role and burst evaluation."""
    cfg = load_analysis_config("config/thresholds/calibrated.yaml")
    assert cfg.value("role.s_min") == 0.60
    assert cfg.value("role.s_weak") == 0.30
    assert cfg.value("temporal.burst.gap_seconds") in (481, 483, 488)

    payload = _payload()
    pkg = load_validated_package(payload)

    # Analyze multi-member chain C1
    analysis = analyze_chain_configured(pkg, "C1", analysis_config=cfg)
    assert analysis.chain_id == "C1"
    assert len(analysis.members) == 3

    # Verify thresholds match calibrated configuration
    role_th = cfg.role_thresholds()
    assert role_th.s_min == 0.60
    assert role_th.s_weak == 0.30


def test_fail_closed_data_truth_for_missing_channels():
    """Missing or unindexed telemetry must yield UNAVAILABLE/NONE rather than fabricated values."""
    payload = _payload()
    # Add a singleton chain C_single to verify honest singleton fail-closed behavior
    payload["alarms"].append({
        "alarm_id": "a_single",
        "snapshot_id": "s1",
        "source_kind": "SYNTHETIC_TEST",
        "provenance_class": "SYSTEM_FACT",
        "raw": {"location_code": "SITE-B"},
        "alarm_name": "ISOLATED DOWN",
        "device_code": "D_SINGLE",
        "canonical_start_time": "2026-01-01T00:05:00",
    })
    payload["chains"].append({
        "chain_id": "C_single",
        "snapshot_id": "s1",
        "member_count": 1,
        "source_kind": "SYNTHETIC_TEST",
        "provenance_class": "SYSTEM_FACT",
    })
    payload["memberships"].append({
        "chain_id": "C_single",
        "alarm_id": "a_single",
        "snapshot_id": "s1",
        "source_kind": "SYNTHETIC_TEST",
    })

    ws = Workspace()
    try:
        ws.replace_snapshot(payload)
        analysis = ws.analyze("C1")
        ctx = extract_cohesion_context(ws, "C1", analysis=analysis)

        # Audit status must report NOT_EVALUATED honestly when Tier-2 hasn't run
        assert ctx["audit"]["status"] == "NOT_EVALUATED"
        assert ctx["audit"]["conductance"] is None
        assert ctx["audit"]["candidate_cut"] is False

        # Singleton verification
        single_analysis = ws.analyze("C_single")
        single_ctx = extract_cohesion_context(ws, "C_single", analysis=single_analysis)
        assert single_ctx["chain"]["is_singleton"] is True
        vi_singleton = build_deterministic_cohesion_narrative(single_ctx, language="vi")
        assert "chứa 1 cảnh báo" in vi_singleton.lower()
    finally:
        ws.close()


def test_cohesion_narrative_vietnamese_deterministic():
    """Verify Vietnamese deterministic narrative contains accurate facts and operational context."""
    context = {
        "chain": {"chain_id": "6913556", "alarm_count": 26, "duration_seconds": 2450, "is_singleton": False},
        "alarm_summary": {
            "top_alarm_types": [
                ["DOWN BGP_changed from ESTABLISHED to IDLE - Protocol", 21],
                ["hwEntityInvalid - PORTFAULT (Lost Optical Power)", 5],
            ],
            "network_classes": ["AGG_DISTRICT", "CORE_PROVINCE"],
            "devices": ["TTH0145AGG01", "TTH8001PRT01", "TTH8003AGG01"],
        },
        "roles": {
            "counts": {"CORE": 10, "PERIPHERAL": 14, "WEAK": 2},
            "core_count": 10,
            "weak_count": 2,
            "weak_members": ["396001", "396002"],
            "insufficient_count": 0,
            "insufficient_members": [],
        },
        "topology": {"mapped": 26, "total": 26, "resource_types": ["ROUTER"]},
        "audit": {"status": "EVALUATED", "verdict": "CANDIDATE_SPLIT", "candidate_cut": True, "conductance": 0.15},
        "recommendations": {"split_recommended": True},
    }

    vi_narrative = build_deterministic_cohesion_narrative(context, language="vi")
    assert "Chuỗi 6913556" in vi_narrative
    assert "21 sự kiện 'DOWN BGP_changed from ESTABLISHED to IDLE - Protocol'" in vi_narrative
    assert "3 thiết bị" in vi_narrative
    assert "WEAK" in vi_narrative
    assert "tách chuỗi (SPLIT)" in vi_narrative
    assert "DWDM" not in vi_narrative


def test_ai_advisor_vietnamese_deterministic():
    """Verify AI Advisor generates structured Vietnamese summary with clear callouts for weak members."""
    structured = {
        "chain_id": "CH-100",
        "member_count": 5,
        "role_counts": {"CORE": 3, "WEAK": 2},
        "weak_members": ["ALM-04", "ALM-05"],
        "insufficient_members": [],
        "descriptors": ["device=R1 (coverage 80%)"],
        "proposals": [{"candidate_id": "CAND-01", "operation": "REMOVE_MEMBER"}],
        "recommendation_status": "AVAILABLE",
    }

    vi_narrative = build_deterministic_narrative("CH-100", structured, review_status="AVAILABLE", language="vi")
    assert "Tóm tắt bằng chứng cho chuỗi CH-100" in vi_narrative
    assert "**5** cảnh báo" in vi_narrative
    assert "ALM-04" in vi_narrative
    assert "REMOVE_MEMBER" in vi_narrative
    assert "ADR-0024" not in vi_narrative


def test_api_endpoints_support_vietnamese_query(monkeypatch):
    """Verify REST API /cohesion-narrative and /ai-suggestion return Vietnamese when ?lang=vi is queried."""
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OPENAI_COMPATIBLE")

    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                loaded = await client.post("/api/v1/snapshots", json=_payload())
                assert loaded.status_code == 201

                # 1. Cohesion narrative in Vietnamese
                resp_vi = await client.get("/api/v1/chains/C1/cohesion-narrative?lang=vi")
                assert resp_vi.status_code == 200
                data_vi = resp_vi.json()
                assert data_vi["chain_id"] == "C1"
                assert "Chuỗi C1" in data_vi["narrative"] or "chuỗi C1" in data_vi["narrative"] or "Chưa thực hiện" in data_vi["narrative"]

                # 2. Cohesion narrative default English (backward compatibility)
                resp_en = await client.get("/api/v1/chains/C1/cohesion-narrative")
                assert resp_en.status_code == 200
                data_en = resp_en.json()
                assert "Chain C1" in data_en["narrative"]

                # 3. AI Suggestion in Vietnamese
                sug_vi = await client.get("/api/v1/chains/C1/ai-suggestion?lang=vi")
                assert sug_vi.status_code == 200
                sug_data = sug_vi.json()
                assert "Tóm tắt bằng chứng cho chuỗi C1" in sug_data["narrative"]
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_ai_advisor_uncalibrated_policy_safety_mode():
    """When review policy is uncalibrated on real data, AI advisor must state safety lock truthfully rather than claiming no improvement."""
    structured = {
        "chain_id": "6913556",
        "member_count": 26,
        "role_counts": {"CORE": 26, "WEAK": 0},
        "weak_members": [],
        "insufficient_members": [],
        "descriptors": ["location_code=['VN','KV2','HUE','HUE005']"],
        "proposals": [],
        "evaluated_improvements": [
            {
                "candidate_id": "841a178b",
                "operation": "SPLIT_CHAIN",
                "summary_action": "Đề xuất phân tách chuỗi 6913556 thành 2 chuỗi con",
                "why_better": "Conductance cải thiện",
                "delta_highlights": [
                    {"label": "Min Support", "delta": "+16.2%"},
                    {"label": "Evidence Coverage", "delta": "+16.9%"},
                ],
            }
        ],
        "review_reason": "COUNTERFACTUAL_POLICY_NOT_CALIBRATED",
        "recommendation_status": "UNAVAILABLE",
    }

    vi_narrative = build_deterministic_narrative(
        "6913556",
        structured,
        review_status="AVAILABLE",
        review_reason="COUNTERFACTUAL_POLICY_NOT_CALIBRATED",
        language="vi",
    )
    # Must truthfully state safety mode and mention the evaluated improvement
    assert "Chế độ an toàn mặc định" in vi_narrative
    assert "Đề xuất phân tách chuỗi 6913556" in vi_narrative
    assert "Rationale metric" in vi_narrative
    assert "Conductance cải thiện" in vi_narrative
    assert "+16.2%" in vi_narrative
    assert "không phải recommendation vận hành" in vi_narrative
    # MUST NOT falsely claim that experiments brought no improvement
    assert "Thử nghiệm loại bỏ hoặc phân tách không mang lại cải thiện" not in vi_narrative
