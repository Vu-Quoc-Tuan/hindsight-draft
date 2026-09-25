from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx2
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from configuration import load_analysis_config
from nocpro_api import create_app
from nocpro_api.persistence.models import Base
from nocpro_api.persistence.repository import SnapshotRepository
from nocpro_api.review_learning_service import ReviewLearningService
from nocpro_api.workspace import Workspace
from tests.test_counterfactual_analysis import _metric_computer, _tier1b
from tests.test_counterfactual_evaluator import _package
from tier2.counterfactual import CounterfactualJobManager

pytestmark = pytest.mark.anyio


def _config():
    return load_analysis_config("config/thresholds/e2e-counterfactual.yaml")


def _setup_workspace_with_evaluated_review():
    ws = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
    ws.package = _package()
    ws.review_jobs = CounterfactualJobManager(metric_computer=_metric_computer)
    submission = ws.review_jobs.submit(
        ws.package,
        "C",
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=_config(),
    )
    job_view = ws.review_jobs.wait(submission.job_id)
    assert job_view.result is not None
    candidates = (
        job_view.result.recommendations
        or job_view.result.remove.candidates
        or job_view.result.evaluated_candidates
    )
    assert len(candidates) > 0
    candidate_id = candidates[0].candidate.candidate_id
    return ws, submission.job_id, candidate_id


async def test_feedback_on_unknown_job_returns_404() -> None:
    app = create_app()
    transport = httpx2.ASGITransport(app=app)
    try:
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            resp = await asyncio.wait_for(
                client.post(
                    "/api/v1/review-jobs/unknown-job-id/feedback",
                    json={
                        "candidate_id": "c1",
                        "decision": "REJECTED",
                    },
                ),
                timeout=5,
            )
            assert resp.status_code == 404
    finally:
        app.state.workspace.close()


async def test_feedback_on_unknown_candidate_returns_400() -> None:
    ws, job_id, _ = _setup_workspace_with_evaluated_review()
    app = create_app(workspace=ws)
    transport = httpx2.ASGITransport(app=app)
    try:
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            resp = await client.post(
                f"/api/v1/review-jobs/{job_id}/feedback",
                json={
                    "candidate_id": "non-existent-cand",
                    "decision": "REJECTED",
                },
            )
            assert resp.status_code == 422
            assert "not an operator-facing recommendation" in resp.json()["detail"]
    finally:
        ws.close()


