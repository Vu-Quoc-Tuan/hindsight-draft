"""C4 route contract: exact context, direct edge, and explicit receipt choice."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
import httpx2
import pytest

from nocpro_api.routes import router


CHILD = ("s2", "v2", "c2")
PARENT = ("s1", "v1", "c1")
HEADERS = {"x-nocpro-snapshot-id": "s2", "x-nocpro-snapshot-version": "v2"}
PATH = "/api/v1/chains/c2/evolution/changes"
SELECTED = "?parent_snapshot_id=s1&parent_snapshot_version=v1&parent_chain_id=c1"


def edge(parent=PARENT):
    return {
        "parent_snapshot_id": parent[0], "parent_snapshot_version": parent[1],
        "parent_chain_id": parent[2], "child_snapshot_id": "s2",
        "child_snapshot_version": "v2", "child_chain_id": "c2",
        "event_type": "MERGE", "overlap_count": 1,
        "parent_snapshot_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "child_snapshot_time": datetime(2026, 1, 2, tzinfo=timezone.utc),
        "parent_source_kind": "SYNTHETIC", "child_source_kind": "REAL_EXPORT_REPLAY",
    }


def receipt(endpoint, receipt_id):
    return SimpleNamespace(
        receipt_id=receipt_id, artifact_revision=receipt_id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        analysis_identity=dict(zip(("snapshot_id", "snapshot_version", "chain_id"), endpoint)),
        assessment={}, source_artifact_refs={},
    )


def test_response_membership_model_rejects_more_than_100_ids():
    from pydantic import ValidationError
    from nocpro_api.schemas import EvolutionMembershipView

    with pytest.raises(ValidationError):
        EvolutionMembershipView.model_validate({
            "added_count": 101, "removed_count": 0, "retained_count": 0,
            "added_alarm_ids": [f"a{i:03}" for i in range(101)],
            "removed_alarm_ids": [], "truncated": True,
        })


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setenv("NOCPRO_EVOLUTION_CHANGES_ENABLED", "true")
    repo = SimpleNamespace(
        list_evolution_predecessors=AsyncMock(return_value=([edge(), edge(("s0", "v1", "c0"))], False)),
        get_evolution_edge=AsyncMock(return_value=edge()),
        evolution_membership_summary=AsyncMock(return_value={
            "added_count": 1, "removed_count": 1, "retained_count": 1,
            "added_alarm_ids": ["a3"], "removed_alarm_ids": ["a1"], "truncated": False,
        }),
        list_evolution_endpoint_receipts=AsyncMock(return_value=([], False)),
        quality_evaluation_receipt=AsyncMock(return_value=None),
        load_evolution=AsyncMock(),
    )
    package = SimpleNamespace(snapshot=SimpleNamespace(snapshot_id="s2", snapshot_version="v2"), chains={"c2": object()})
    service = SimpleNamespace(repository=repo, require_package=lambda: package)
    app = FastAPI()
    app.state.workspace = service
    app.include_router(router)
    return app, repo, monkeypatch


async def get(app, path=PATH, headers=HEADERS):
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, headers=headers)


@pytest.mark.anyio
async def test_default_off_and_exact_child_context(harness):
    app, repo, monkeypatch = harness
    monkeypatch.delenv("NOCPRO_EVOLUTION_CHANGES_ENABLED")
    assert (await get(app)).status_code == 503
    monkeypatch.setenv("NOCPRO_EVOLUTION_CHANGES_ENABLED", "true")
    assert (await get(app, headers={})).status_code == 409
    assert (await get(app, headers={**HEADERS, "x-nocpro-snapshot-version": "v1"})).status_code == 409
    assert (await get(app, path=PATH.replace("c2", "missing"))).status_code == 404
    repo.list_evolution_predecessors.assert_not_awaited()


@pytest.mark.anyio
async def test_merge_returns_bounded_parent_choices_without_comparison(harness):
    app, repo, _ = harness
    response = await get(app)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PARTIAL"
    assert body["parent"] is None
    assert {choice["parent"]["chain_id"] for choice in body["predecessor_choices"]} == {"c0", "c1"}
    repo.get_evolution_edge.assert_not_awaited()
    repo.load_evolution.assert_not_awaited()


@pytest.mark.anyio
async def test_selection_errors_and_unknown_edge(harness):
    app, repo, _ = harness
    assert (await get(app, PATH + "?parent_snapshot_id=s1")).status_code == 422
    assert (await get(app, PATH + "?child_receipt_id=r1")).status_code == 422
    repo.get_evolution_edge.return_value = None
    assert (await get(app, PATH + SELECTED)).status_code == 404


@pytest.mark.anyio
async def test_membership_survives_missing_receipts_and_mismatch_rejected(harness):
    app, repo, _ = harness
    response = await get(app, PATH + SELECTED)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PARTIAL"
    assert body["membership"]["retained_count"] == 1
    assert body["quality"]["delta"] is None
    assert {item["field"] for item in body["context_changes"]} == {"source_kind"}
    repo.quality_evaluation_receipt.return_value = receipt(("other", "v1", "c1"), "r-wrong")
    assert (await get(app, PATH + SELECTED + "&parent_receipt_id=r-wrong")).status_code == 422
    repo.load_evolution.assert_not_awaited()


@pytest.mark.anyio
async def test_ambiguous_receipts_offer_choices_and_explicit_selection(harness):
    app, repo, _ = harness
    repo.list_evolution_endpoint_receipts.side_effect = [
        ([receipt(PARENT, "p1"), receipt(PARENT, "p2")], False),
        ([receipt(CHILD, "c1")], False),
    ]
    response = await get(app, PATH + SELECTED)
    assert response.status_code == 200
    body = response.json()
    assert "RECEIPT_SELECTION_REQUIRED" in body["reason_codes"]
    assert [item["receipt_id"] for item in body["parent_receipt_choices"]] == ["p1", "p2"]
    assert body["quality"]["before_receipt_id"] is None
    repo.quality_evaluation_receipt.return_value = receipt(PARENT, "p1")
    repo.list_evolution_endpoint_receipts.reset_mock(side_effect=True)
    repo.list_evolution_endpoint_receipts.return_value = ([receipt(CHILD, "c1")], False)
    chosen = await get(app, PATH + SELECTED + "&parent_receipt_id=p1")
    assert chosen.status_code == 200
    assert chosen.json()["quality"]["before_receipt_id"] == "p1"


@pytest.mark.anyio
async def test_database_error_is_503(harness):
    from sqlalchemy.exc import OperationalError

    app, repo, _ = harness
    repo.list_evolution_predecessors.side_effect = OperationalError("select", {}, Exception("down"))
    assert (await get(app)).status_code == 503


@pytest.mark.anyio
async def test_missing_repository_and_context_change_during_read(harness):
    app, repo, _ = harness
    service = app.state.workspace
    service.repository = None
    assert (await get(app)).status_code == 503
    service.repository = repo
    first = service.require_package()
    calls = 0

    def switched_package():
        nonlocal calls
        calls += 1
        return first if calls == 1 else SimpleNamespace(snapshot=first.snapshot, chains=first.chains)

    service.require_package = switched_package
    assert (await get(app)).status_code == 409


@pytest.mark.anyio
async def test_overlap_mismatch_hides_membership(harness):
    app, repo, _ = harness
    repo.evolution_membership_summary.return_value = {
        "added_count": 0, "removed_count": 0, "retained_count": 2,
        "added_alarm_ids": [], "removed_alarm_ids": [], "truncated": False,
    }
    response = await get(app, PATH + SELECTED)
    assert response.status_code == 200
    assert response.json()["membership"] is None
    assert "LINEAGE_OVERLAP_MISMATCH" in response.json()["reason_codes"]
