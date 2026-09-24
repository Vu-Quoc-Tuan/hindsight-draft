"""Regression tests for ADR-0024 deterministic evidence rendering."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx2
import pytest

from nocpro_api import create_app
from nocpro_api.ai_advisor import (
    build_deterministic_narrative,
    extract_grounded_claims,
    generate_ai_suggestion,
)
from nocpro_api.assistant import answer_query, render_answer
from nocpro_api.grounded_llm import GroundedRenderResult
from tests.test_api import _payload


@pytest.fixture(autouse=True)
def _isolate_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests independent from a developer's project-root .env."""
    for name in (
        "AI_PROVIDER_PROTOCOL",
        "AI_BASE_URL",
        "AI_API_KEY",
        "AI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def _analysis() -> SimpleNamespace:
    return SimpleNamespace(
        members={
            "A1": SimpleNamespace(
                role=SimpleNamespace(verdict="CORE", support=0.91),
                representativeness=0.82,
            ),
            "A2": SimpleNamespace(
                role=SimpleNamespace(verdict="WEAK", support=0.12),
                representativeness=0.10,
            ),
            "A3": SimpleNamespace(
                role=SimpleNamespace(
                    verdict="INSUFFICIENT_DATA",
                    support=None,
                ),
                representativeness=None,
            ),
        },
        descriptors=[
            SimpleNamespace(label="same entity", coverage=0.85),
        ],
    )


def _review() -> dict[str, object]:
    return {
        "evaluated_candidates": [
            {
                "candidate_id": "cf-1",
                "operation": "REMOVE_MEMBER",
            }
        ],
        "recommendations": [{"candidate_id": "cf-1"}],
        "recommendation_status": "AVAILABLE",
    }


def test_ai_advisor_projects_actual_member_role_shape() -> None:
    structured, claims = extract_grounded_claims("C100", _analysis(), _review())

    assert structured["member_count"] == 3
    assert structured["weak_members"] == ["A2"]
    assert structured["insufficient_members"] == ["A3"]
    assert structured["proposals"] == [
        {"candidate_id": "cf-1", "operation": "REMOVE_MEMBER"}
    ]
    assert any("WEAK" in claim for claim in claims)
    assert any("INSUFFICIENT_DATA" in claim for claim in claims)
    assert all("root cause" not in claim.lower() for claim in claims)


def test_ai_advisor_never_converts_absence_of_weak_into_high_fit() -> None:
    analysis = SimpleNamespace(
        members={
            "A1": SimpleNamespace(
                role=SimpleNamespace(
                    verdict="INSUFFICIENT_DATA",
                    support=None,
                ),
                representativeness=None,
            )
        },
        descriptors=[],
    )
    structured, _ = extract_grounded_claims("C1", analysis)
    narrative = build_deterministic_narrative("C1", structured)

    assert "Evidence is incomplete for: A1." in narrative
    assert "high fit" not in narrative.lower()
    assert "causal direction is" not in narrative.lower()


def test_ai_advisor_fail_closes_missing_and_bounded_review_states() -> None:
    structured, _ = extract_grounded_claims("C1", _analysis())

    missing = build_deterministic_narrative(
        "C1", structured, review_status="NOT_AVAILABLE", language="vi"
    )
    assert "chưa được thực hiện" in missing
    assert "không ghi nhận phương án" not in missing
    assert "Pareto" not in missing

    bounded = build_deterministic_narrative(
        "C1",
        {**structured, "recommendation_status": "NO_CLEAR_ALTERNATIVE"},
        review_status="AVAILABLE",
        language="vi",
    )
    assert "không gian tìm kiếm hữu hạn đã đánh giá" in bounded
    assert "tối ưu" not in bounded.lower()
    assert "thuần nhất" not in bounded.lower()


def test_ai_advisor_uses_recommendation_refs_to_find_evaluated_detail(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    result = generate_ai_suggestion(
        "C1", _analysis(), _review(), review_status="AVAILABLE"
    )

    assert result.status == "AVAILABLE"
    assert result.model == ""
    assert result.provider_status == "NOT_CONFIGURED"
    assert result.narrative == ""


def test_ai_advisor_uses_llm_only_for_grounded_narrative(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_render_grounded(**kwargs):
        captured.update(kwargs)
        return GroundedRenderResult(
            message="Rendered grounded advisor text",
            model="configured-model",
            provider_status="OK",
            used_provider=True,
        )

    monkeypatch.setattr(
        "nocpro_api.ai_advisor.render_grounded",
        fake_render_grounded,
    )
    result = generate_ai_suggestion("C1", _analysis(), _review())

    assert result.narrative == "Rendered grounded advisor text"
    assert result.model == "configured-model"
    assert result.provider_status == "OK"
    assert result.grounded_claims == [
        "Chain C1 contains 3 analyzed members.",
        "1 member(s) are classified WEAK: A2.",
        "1 member(s) have INSUFFICIENT_DATA: A3.",
        "Top descriptors: same entity (coverage 85%).",
        "Operator-facing counterfactual recommendation: REMOVE_MEMBER (cf-1).",
    ]
    assert captured["purpose"] == "ADVISOR"
    assert captured["fact_refs"] == result.grounded_claims
    facts = captured["facts"]
    assert isinstance(facts, dict)
    assert facts["structured_analysis"]["weak_members"] == ["A2"]
    assert facts["review_status"] == "NOT_AVAILABLE"
    assert "does not infer root cause" in str(captured["draft"])


def test_ai_advisor_distinguishes_unavailable_review_from_no_recommendation(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    result = generate_ai_suggestion(
        "C1",
        _analysis(),
        review_status="UNAVAILABLE",
        review_reason="REVIEW_ARTIFACT_UNAVAILABLE",
    )

    assert result.review_status == "UNAVAILABLE"
    assert result.review_reason == "REVIEW_ARTIFACT_UNAVAILABLE"
    assert result.narrative == ""


def test_ai_suggestion_api_endpoint_surfaces_provider_unavailable_without_fallback(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                loaded = await client.post("/api/v1/snapshots", json=_payload())
                assert loaded.status_code == 201

                first = await client.get("/api/v1/chains/C1/ai-suggestion")
                second = await client.get("/api/v1/chains/C1/ai-suggestion")
                assert first.status_code == 200
                assert second.status_code == 200
                assert first.json() == second.json()
                assert first.json()["model"] == ""
                assert first.json()["provider_status"] == "NOT_CONFIGURED"
                assert first.json()["narrative"] == ""
                assert "ADR-0024" in first.json()["disclaimer"]
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_assistant_query_is_snapshot_bound_and_does_not_infer_offline_navigation() -> None:
    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                loaded = await client.post("/api/v1/snapshots", json=_payload())
                assert loaded.status_code == 201
                context = {
                    "snapshot_id": "s1",
                    "snapshot_version": "1",
                    "page": "tree",
                    "chain_id": "C1",
                }
                response = await client.post(
                    "/api/v1/assistant/query",
                    json={"query": "open audit", "context": context},
                )
                assert response.status_code == 200
                body = response.json()
                assert body["contract_version"] == "nocpro-assistant-v1"
                assert body["status"] == "NO_FINDING"
                assert body["message"] == ""
                assert body["provider_status"] == "NOT_CONFIGURED"
                assert body["response_mode"] == "PROVIDER_UNAVAILABLE"
                assert body["fact_refs"] == []
                assert body["actions"] == []

                stale = await client.post(
                    "/api/v1/assistant/query",
                    json={"query": "open audit", "context": {**context, "snapshot_version": "99"}},
                )
                assert stale.status_code == 200
                assert stale.json()["status"] == "STALE_CONTEXT"
                assert stale.json()["actions"] == []
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_assistant_llm_can_change_only_the_deterministic_message(monkeypatch) -> None:
    deterministic = {
        "status": "AVAILABLE",
        "message": "Open the exact persisted Audit result.",
        "fact_refs": ["ui-context:C1"],
        "actions": [
            {
                "kind": "NAVIGATE",
                "label": "Open Structural Audit",
                "target": {
                    "snapshot_id": "s1",
                    "snapshot_version": "1",
                    "chain_id": "C1",
                    "tab": "structure",
                    "pair_alarm_id_a": None,
                    "pair_alarm_id_b": None,
                },
            }
        ],
    }
    captured: dict[str, object] = {}

    def fake_render_grounded(**kwargs):
        captured.update(kwargs)
        return GroundedRenderResult(
            message="Rendered assistant text",
            model="configured-model",
            provider_status="OK",
            used_provider=True,
        )

    monkeypatch.setattr(
        "nocpro_api.assistant.render_grounded",
        fake_render_grounded,
    )
    result = render_answer(
        context={"snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1"},
        deterministic=deterministic,
    )

    assert result["message"] == "Rendered assistant text"
    assert result["status"] == deterministic["status"]
    assert result["fact_refs"] == deterministic["fact_refs"]
    assert result["actions"] == deterministic["actions"]
    assert result["model"] == "configured-model"
    assert result["provider_status"] == "OK"
    assert captured["purpose"] == "ASSISTANT"
    assert captured["draft"] == deterministic["message"]
    assert captured["fact_refs"] == deterministic["fact_refs"]


def test_assistant_stale_context_never_invokes_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        "nocpro_api.assistant.render_grounded",
        lambda **_kwargs: pytest.fail("stale context must not invoke provider"),
    )
    deterministic = {
        "status": "STALE_CONTEXT",
        "message": "Refresh the workspace.",
        "fact_refs": [],
        "actions": [],
    }

    result = render_answer(
        context={"snapshot_id": "s1", "snapshot_version": "99"},
        deterministic=deterministic,
    )

    assert result == {
        **deterministic,
        "model": "",
        "provider_status": "STALE_CONTEXT",
        "response_mode": "PROVIDER_UNAVAILABLE",
        "tools_used": [],
    }


def test_assistant_route_does_not_infer_actions_when_provider_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "nocpro_api.assistant.render_grounded",
        lambda **_kwargs: pytest.fail("provider must not be called when unconfigured"),
    )

    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                await client.post("/api/v1/snapshots", json=_payload())
                response = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "open audit",
                        "context": {
                            "snapshot_id": "s1",
                            "snapshot_version": "1",
                            "page": "tree",
                            "chain_id": "C1",
                        },
                    },
                )
                assert response.status_code == 200
                body = response.json()
                assert body["message"] == ""
                assert body["model"] == ""
                assert body["provider_status"] == "NOT_CONFIGURED"
                assert body["response_mode"] == "PROVIDER_UNAVAILABLE"
                assert body["status"] == "NO_FINDING"
                assert body["fact_refs"] == []
                assert body["actions"] == []
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_assistant_rejects_missing_or_invalid_snapshot_bound_targets() -> None:
    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                await client.post("/api/v1/snapshots", json=_payload())
                missing_identity = await client.post(
                    "/api/v1/assistant/query",
                    json={"query": "open audit", "context": {"chain_id": "C1"}},
                )
                assert missing_identity.status_code == 422

                missing_chain = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "open review",
                        "context": {
                            "snapshot_id": "s1", "snapshot_version": "1", "chain_id": "missing",
                        },
                    },
                )
                assert missing_chain.status_code == 200
                assert missing_chain.json()["status"] == "NO_FINDING"
                assert missing_chain.json()["provider_status"] == "NOT_CONFIGURED"
                assert missing_chain.json()["actions"] == []

                invalid_pair = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "open pair why",
                        "context": {
                            "snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1",
                            "pair_alarm_id_a": "a1", "pair_alarm_id_b": "missing",
                        },
                    },
                )
                assert invalid_pair.status_code == 200
                assert invalid_pair.json()["status"] == "NO_FINDING"
                assert invalid_pair.json()["provider_status"] == "NOT_CONFIGURED"
                assert invalid_pair.json()["actions"] == []

                valid_pair = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "open pair why",
                        "context": {
                            "snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1",
                            "pair_alarm_id_a": "a1", "pair_alarm_id_b": "a2",
                        },
                    },
                )
                assert valid_pair.status_code == 200
                assert valid_pair.json()["status"] == "NO_FINDING"
                assert valid_pair.json()["provider_status"] == "NOT_CONFIGURED"
                assert valid_pair.json()["actions"] == []
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_assistant_does_not_expose_registry_facts_as_ai_fallback() -> None:
    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                await client.post("/api/v1/snapshots", json=_payload())
                response = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "conductance là gì",
                        "context": {"snapshot_id": "s1", "snapshot_version": "1"},
                    },
                )
                assert response.status_code == 200
                body = response.json()
                assert body["message"] == ""
                assert body["provider_status"] == "NOT_CONFIGURED"
                assert body["response_mode"] == "PROVIDER_UNAVAILABLE"
                assert body["status"] == "NO_FINDING"
                assert body["fact_refs"] == []
                assert body["actions"] == []
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_assistant_empty_query_does_not_expose_selected_metric_as_ai_fallback() -> None:
    async def exercise() -> None:
        service = SimpleNamespace(active_identity=lambda: ("s1", "1"))
        context = {
            "snapshot_id": "s1",
            "snapshot_version": "1",
            "selected_metric": "conductance",
        }

        deterministic = await answer_query(service, "", context)
        rendered = render_answer(context=context, deterministic=deterministic)

        assert rendered["message"] == ""
        assert rendered["fact_refs"] == ["semantic-registry:conductance"]
        assert rendered["provider_status"] == "EMPTY_QUERY"
        assert rendered["response_mode"] == "PROVIDER_UNAVAILABLE"

        no_selection = await answer_query(
            service,
            "",
            {"snapshot_id": "s1", "snapshot_version": "1"},
        )
        assert no_selection["message"] == ""
        assert no_selection["status"] == "NO_FINDING"
        assert no_selection["fact_refs"] == ["semantic-registry:nocpro-assistant-registry-v1"]
        assert no_selection["provider_status"] == "EMPTY_QUERY"
        assert no_selection["response_mode"] == "PROVIDER_UNAVAILABLE"

    asyncio.run(exercise())


