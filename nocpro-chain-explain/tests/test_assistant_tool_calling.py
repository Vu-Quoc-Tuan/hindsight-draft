"""Tests for NocPro Assistant native LLM tool calling."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
import httpx2
import pytest

from nocpro_api.app import create_app
from nocpro_api.assistant import ASSISTANT_TOOLS, dispatch_assistant_tool
from nocpro_api.grounded_llm import GroundedAssistantCallResult, LLMToolCall
from tests.test_api import _payload


def _run_deep_dive_explicitly(workspace: Any, chain_id: str = "C1") -> None:
    submission = workspace.submit_deep_dive(chain_id)
    completed = workspace.jobs.wait(submission.job_id, timeout=5)
    assert completed.status.value == "SUCCEEDED"


def test_public_tool_registry_exposes_six_upgraded_read_only_tools() -> None:
    names = [tool["function"]["name"] for tool in ASSISTANT_TOOLS]
    assert names == [
        "search_project_knowledge",
        "navigate_workspace",
        "search_chains",
        "explain_capability_boundary",
        "inspect_mapping_capability",
        "inspect_current_view",
    ]


def test_current_view_combines_validated_chain_and_metric_knowledge() -> None:
    app = create_app()
    try:
        async def seed() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                assert (await client.post("/api/v1/snapshots", json=_payload())).status_code == 201

        asyncio.run(seed())
        result = asyncio.run(dispatch_assistant_tool(
            app.state.workspace,
            "inspect_current_view",
            {"view": "chain", "selected_metric": "membership_support"},
            {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"},
        ))
        assert result["status"] == "AVAILABLE"
        assert result["data"]["chain_id"] == "C1"
        assert result["data"]["selected_metric"] == "membership_support"
        assert result["data"]["knowledge"][0]["id"] == "metric.membership_support"
    finally:
        app.state.workspace.close()


def test_provider_failure_after_tool_preserves_verified_tool_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://api.test/v1")
    monkeypatch.setenv("AI_MODEL", "mock-model")
    calls = 0

    def provider(**_kwargs: Any) -> GroundedAssistantCallResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return GroundedAssistantCallResult(
                content=None,
                tool_calls=[LLMToolCall("search_project_knowledge", {"query": "conductance"}, "call-1")],
                model="mock-model", provider_status="OK", used_provider=True,
            )
        return GroundedAssistantCallResult(
            content=None, tool_calls=[], model="mock-model",
            provider_status="TIMEOUT", used_provider=False,
        )

    monkeypatch.setattr("nocpro_api.assistant.call_grounded_assistant", provider)
    app = create_app()
    try:
        async def exercise() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                await client.post("/api/v1/snapshots", json=_payload())
                response = await client.post("/api/v1/assistant/query", json={
                    "query": "Giải thích metric đang nói tới",
                    "context": {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"},
                })
                body = response.json()
                assert response.status_code == 200
                assert body["response_mode"] == "PROVIDER_UNAVAILABLE"
                assert body["provider_status"] == "TIMEOUT"
                assert body["tools_used"] == ["search_project_knowledge"]
                assert body["message"] == ""

        asyncio.run(exercise())
    finally:
        app.state.workspace.close()


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

        result = asyncio.run(dispatch_assistant_tool(
            ws, "explain_metric", {"metric_name": "conductance"}, context
        ))
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
        result = asyncio.run(dispatch_assistant_tool(
            ws, "navigate_workspace", {"tab": "structure", "chain_id": "C1"}, context
        ))
        assert result["status"] == "AVAILABLE"
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["kind"] == "NAVIGATE"
        assert action["label"] == "Open Structural Audit"
        assert action["target"]["tab"] == "structure"
        assert action["target"]["chain_id"] == "C1"
        assert action["target"]["snapshot_id"] == "s1"
        assert action["target"]["snapshot_version"] == "1"

        legacy_audit_result = asyncio.run(dispatch_assistant_tool(
            ws, "navigate_workspace", {"tab": "audit", "chain_id": "C1"}, context
        ))
        assert legacy_audit_result["status"] == "AVAILABLE"
        assert legacy_audit_result["actions"][0]["target"]["tab"] == "structure"

        # Navigate to Pair WHY with pair
        why_result = asyncio.run(dispatch_assistant_tool(
            ws,
            "navigate_workspace",
            {"tab": "why", "chain_id": "C1", "pair_alarm_id_a": "a1", "pair_alarm_id_b": "a2"},
            context,
        ))
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

        result = asyncio.run(dispatch_assistant_tool(ws, "search_chains", {"query": "C1"}, context))
        assert result["status"] == "AVAILABLE"
        assert len(result["actions"]) == 1
        assert result["actions"][0]["target"]["chain_id"] == "C1"

        # Non-matching search
        empty_result = asyncio.run(dispatch_assistant_tool(ws, "search_chains", {"query": "NON_EXISTENT"}, context))
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
                    system_prompt = kwargs["messages"][0]["content"]
                    assert "must call a read-only tool before making factual claims" in system_prompt
                    assert "Do not invent or infer chain-specific facts" in system_prompt
                    if kwargs["messages"][-1]["role"] == "tool":
                        return GroundedAssistantCallResult(
                            content="Độ dẫn thấp gợi ý một ranh giới kết nối yếu để review; nó không tự kết luận over-merge.",
                            tool_calls=[], model="mock-model", provider_status="OK", used_provider=True,
                        )
                    return GroundedAssistantCallResult(
                        content="Nội dung chưa grounded ở lượt chọn tool phải bị bỏ.",
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
                assert "Độ dẫn thấp" in data["message"]
                assert "Nội dung chưa grounded" not in data["message"]
                assert data["model"] == "mock-model"
                assert data["provider_status"] == "OK"
                assert data["response_mode"] == "LLM_PRIMARY"
                assert data["tools_used"] == ["search_project_knowledge"]

                # Test 2: LLM selects navigate_workspace
                def fake_llm_navigate(**kwargs: Any) -> GroundedAssistantCallResult:
                    if kwargs["messages"][-1]["role"] == "tool":
                        return GroundedAssistantCallResult(
                            content="Mình đã chuẩn bị điều hướng tới Structural Audit.",
                            tool_calls=[], model="mock-model", provider_status="OK", used_provider=True,
                        )
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
                        content="Có, tôi có thể trả lời bằng tiếng Việt.",
                        tool_calls=[],
                        model="mock-model",
                        provider_status="OK",
                        used_provider=True,
                    )

                monkeypatch.setattr("nocpro_api.assistant.call_grounded_assistant", fake_llm_chat)

                resp = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "bạn có thể trả lời bằng tiếng Việt không?",
                        "context": {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"},
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "AVAILABLE"
                assert data["message"] == "Có, tôi có thể trả lời bằng tiếng Việt."
                assert data["actions"] == []
                assert data["response_mode"] == "LLM_PRIMARY"

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

        submit_calls = 0
        original_submit = ws.submit_deep_dive

        def tracked_submit(chain_id: str) -> Any:
            nonlocal submit_calls
            submit_calls += 1
            return original_submit(chain_id)

        ws.submit_deep_dive = tracked_submit
        unavailable = asyncio.run(dispatch_assistant_tool(
            ws, "inspect_chart", {"chart_type": "attribution_deletion_curve"}, context
        ))
        assert unavailable["status"] == "UNAVAILABLE"
        assert submit_calls == 0

        # The operator starts Tier 2 explicitly; Assistant only reads the completed result.
        _run_deep_dive_explicitly(ws)
        assert submit_calls == 1

        # 1. Inspect deletion curve
        res_del = asyncio.run(dispatch_assistant_tool(
            ws, "inspect_chart", {"chart_type": "attribution_deletion_curve"}, context
        ))
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
        res_cut = asyncio.run(dispatch_assistant_tool(
            ws, "inspect_chart", {"chart_type": "conductance_cut"}, context
        ))
        assert res_cut["status"] == "AVAILABLE"
        cut_data = res_cut["chart_data"]
        assert cut_data["chart_type"] == "conductance_cut"
        assert cut_data["verdict"] == "SKIPPED_SMALL_CHAIN"
        assert len(res_cut["actions"]) == 1

        # 3. Invalid chain
        res_invalid = asyncio.run(dispatch_assistant_tool(
            ws, "inspect_chart", {"chart_type": "conductance_cut", "chain_id": "NON_EXISTENT"}, context
        ))
        assert res_invalid["status"] == "UNAVAILABLE"
        assert "capability:CHAIN_CONTEXT_UNAVAILABLE" in res_invalid["fact_refs"]
    finally:
        app.state.workspace.close()


def test_inspect_evolution_reads_verified_artifact_and_rejects_single_snapshot() -> None:
    app = create_app()
    try:
        async def seed() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/v1/snapshots", json=_payload())
                assert res.status_code == 201

        asyncio.run(seed())
        ws = app.state.workspace
        context = {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"}

        unavailable = asyncio.run(dispatch_assistant_tool(
            ws,
            "inspect_chart",
            {"chart_type": "evolution_lineage", "chain_id": "C1"},
            context,
        ))
        assert unavailable["status"] == "UNAVAILABLE"
        assert unavailable["fact_refs"] == [
            "capability:SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE"
        ]

        async def verified_evolution(_chain_id: str) -> Any:
            return SimpleNamespace(
                status="AVAILABLE",
                reason=None,
                source_kind="SYNTHETIC_TEST",
                sequence_status="VERIFIED",
                production_validation="NOT_ESTABLISHED",
                lineage_component_id="lc-synthetic",
                branch_id="branch-1",
                snapshot_id="s1",
                snapshot_version="1",
                chain_id="C1",
                nodes=(
                    SimpleNamespace(
                        snapshot_id="s0",
                        snapshot_version="1",
                        chain_id="C0",
                        snapshot_time=__import__("datetime").datetime.fromisoformat(
                            "2026-01-01T00:00:00+00:00"
                        ),
                        lineage_component_id="lc-synthetic",
                        branch_id="branch-1",
                        source_kind="SYNTHETIC_TEST",
                    ),
                ),
                edges=(),
            )

        ws.evolution = verified_evolution
        available = asyncio.run(dispatch_assistant_tool(
            ws,
            "inspect_chart",
            {"chart_type": "evolution_lineage", "chain_id": "C1"},
            context,
        ))
        assert available["status"] == "AVAILABLE"
        assert available["chart_data"]["source_kind"] == "SYNTHETIC_TEST"
        assert available["chart_data"]["sequence_status"] == "VERIFIED"
        assert available["chart_data"]["production_validation"] == "NOT_ESTABLISHED"
        assert available["chart_data"]["nodes"][0]["chain_id"] == "C0"
    finally:
        app.state.workspace.close()


def test_inspect_counterfactual_has_own_read_only_handler() -> None:
    app = create_app()
    try:
        async def seed() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/v1/snapshots", json=_payload())
                assert res.status_code == 201

        asyncio.run(seed())
        ws = app.state.workspace
        context = {"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"}

        async def no_review(_chain_id: str) -> None:
            return None

        ws.latest_review = no_review
        unavailable = asyncio.run(dispatch_assistant_tool(
            ws,
            "inspect_chart",
            {"chart_type": "counterfactual_review", "chain_id": "C1"},
            context,
        ))
        assert unavailable["status"] == "UNAVAILABLE"
        assert unavailable["fact_refs"] == ["capability:REVIEW_ARTIFACT_NOT_AVAILABLE"]
        assert unavailable["actions"][0]["target"]["tab"] == "review"
        assert "primary_auc" not in unavailable.get("chart_data", {})

        review_result = {
            "contract_version": "counterfactual-review-v1",
            "status": "AVAILABLE",
            "evaluated_candidates": [
                {"candidate_id": "cf-move-1", "operation": "MOVE_MEMBER"}
            ],
            "recommendations": [{"candidate_id": "cf-move-1"}],
            "frontier": {
                "count_before_limit": 1,
                "selected_count": 1,
                "truncated": False,
            },
            "operation_status": {},
        }

        async def persisted_review(_chain_id: str) -> Any:
            return SimpleNamespace(status="SUCCEEDED", result=review_result)

        ws.latest_review = persisted_review
        available = asyncio.run(dispatch_assistant_tool(
            ws,
            "inspect_chart",
            {"chart_type": "counterfactual_review", "chain_id": "C1"},
            context,
        ))
        assert available["status"] == "AVAILABLE"
        assert available["chart_data"]["chart_type"] == "counterfactual_review"
        assert available["chart_data"]["recommendations"] == [
            {"candidate_id": "cf-move-1"}
        ]
        assert available["chart_data"]["frontier"]["selected_count"] == 1
        assert available["chart_data"]["evaluated_candidates"][0]["operation"] == "MOVE_MEMBER"
        assert "primary_auc" not in available["chart_data"]
    finally:
        app.state.workspace.close()


def test_assistant_endpoint_bridges_persisted_evolution_read_without_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://api.test/v1")
    monkeypatch.setenv("AI_MODEL", "mock-model")

    def select_evolution(*, tools: Any = None, **_kwargs: Any) -> GroundedAssistantCallResult:
        if _kwargs["messages"][-1]["role"] == "tool":
            return GroundedAssistantCallResult(
                content="Evolution chưa khả dụng vì chưa có chuỗi snapshot tuần tự đã xác minh.",
                tool_calls=[],
                model="mock-model",
                provider_status="OK",
                used_provider=True,
            )
        return GroundedAssistantCallResult(
            content="Evolution placeholder must not be used.",
            tool_calls=[
                LLMToolCall(
                    name="inspect_chart",
                    arguments={"chain_id": "C1", "chart_type": "evolution_lineage"},
                )
            ],
            model="mock-model",
            provider_status="OK",
            used_provider=True,
        )

    monkeypatch.setattr("nocpro_api.assistant.call_grounded_assistant", select_evolution)
    app = create_app()
    try:
        async def run() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                seeded = await client.post("/api/v1/snapshots", json=_payload())
                assert seeded.status_code == 201
                response = await asyncio.wait_for(
                    client.post(
                        "/api/v1/assistant/query",
                        json={
                            "query": "Evolution của C1 thế nào?",
                            "context": {
                                "snapshot_id": "s1",
                                "snapshot_version": "1",
                                "chain_id": "C1",
                            },
                        },
                    ),
                    timeout=2,
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["status"] == "UNAVAILABLE"
                assert payload["fact_refs"] == [
                    "capability:SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE"
                ]
                assert payload["chart_data"]["status"] == "UNAVAILABLE"
                assert "Evolution placeholder" not in payload["message"]

        asyncio.run(run())
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
                _run_deep_dive_explicitly(app.state.workspace)

                calls_count = 0

                def mock_call_assistant(messages: list[dict[str, Any]], tools: Any = None, **kwargs: Any) -> GroundedAssistantCallResult:
                    nonlocal calls_count
                    calls_count += 1
                    if messages[-1]["role"] != "tool":
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
                            content="Đường Primary AUC = 9.999 giảm mạnh tại bước 5 do loại bỏ temporal_burst.",
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
                assert "Đường Primary AUC = 9.999" not in data["message"]
                assert data["message"] == ""
                assert data["model"] == "mock-model"
                assert data["provider_status"] == "GROUNDING_NUMBER_MISMATCH"
                assert data["response_mode"] == "PROVIDER_UNAVAILABLE"
                assert len(data["actions"]) == 1
                assert data["actions"][0]["target"]["tab"] == "structure"
                assert calls_count == 2

        asyncio.run(run())
    finally:
        app.state.workspace.close()


def test_unconfigured_provider_does_not_infer_a_chart_or_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AI_API_KEY", "AI_BASE_URL", "AI_MODEL"):
        monkeypatch.delenv(name, raising=False)
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

        from nocpro_api.assistant import answer_query

        result = asyncio.run(answer_query(
            ws,
            "giải thích biểu đồ deletion curve chuỗi này",
            context,
        ))
        assert result["status"] == "NO_FINDING"
        assert result["provider_status"] in {"NOT_CONFIGURED", "PROVIDER_ERROR"}
        assert result["message"] == ""
        assert result["actions"] == []
    finally:
        app.state.workspace.close()
