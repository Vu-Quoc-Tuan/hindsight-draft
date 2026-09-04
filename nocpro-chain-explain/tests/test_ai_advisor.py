"""Regression tests for ADR-0024 deterministic evidence rendering."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx2

from nocpro_api import create_app
from nocpro_api.ai_advisor import (
    build_deterministic_narrative,
    extract_grounded_claims,
    generate_ai_suggestion,
)
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


def test_ai_advisor_uses_recommendation_refs_to_find_evaluated_detail() -> None:
    result = generate_ai_suggestion("C1", _analysis(), _review())

    assert result.status == "AVAILABLE"
    assert result.model == "DETERMINISTIC_EVIDENCE"
    assert result.provider_status == "NOT_USED"
    assert "REMOVE_MEMBER (cf-1)" in result.narrative
    assert "does not infer root cause" in result.narrative


def test_ai_suggestion_api_endpoint_is_deterministic_and_provider_free() -> None:
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
                assert first.json()["provider_status"] == "NOT_USED"
                assert "ADR-0024" in first.json()["disclaimer"]
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())