def test_assistant_fails_closed_for_resource_to_chain_search() -> None:
    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                await client.post("/api/v1/snapshots", json=_payload())
                response = await client.post(
                    "/api/v1/assistant/query",
                    json={
                        "query": "find service billing-api",
                        "context": {"snapshot_id": "s1", "snapshot_version": "1"},
                    },
                )
                assert response.status_code == 200
                body = response.json()
                assert body["status"] == "NO_FINDING"
                assert body["provider_status"] == "NOT_CONFIGURED"
                assert body["fact_refs"] == []
                assert body["actions"] == []
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_ai_advisor_renders_comparative_explanation_in_vietnamese() -> None:
    review = {
        "evaluated_candidates": [
            {
                "candidate_id": "rem-1",
                "operation": "REMOVE_MEMBER",
                "comparative_explanation": {
                    "summary_action": "Tách cảnh báo A2 (Device-1 - Link Down) ra khỏi chuỗi",
                    "why_better": "Loại bỏ cảnh báo có độ hỗ trợ yếu giúp tăng độ tin cậy liên kết từ 12% lên 91% (+79%).",
                    "delta_highlights": [
                        {
                            "metric_name": "minimum_membership_support",
                            "label": "Min support",
                            "before": "12.0%",
                            "after": "91.0%",
                            "delta": "+79.0%",
                            "is_improvement": True,
                        },
                        {
                            "metric_name": "weak_member_count",
                            "label": "Weak members",
                            "before": "1",
                            "after": "0",
                            "delta": "-1",
                            "is_improvement": True,
                        },
                    ],
                    "comparison_points": [
                        "Loại bỏ 1 cảnh báo yếu có độ hỗ trợ chỉ 12.0%.",
                    ],
                },
            }
        ],
        "recommendations": [{"candidate_id": "rem-1"}],
        "recommendation_status": "AVAILABLE",
    }

    result = generate_ai_suggestion(
        "C100", _analysis(), review_result=review, review_status="AVAILABLE", language="vi"
    )

    assert result.status == "AVAILABLE"
    assert result.narrative == ""
    assert result.provider_status == "NOT_CONFIGURED"
    assert any("Proposal action:" in claim for claim in result.grounded_claims)
    assert any("Proposal rationale:" in claim for claim in result.grounded_claims)


