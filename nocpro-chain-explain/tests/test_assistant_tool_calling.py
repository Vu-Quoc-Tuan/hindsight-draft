"""Tests for NocPro Assistant native LLM tool calling."""

from __future__ import annotations

import asyncio
from typing import Any
import httpx2
import pytest

from nocpro_api.app import create_app
from nocpro_api.assistant import dispatch_assistant_tool
from nocpro_api.grounded_llm import GroundedAssistantCallResult, LLMToolCall
from tests.test_api import _payload


def test_tool_dispatch_explain_metric() -> None:
    app = create_app()
    try:
        async def run() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/v1/snapshots", json=_payload())
                assert res.status_code == 201

        asyncio.run(run())

        ws = app.state.workspace
        context = {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"}

        result = dispatch_assistant_tool(
            ws, "explain_metric", {"metric_name": "conductance"}, context
        )
        assert result["status"] == "AVAILABLE"
        assert "Audit conductance" in result["message"]
        assert "semantic-registry:conductance" in result["fact_refs"]
        assert result["actions"] == []
    finally:
        app.state.workspace.close()


def test_tool_dispatch_navigate_workspace() -> None:
    app = create_app()
    try:
        async def run() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/v1/snapshots", json=_payload())
                assert res.status_code == 201

        asyncio.run(run())
        ws = app.state.workspace
        context = {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"}

        # Navigate to structure (Audit)
        result = dispatch_assistant_tool(
            ws, "navigate_workspace", {"tab": "structure", "chain_id": "C1"}, context
        )
        assert result["status"] == "AVAILABLE"
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["kind"] == "NAVIGATE"
        assert action["label"] == "Open Structural Audit"
        assert action["target"]["tab"] == "structure"
        assert action["target"]["chain_id"] == "C1"
        assert action["target"]["snapshot_id"] == "s1"
        assert action["target"]["snapshot_version"] == "1"

        # Navigate to Pair WHY with pair
        why_result = dispatch_assistant_tool(
            ws,
            "navigate_workspace",
            {"tab": "why", "chain_id": "C1", "pair_alarm_id_a": "a1", "pair_alarm_id_b": "a2"},
            context,
        )
        assert why_result["status"] == "AVAILABLE"
        why_action = why_result["actions"][0]
        assert why_action["label"] == "Open Pair WHY"
        assert why_action["target"]["pair_alarm_id_a"] == "a1"
        assert why_action["target"]["pair_alarm_id_b"] == "a2"
    finally:
        app.state.workspace.close()


def test_tool_dispatch_search_chains() -> None:
    app = create_app()
    try:
        async def run() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/v1/snapshots", json=_payload())
                assert res.status_code == 201

        asyncio.run(run())
        ws = app.state.workspace
        context = {"snapshot_id": "s1", "snapshot_version": "1"}

        result = dispatch_assistant_tool(ws, "search_chains", {"query": "C1"}, context)
        assert result["status"] == "AVAILABLE"
        assert len(result["actions"]) == 1
        assert result["actions"][0]["target"]["chain_id"] == "C1"

        # Non-matching search
        empty_result = dispatch_assistant_tool(ws, "search_chains", {"query": "NON_EXISTENT"}, context)
        assert empty_result["status"] == "NO_FINDING"
        assert empty_result["actions"] == []
    finally:
        app.state.workspace.close()


def test_llm_tool_calling_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://api.test/v1")
    monkeypatch.setenv("AI_MODEL", "mock-model")

    app = create_app()
    try:
        async def run() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/v1/snapshots", json=_payload())
                assert res.status_code == 201

                # Test 1: LLM selects explain_metric
                def fake_llm_explain(**kwargs: Any) -> GroundedAssistantCallResult:
                    return GroundedAssistantCallResult(
                        content="Giải thích về conductance",
                        tool_calls=[LLMToolCall(name="explain_metric", arguments={"metric_name": "conductance"})],
                        model="mock-model",
                        provider_status="OK",
                        used_provider=True,
                    )

                monkeypatch.setattr("nocpro_api.assistant.call_grounded_assistant", fake_llm_explain)

                resp = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "Conductance là cái gì thế?",
                        "context": {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"},
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "AVAILABLE"
                assert "Audit conductance" in data["message"]
                assert data["model"] == "mock-model"
                assert data["provider_status"] == "OK"

                # Test 2: LLM selects navigate_workspace
                def fake_llm_navigate(**kwargs: Any) -> GroundedAssistantCallResult:
                    return GroundedAssistantCallResult(
                        content=None,
                        tool_calls=[LLMToolCall(name="navigate_workspace", arguments={"tab": "structure", "chain_id": "C1"})],
                        model="mock-model",
                        provider_status="OK",
                        used_provider=True,
                    )

                monkeypatch.setattr("nocpro_api.assistant.call_grounded_assistant", fake_llm_navigate)

                resp = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "mở tab audit chuỗi C1",
                        "context": {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"},
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "AVAILABLE"
                assert len(data["actions"]) == 1
                assert data["actions"][0]["target"]["tab"] == "structure"
                assert data["actions"][0]["target"]["chain_id"] == "C1"

                # Test 3: LLM direct conversational answer without tool
                def fake_llm_chat(**kwargs: Any) -> GroundedAssistantCallResult:
                    return GroundedAssistantCallResult(
                        content="Hệ thống đang hoạt động bình thường, chuỗi C1 có 3 cảnh báo.",
                        tool_calls=[],
                        model="mock-model",
                        provider_status="OK",
                        used_provider=True,
                    )

                monkeypatch.setattr("nocpro_api.assistant.call_grounded_assistant", fake_llm_chat)

                resp = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "tình hình thế nào?",
                        "context": {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"},
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "AVAILABLE"
                assert data["message"] == "Hệ thống đang hoạt động bình thường, chuỗi C1 có 3 cảnh báo."
                assert data["actions"] == []

        asyncio.run(run())
    finally:
        app.state.workspace.close()


def test_tool_dispatch_inspect_chart() -> None:
    app = create_app()
    try:
        async def run() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/v1/snapshots", json=_payload())
                assert res.status_code == 201

        asyncio.run(run())
        ws = app.state.workspace
        context = {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"}

        # 1. Inspect deletion curve
        res_del = dispatch_assistant_tool(
            ws, "inspect_chart", {"chart_type": "attribution_deletion_curve"}, context
        )
        assert res_del["status"] == "AVAILABLE"
        chart_data = res_del["chart_data"]
        assert chart_data["chart_type"] == "attribution_deletion_curve"
        assert chart_data["primary_auc"] is not None
        assert chart_data["random_mean_auc"] is not None
        assert isinstance(chart_data["primary_curve"], list)
        assert len(chart_data["primary_curve"]) > 0
        assert len(res_del["actions"]) == 1
        assert res_del["actions"][0]["target"]["tab"] == "structure"
        assert "chain:C1" in res_del["fact_refs"]

        # 2. Inspect conductance cut
        res_cut = dispatch_assistant_tool(
            ws, "inspect_chart", {"chart_type": "conductance_cut"}, context
        )
        assert res_cut["status"] == "AVAILABLE"
        cut_data = res_cut["chart_data"]
        assert cut_data["chart_type"] == "conductance_cut"
        assert cut_data["verdict"] == "SKIPPED_SMALL_CHAIN"
        assert len(res_cut["actions"]) == 1

        # 3. Invalid chain
        res_invalid = dispatch_assistant_tool(
            ws, "inspect_chart", {"chart_type": "conductance_cut", "chain_id": "NON_EXISTENT"}, context
        )
        assert res_invalid["status"] == "UNAVAILABLE"
        assert "capability:CHAIN_CONTEXT_UNAVAILABLE" in res_invalid["fact_refs"]
    finally:
        app.state.workspace.close()


def test_llm_tool_calling_inspect_chart_multi_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://api.test/v1")
    monkeypatch.setenv("AI_MODEL", "mock-model")

    app = create_app()
    try:
        async def run() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/v1/snapshots", json=_payload())
                assert res.status_code == 201

                calls_count = 0

                def mock_call_assistant(messages: list[dict[str, Any]], tools: Any = None, **kwargs: Any) -> GroundedAssistantCallResult:
                    nonlocal calls_count
                    calls_count += 1
                    if tools is not None:
                        # Turn 1: LLM decides to call inspect_chart
                        return GroundedAssistantCallResult(
                            content=None,
                            tool_calls=[
                                LLMToolCall(
                                    name="inspect_chart",
                                    arguments={"chain_id": "C1", "chart_type": "attribution_deletion_curve"},
                                    id="call_mock_1",
                                )
                            ],
                            model="mock-model",
                            provider_status="OK",
                            used_provider=True,
                        )
                    else:
                        # Turn 2: LLM receives tool response and explains the chart
                        last_msg = messages[-1]
                        assert last_msg["role"] == "tool"
                        assert "primary_auc" in last_msg["content"]
                        return GroundedAssistantCallResult(
                            content="Đường Primary AUC = 0.45 giảm mạnh tại bước 5 do loại bỏ temporal_burst.",
                            tool_calls=[],
                            model="mock-model",
                            provider_status="OK",
                            used_provider=True,
                        )

                monkeypatch.setattr("nocpro_api.assistant.call_grounded_assistant", mock_call_assistant)

                resp = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "giải thích đường vẽ biểu đồ Deletion curve",
                        "context": {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"},
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "AVAILABLE"
                assert "Đường Primary AUC = 0.45" in data["message"]
                assert data["model"] == "mock-model"
                assert data["provider_status"] == "OK"
                assert len(data["actions"]) == 1
                assert data["actions"][0]["target"]["tab"] == "structure"
                assert calls_count == 2

        asyncio.run(run())
    finally:
        app.state.workspace.close()


def test_fallback_chart_route() -> None:
    app = create_app()
    try:
        async def run() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/v1/snapshots", json=_payload())
                assert res.status_code == 201

        asyncio.run(run())
        ws = app.state.workspace
        context = {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"}

        from nocpro_api.assistant import _fallback_route

        result = _fallback_route(ws, "giải thích biểu đồ deletion curve chuỗi này", context)
        assert result["status"] == "AVAILABLE"
        assert "Số liệu biểu đồ Deletion Curve" in result["message"]
        assert result["chart_data"]["chart_type"] == "attribution_deletion_curve"
        assert len(result["actions"]) == 1
    finally:
        app.state.workspace.close()

