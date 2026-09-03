"""Tests for AI Operational Advisor conforming to ADR-0024."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import httpx2
import pytest

from nocpro_api import create_app
from nocpro_api.ai_advisor import (
    extract_grounded_claims,
    build_deterministic_narrative,
    generate_ai_suggestion,
)
from tests.test_api import _payload


def test_ai_advisor_extracts_pure_grounded_claims() -> None:
    # Build a mock analysis object
    mock_member_1 = {"alarm_id": "A1", "device_code": "R1", "role": "ROOT", "fit": "NORMAL"}
    mock_member_2 = {"alarm_id": "A2", "device_code": "R2", "role": "LEAF", "fit": "WEAK"}
    mock_desc = {"label": "Power Supply Fluctuation", "coverage": 0.85, "precision_global": 0.9}

    analysis = MagicMock()
    analysis.members = [mock_member_1, mock_member_2]
    analysis.descriptors = [mock_desc]
    analysis.role_counts = {"ROOT": 1, "LEAF": 1}

    structured, claims = extract_grounded_claims("C100", analysis)
    assert structured["chain_id"] == "C100"
    assert structured["member_count"] == 2
    assert "A2 (R2)" in structured["weak_members"]
    assert "A1 (R1)" in structured["root_members"]
    assert any("2 cảnh báo" in c for c in claims)
    assert any("tương quan yếu" in c for c in claims)


def test_ai_advisor_fallback_builds_rich_deterministic_narrative() -> None:
    mock_member = {"alarm_id": "A1", "device_code": "CORE-HNI", "role": "ROOT", "fit": "NORMAL"}
    analysis = MagicMock()
    analysis.members = [mock_member]
    analysis.descriptors = []
    analysis.role_counts = {"ROOT": 1}

    # Generate without LLM
    with patch.dict("os.environ", {"AI_API_KEY": ""}):
        res = generate_ai_suggestion("C1", analysis)
        assert res.status == "FALLBACK"
        assert "CORE-HNI" in res.narrative
        assert "ADR-0024" in res.disclaimer
        assert len(res.grounded_claims) > 0


def test_ai_advisor_handles_llm_provider_restriction_gracefully() -> None:
    mock_member = {"alarm_id": "A1", "device_code": "CORE-HNI", "role": "ROOT", "fit": "NORMAL"}
    analysis = MagicMock()
    analysis.members = [mock_member]
    analysis.descriptors = []
    analysis.role_counts = {"ROOT": 1}

    http_error = MagicMock()
    http_error.code = 403
    http_error.reason = "Forbidden"
    http_error.read.return_value = b'{"error":{"type":"forbidden","message":"telegram_required"}}'

    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        url="https://router.bynara.id/v1/chat/completions",
        code=403,
        msg="Forbidden",
        hdrs={},
        fp=http_error,
    )), patch.dict("os.environ", {"AI_API_KEY": "sk-test-key"}):
        res = generate_ai_suggestion("C1", analysis)
        assert res.status == "FALLBACK"
        assert "telegram_required" in (res.provider_status or "")
        # Invariant: narrative must still be provided via grounded fallback
        assert "Tóm tắt chuỗi sự cố" in res.narrative


def test_ai_advisor_successful_llm_call() -> None:
    mock_member = {"alarm_id": "A1", "device_code": "CORE-HNI", "role": "ROOT", "fit": "NORMAL"}
    analysis = MagicMock()
    analysis.members = [mock_member]
    analysis.descriptors = []
    analysis.role_counts = {"ROOT": 1}

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "### 📋 Tóm tắt trạng thái chuỗi sự cố\nChuỗi C1 được phân tích bởi Mistral-Large."
            }
        }]
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), patch.dict(
        "os.environ", {"AI_API_KEY": "sk-test-key", "AI_MODEL": "mistral-large"}
    ):
        res = generate_ai_suggestion("C1", analysis)
        assert res.status == "AVAILABLE"
        assert res.model == "mistral-large"
        assert "Mistral-Large" in res.narrative


def test_ai_suggestion_api_endpoint() -> None:
    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                loaded = await client.post("/api/v1/snapshots", json=_payload())
                assert loaded.status_code == 201

                resp = await client.get("/api/v1/chains/C1/ai-suggestion")
                assert resp.status_code == 200
                data = resp.json()
                assert data["chain_id"] == "C1"
                assert data["status"] in {"AVAILABLE", "FALLBACK"}
                assert "ADR-0024" in data["disclaimer"]
                assert len(data["narrative"]) > 0
                assert len(data["grounded_claims"]) > 0
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())