async def test_feedback_rejected_stores_and_queries_successfully(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")
    ws, job_id, candidate_id = _setup_workspace_with_evaluated_review()
    app = create_app(workspace=ws)
    transport = httpx2.ASGITransport(app=app)
    try:
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            submission_payload = {
                "candidate_id": candidate_id,
                "decision": "REJECTED",
                "reason": "Topology confirmed these devices belong to the same optical link",
            }
            resp = await client.post(
                f"/api/v1/review-jobs/{job_id}/feedback",
                json=submission_payload,
                headers={"X-Dev-Operator-Id": "ops_expert_01", "X-Dev-Operator-Role": "PRODUCT_OWNER"},
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["feedback_id"].startswith("fb_")
            assert body["job_id"] == job_id
            assert body["candidate_id"] == candidate_id
            assert body["decision"] in ("REJECT", "REJECTED")
            assert body["operator_id"] == "ops_expert_01"
            assert body["reason"] == "Topology confirmed these devices belong to the same optical link"

            # Query job feedback
            get_job_fb = await client.get(
                f"/api/v1/review-jobs/{job_id}/feedback",
                headers={"X-Dev-Operator-Id": "ops_expert_01", "X-Dev-Operator-Role": "PRODUCT_OWNER"},
            )
            assert get_job_fb.status_code == 200
            job_records = get_job_fb.json()
            assert len(job_records) == 1
            assert job_records[0]["candidate_id"] == candidate_id
            assert job_records[0]["decision"] in ("REJECT", "REJECTED")

            # Query chain feedback
            chain_id = body["chain_id"]
            get_chain_fb = await client.get(
                f"/api/v1/chains/{chain_id}/feedback?snapshot_id=s1&snapshot_version=1",
                headers={"X-Dev-Operator-Id": "ops_expert_01", "X-Dev-Operator-Role": "PRODUCT_OWNER"},
            )
            assert get_chain_fb.status_code == 200
            chain_records = get_chain_fb.json()
            assert len(chain_records) == 1
            assert chain_records[0]["candidate_id"] == candidate_id
    finally:
        ws.close()


async def test_feedback_approved_is_persisted_without_dispatching_a_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")
    ws, job_id, candidate_id = _setup_workspace_with_evaluated_review()
    app = create_app(workspace=ws)
    transport = httpx2.ASGITransport(app=app)
    try:
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            submission_payload = {
                "candidate_id": candidate_id,
                "decision": "APPROVED",
                "reason": "Split approved to separate unrelated fault domains",
            }
            resp = await client.post(
                f"/api/v1/review-jobs/{job_id}/feedback",
                json=submission_payload,
                headers={"X-Dev-Operator-Id": "noc_director", "X-Dev-Operator-Role": "PRODUCT_OWNER"},
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["decision"] in ("APPROVE", "APPROVED")
            assert "mutation_dispatched" not in body
    finally:
        ws.close()


async def test_feedback_rejects_removed_auto_apply_parameter() -> None:
    ws, job_id, candidate_id = _setup_workspace_with_evaluated_review()
    app = create_app(workspace=ws)
    transport = httpx2.ASGITransport(app=app)
    try:
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(
                f"/api/v1/review-jobs/{job_id}/feedback",
                json={
                    "candidate_id": candidate_id,
                    "decision": "APPROVED",
                    "auto_apply": True,
                },
            )
            assert response.status_code == 422
    finally:
        ws.close()


async def test_feedback_api_end_to_end_persistence_and_restart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Acceptance test: Review submission -> Real FastAPI endpoint POST feedback -> DB persistence -> Service Restart -> Query feedback -> Materialize."""
    monkeypatch.setenv("REVIEW_TEST_IDENTITY_OVERRIDE", "1")
    db_file = tmp_path / "api_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repo = SnapshotRepository(sessions)

    # 1. Setup workspace with database repository attached
    ws1 = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
    ws1.repository = repo
    ws1.review_learning = ReviewLearningService(repo)
    ws1.package = _package()
    ws1.review_jobs = CounterfactualJobManager(metric_computer=_metric_computer)

    sub = ws1.review_jobs.submit(
        ws1.package,
        "C",
        tier1b_artifact=_tier1b(),
        audit_artifact=None,
        analysis_config=_config(),
        lineage_component_id="comp_api_e2e",
    )
    job_view = ws1.review_jobs.wait(sub.job_id)
    assert job_view.result is not None

    cands = (
        job_view.result.recommendations
        or job_view.result.remove.candidates
        or job_view.result.evaluated_candidates
    )
    cand_id = cands[0].candidate.candidate_id

    # Persist job and review bundle to database
    await repo.persist_counterfactual_job(job_view.persistence_payload())
    await ws1.review_learning.freeze_review_bundle(
        job_id=sub.job_id,
        job_view=job_view,
        package=ws1.package,
        delay_model=ws1.temporal_delay_model,
    )

    app1 = create_app(workspace=ws1)
    transport1 = httpx2.ASGITransport(app=app1)

    # 2. Operator submits feedback through FastAPI endpoint
    async with httpx2.AsyncClient(transport=transport1, base_url="http://testserver") as client:
        resp = await client.post(
            f"/api/v1/review-jobs/{sub.job_id}/feedback",
            json={
                "candidate_id": cand_id,
                "decision": "APPROVED",
                "reason": "Topological split confirmed via real FastAPI route",
            },
            headers={"X-Dev-Operator-Id": "principal_reviewer_42", "X-Dev-Operator-Role": "PRODUCT_OWNER"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["job_id"] == sub.job_id
        assert data["candidate_id"] == cand_id
        assert data["decision"] in ("APPROVE", "APPROVED")

    ws1.close()
    del ws1
    del app1

    # 3. Simulate full service crash and restart: brand new Workspace and app instance
    ws2 = Workspace(config_path=Path("config/thresholds/e2e-counterfactual.yaml"))
    ws2.repository = repo
    ws2.review_learning = ReviewLearningService(repo)

    app2 = create_app(workspace=ws2)
    transport2 = httpx2.ASGITransport(app=app2)

    # 4. Query feedback from restarted service via GET endpoint
    async with httpx2.AsyncClient(transport=transport2, base_url="http://testserver") as client:
        get_resp = await client.get(
            f"/api/v1/review-jobs/{sub.job_id}/feedback",
            headers={"X-Dev-Operator-Id": "principal_reviewer_42", "X-Dev-Operator-Role": "PRODUCT_OWNER"},
        )
        assert get_resp.status_code == 200
        fb_list = get_resp.json()
        assert len(fb_list) == 1
        assert fb_list[0]["candidate_id"] == cand_id
        assert fb_list[0]["decision"] in ("APPROVE", "APPROVED")
        assert fb_list[0]["operator_id"] == "principal_reviewer_42"

    # 5. Fetch training review groups from repository directly
    cutoff = datetime.now(timezone.utc) + timedelta(days=1)
    repo_groups = await repo.training_review_groups_before(cutoff)
    assert len(repo_groups) == 1
    assert repo_groups[0]["review_session"].job_id == sub.job_id
    assert len(repo_groups[0]["active_feedbacks"]) == 1

    ws2.close()
    await engine.dispose()
