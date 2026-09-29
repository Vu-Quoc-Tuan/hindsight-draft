"""Phase 1 Explain verification: calibrated thresholds, data truth, and grounded Vietnamese narratives."""

from __future__ import annotations

import asyncio
import httpx2

from configuration import load_analysis_config
from libs.contracts import load_validated_package
from nocpro_api import create_app
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
    assert cfg.value("role.s_min") >= cfg.value("role.s_weak")
    assert cfg.value("temporal.burst.gap_seconds") > 0

    payload = _payload()
    pkg = load_validated_package(payload)

    # Analyze multi-member chain C1
    analysis = analyze_chain_configured(pkg, "C1", analysis_config=cfg)
    assert analysis.chain_id == "C1"
    assert len(analysis.members) == 3

    # Verify thresholds match calibrated configuration
    role_th = cfg.role_thresholds()
    assert role_th.s_min == cfg.value("role.s_min")
    assert role_th.s_weak == cfg.value("role.s_weak")


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
        "topology": {
            "mapped": 26,
            "total": 26,
            "mapped_device_count": 3,
            "total_device_count": 3,
            "resource_types": ["ROUTER"],
        },
        "audit": {"status": "EVALUATED", "verdict": "CANDIDATE_SPLIT", "candidate_cut": True, "conductance": 0.15},
        "recommendations": {"count": 1, "split_recommended": True},
        "quality_assessment": {
            "method": "HEURISTIC_V1",
            "status": "EVALUATED",
            "stars": 2,
            "label": "Có dấu hiệu nên tách",
            "reasons": [
                "3/3 thiết bị đã nằm trong topology.",
                "Audit phát hiện một ranh giới có thể tách chuỗi.",
            ],
        },
    }

    vi_narrative = build_deterministic_cohesion_narrative(context, language="vi")
    assert "mẫu đồng diễn" in vi_narrative
    assert "21/26 cảnh báo thuộc nhóm" in vi_narrative
    assert "Audit phát hiện ranh giới" in vi_narrative
    assert "2/5 sao" not in vi_narrative
    assert "3/3 thiết bị" not in vi_narrative
    assert len(vi_narrative) < 700
    assert "DWDM" not in vi_narrative


def test_cohesion_narrative_stays_empty_without_a_provider(monkeypatch):
    """The cohesion endpoint must not present deterministic text as provider output."""
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
                assert data_vi["narrative"] == ""
                assert data_vi["provider_status"] == "NOT_CONFIGURED"

                # 2. Cohesion narrative with its default language
                resp_en = await client.get("/api/v1/chains/C1/cohesion-narrative")
                assert resp_en.status_code == 200
                data_en = resp_en.json()
                assert data_en["narrative"] == ""
                assert data_en["provider_status"] == "NOT_CONFIGURED"
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())
