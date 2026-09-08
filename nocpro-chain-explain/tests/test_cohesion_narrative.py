"""Tests for Cohesion Narrative generator and endpoint."""

import asyncio
import httpx2
import pytest

from nocpro_api import create_app
from nocpro_api.cohesion_advisor import (
    build_deterministic_cohesion_narrative,
    extract_cohesion_context,
)
from tests.test_api import _payload


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
        "audit": {"status": "NEEDS_ATTENTION", "candidate_cut": True, "conductance": 0.12},
        "recommendations": {"split_recommended": False},
    }
    narrative_a = build_deterministic_cohesion_narrative(context_a)
    assert "6892935" in narrative_a
    assert "IP_CORE" in narrative_a
    assert "OPTICAL_POWER_RX_LOW" in narrative_a
    assert "Structural audit detected a weak separation boundary" in narrative_a
    assert "conductance 0.12" in narrative_a
    assert "DWDM" not in narrative_a
    assert "passive fiber" not in narrative_a

    # Scenario B: Single alarm singleton
    context_b = {
        "chain": {"chain_id": "6892337", "alarm_count": 1, "duration_seconds": 0, "is_singleton": True},
        "alarm_summary": {
            "top_alarm_types": [["REPT-LKF: not aligned", 1]],
            "network_classes": ["CORE"],
            "devices": ["STPV01"],
        },
        "topology": {"mapped": 0, "total": 1, "resource_types": []},
        "audit": {"status": "SOLID", "candidate_cut": False, "conductance": None},
        "recommendations": {"split_recommended": False},
    }
    narrative_b = build_deterministic_cohesion_narrative(context_b)
    assert "isolated single-alarm event" in narrative_b
    assert "REPT-LKF: not aligned" in narrative_b
    assert "STPV01" in narrative_b
    assert "no cross-device temporal propagation" in narrative_b
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
        "audit": {"status": "NEEDS_ATTENTION", "candidate_cut": True, "conductance": 0.05},
        "recommendations": {"split_recommended": True},
    }
    narrative_c = build_deterministic_cohesion_narrative(context_c)
    assert "split alternative has been recommended for review" in narrative_c


def test_api_cohesion_narrative_endpoint():
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
                assert "recommendations" in res_json["context"]
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())