def test_ai_advisor_does_not_infer_optimality_when_review_status_is_missing() -> None:
    clean_analysis = SimpleNamespace(
        members={
            "A1": SimpleNamespace(
                role=SimpleNamespace(verdict="CORE", support=0.95),
                representativeness=0.88,
            ),
            "A2": SimpleNamespace(
                role=SimpleNamespace(verdict="CORE", support=0.92),
                representativeness=0.85,
            ),
        },
        descriptors=[SimpleNamespace(label="same entity", coverage=1.0)],
    )
    empty_review = {
        "evaluated_candidates": [],
        "recommendations": [],
    }

    result = generate_ai_suggestion(
        "C200", clean_analysis, review_result=empty_review, review_status="AVAILABLE", language="vi"
    )

    assert result.status == "AVAILABLE"
    assert result.narrative == ""
    assert result.provider_status == "NOT_CONFIGURED"
    assert "Xác thực Pareto" not in result.narrative
    assert "cấu trúc thuần nhất" not in result.narrative
    assert "phân mảnh tô-pô" not in result.narrative


def test_ai_advisor_extracts_and_renders_operational_facts() -> None:
    pkg = SimpleNamespace(
        alarms=[
            SimpleNamespace(
                alarm_id="A1",
                device_code="node-81",
                alarm_name="OpenstackServiceStatus",
                severity_name="Major",
                canonical_start_time="2024-03-29 09:27:59",
                raw={"content": "Service nova-compute is DOWN", "site": "SITE: HANOI-DC"},
            ),
            SimpleNamespace(
                alarm_id="A2",
                device_code="node-82",
                alarm_name="OpenstackServiceStatus",
                severity_name="Major",
                canonical_start_time="2024-03-29 09:32:13",
                raw={"content": "Service neutron-server is DOWN", "site": "HANOI-DC"},
            ),
        ]
    )
    analysis = SimpleNamespace(
        members={
            "A1": SimpleNamespace(
                role=SimpleNamespace(verdict="CORE", support=0.92),
                representativeness=0.88,
            ),
            "A2": SimpleNamespace(
                role=SimpleNamespace(verdict="WEAK", support=0.15),
                representativeness=0.20,
            ),
        },
        descriptors=[SimpleNamespace(label="same entity", coverage=0.9)],
    )

    structured, claims = extract_grounded_claims("C300", analysis, package=pkg)
    assert structured["operational_facts"]["has_package_data"] is True
    assert structured["operational_facts"]["device_names"] == ["node-81", "node-82"]
    assert structured["operational_facts"]["locations"] == ["HANOI-DC"]
    assert structured["operational_facts"]["duration_seconds"] == 254
    assert len(structured["operational_facts"]["delayed_alarms"]) == 1
    assert structured["operational_facts"]["delayed_alarms"][0]["alarm_id"] == "A2"
    assert any("node-81" in c for c in claims)
    assert any("HANOI-DC" in c for c in claims)
    assert any("duration 254s" in c for c in claims)
    assert any("Delayed alarm A2" in c for c in claims)

    narrative_vi = build_deterministic_narrative("C300", structured, language="vi")
    assert "node-81" in narrative_vi
    assert "HANOI-DC" in narrative_vi
    assert "254 giây" in narrative_vi
    assert "Đợt bùng phát trễ" in narrative_vi
    assert "A2" in narrative_vi

    result = generate_ai_suggestion("C300", analysis, package=pkg, language="vi")
    assert result.status == "AVAILABLE"
    assert result.narrative == ""
    assert result.provider_status == "NOT_CONFIGURED"
