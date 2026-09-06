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
from nocpro_api.assistant import render_answer
from nocpro_api.grounded_llm import GroundedRenderResult
from tests.test_api import _payload


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


def test_ai_advisor_uses_recommendation_refs_to_find_evaluated_detail(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    result = generate_ai_suggestion("C1", _analysis(), _review())

    assert result.status == "AVAILABLE"
    assert result.model == "DETERMINISTIC_EVIDENCE"
    assert result.provider_status == "NOT_CONFIGURED"
    assert "REMOVE_MEMBER (cf-1)" in result.narrative
    assert "does not infer root cause" in result.narrative


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
    assert "could not be read" in result.narrative
    assert "No operator-facing counterfactual recommendation" not in result.narrative


def test_ai_suggestion_api_endpoint_falls_back_when_provider_is_not_configured(
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
                assert first.json()["model"] == "DETERMINISTIC_EVIDENCE"
                assert first.json()["provider_status"] == "NOT_CONFIGURED"
                assert "ADR-0024" in first.json()["disclaimer"]
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_assistant_query_is_snapshot_bound_and_only_returns_typed_navigation() -> None:
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
                assert body["actions"] == [{
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
                }]
                assert "root cause" not in body["message"].lower()

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
        "model": "DETERMINISTIC_EVIDENCE",
        "provider_status": "NOT_APPLIED",
    }


def test_assistant_route_renders_after_typed_action_generation(monkeypatch) -> None:
    def fake_render_grounded(**_kwargs):
        return GroundedRenderResult(
            message="Bản diễn giải đã được render từ action hợp lệ.",
            model="configured-model",
            provider_status="OK",
            used_provider=True,
        )

    monkeypatch.setattr(
        "nocpro_api.assistant.render_grounded",
        fake_render_grounded,
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
                assert body["message"] == "Bản diễn giải đã được render từ action hợp lệ."
                assert body["model"] == "configured-model"
                assert body["provider_status"] == "OK"
                assert body["fact_refs"] == ["ui-context:C1"]
                assert body["actions"] == [{
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
                }]
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
                assert missing_chain.json()["status"] == "UNAVAILABLE"
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
                assert invalid_pair.json()["status"] == "UNAVAILABLE"
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
                assert valid_pair.json()["actions"] == [{
                    "kind": "NAVIGATE",
                    "label": "Open Pair WHY",
                    "target": {
                        "snapshot_id": "s1", "snapshot_version": "1", "chain_id": "C1", "tab": "why",
                        "pair_alarm_id_a": "a1", "pair_alarm_id_b": "a2",
                    },
                }]
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_assistant_explains_registry_without_claiming_root_cause() -> None:
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
                assert "root-cause claim" in body["message"]
                assert body["fact_refs"] == ["semantic-registry:conductance"]
        finally:
            app.state.workspace.close()

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
                assert body["status"] == "UNAVAILABLE"
                assert "capability:RESOURCE_TO_CHAIN_MAPPING_UNAVAILABLE" in body["fact_refs"]
                assert body["actions"] == [{
                    "kind": "NAVIGATE", "label": "Open Topology", "target": {
                        "snapshot_id": "s1", "snapshot_version": "1", "chain_id": None,
                        "tab": "topology", "pair_alarm_id_a": None, "pair_alarm_id_b": None,
                    },
                }]
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())
