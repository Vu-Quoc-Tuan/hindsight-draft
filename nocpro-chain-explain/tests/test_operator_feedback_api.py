from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx2
import pytest

from configuration import load_analysis_config
from nocpro_api import create_app
from nocpro_api.workspace import Workspace
from tests.test_api import _payload
from tests.test_counterfactual_analysis import _metric_computer, _tier1b
from tests.test_counterfactual_evaluator import _package
from tier2.counterfactual import CounterfactualJobManager


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


def test_feedback_on_unknown_job_returns_404() -> None:
    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                resp = await client.post(
                    "/api/v1/review-jobs/unknown-job-id/feedback",
                    json={
                        "candidate_id": "c1",
                        "decision": "REJECTED",
                    },
                )
                assert resp.status_code == 404
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_feedback_on_unknown_candidate_returns_400() -> None:
    async def exercise() -> None:
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
                assert "not found in review job" in resp.json()["detail"]
        finally:
            ws.close()

    asyncio.run(exercise())


def test_feedback_rejected_stores_and_queries_successfully() -> None:
    async def exercise() -> None:
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
                    "operator_id": "ops_expert_01",
                    "reason": "Topology confirmed these devices belong to the same optical link",
                }
                resp = await client.post(
                    f"/api/v1/review-jobs/{job_id}/feedback",
                    json=submission_payload,
                )
                assert resp.status_code == 201
                body = resp.json()
                assert body["feedback_id"].startswith("fb_")
                assert body["job_id"] == job_id
                assert body["candidate_id"] == candidate_id
                assert body["decision"] == "REJECTED"
                assert body["operator_id"] == "ops_expert_01"
                assert body["reason"] == "Topology confirmed these devices belong to the same optical link"
                assert body["mutation_dispatched"] is False

                # Query job feedback
                get_job_fb = await client.get(f"/api/v1/review-jobs/{job_id}/feedback")
                assert get_job_fb.status_code == 200
                job_records = get_job_fb.json()
                assert len(job_records) == 1
                assert job_records[0]["candidate_id"] == candidate_id
                assert job_records[0]["decision"] == "REJECTED"

                # Query chain feedback
                chain_id = body["chain_id"]
                get_chain_fb = await client.get(f"/api/v1/chains/{chain_id}/feedback")
                assert get_chain_fb.status_code == 200
                chain_records = get_chain_fb.json()
                assert len(chain_records) == 1
                assert chain_records[0]["candidate_id"] == candidate_id
        finally:
            ws.close()

    asyncio.run(exercise())


def test_feedback_approved_with_auto_apply_dispatches_mutation() -> None:
    async def exercise() -> None:
        ws, job_id, candidate_id = _setup_workspace_with_evaluated_review()
        app = create_app(workspace=ws)
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                mock_response = MagicMock()
                mock_response.status = 200
                mock_response.read.return_value = b'{"ok": true, "status": "MUTATION_RECORDED_BY_NOCPRO"}'
                mock_response.__enter__.return_value = mock_response

                with patch(
                    "urllib.request.urlopen", return_value=mock_response
                ), patch.dict(
                    "os.environ",
                    {"NOCPRO_MUTATION_WEBHOOK_URL": "http://nocpro.viettel.internal/webhook"},
                ):
                    submission_payload = {
                        "candidate_id": candidate_id,
                        "decision": "APPROVED",
                        "operator_id": "noc_director",
                        "reason": "Split approved to separate unrelated fault domains",
                        "auto_apply": True,
                    }
                    resp = await client.post(
                        f"/api/v1/review-jobs/{job_id}/feedback",
                        json=submission_payload,
                    )
                    assert resp.status_code == 201
                    body = resp.json()
                    assert body["decision"] == "APPROVED"
                    assert body["mutation_dispatched"] is True
                    assert body["mutation_dispatch_result"]["status_code"] == 200
                    assert body["mutation_dispatch_result"]["response"]["ok"] is True
        finally:
            ws.close()

    asyncio.run(exercise())
