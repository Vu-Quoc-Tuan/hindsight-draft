from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx2

from nocpro_api import create_app
from tests.test_api import _payload


async def _poll(client: httpx2.AsyncClient, job_id: str) -> dict:
    for _ in range(100):
        response = await client.get(f"/api/v1/review-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in {"SUCCEEDED", "FAILED"}:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("Counterfactual review did not finish")


def test_review_submit_poll_and_compatible_lookup() -> None:
    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                loaded = await client.post("/api/v1/snapshots", json=_payload())
                assert loaded.status_code == 201

                absent = await client.get("/api/v1/chains/C1/review")
                assert absent.status_code == 404

                submission = await client.post("/api/v1/chains/C1/review")
                assert submission.status_code == 202
                job_id = submission.json()["job_id"]
                completed = await _poll(client, job_id)

                assert completed["status"] == "SUCCEEDED"
                assert completed["identity"]["snapshot_id"] == "s1"
                assert completed["identity"]["snapshot_version"] == "1"
                assert completed["result"]["status"] == "UNAVAILABLE"
                assert completed["result"]["contract_version"] == "counterfactual-review-v1"
                assert completed["result"]["calibration_status"] is None
                assert (
                    completed["result"]["reason"]
                    == "COUNTERFACTUAL_CONFIG_INCOMPLETE"
                )
                operations = completed["result"]["operation_status"]
                assert operations["REMOVE_MEMBER"]["status"] == "UNAVAILABLE"
                assert operations["SPLIT_CHAIN"]["status"] == "UNAVAILABLE"
                assert operations["MOVE_MEMBER"]["status"] == "UNAVAILABLE"
                assert operations["MERGE_CHAINS"]["status"] == "UNAVAILABLE"
                assert operations["ADD_MEMBER"] == {
                    "status": "BLOCKED",
                    "reason": "UNKNOWN_UPSTREAM_SEMANTICS",
                    "search_mode": "NOT_RUN",
                    "candidate_count": 0,
                    "evaluated_count": 0,
                    "ceiling": None,
                }

                latest = await client.get("/api/v1/chains/C1/review")
                assert latest.status_code == 200
                assert latest.json()["job_id"] == job_id
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_review_routes_keep_unknown_resources_explicit() -> None:
    async def exercise() -> None:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                await client.post("/api/v1/snapshots", json=_payload())
                unknown_chain = await client.post(
                    "/api/v1/chains/UNKNOWN/review"
                )
                unknown_job = await client.get(
                    "/api/v1/review-jobs/UNKNOWN"
                )
                assert unknown_chain.status_code == 404
                assert unknown_job.status_code == 404
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_review_reads_flush_pending_persistence_before_responding() -> None:
    async def exercise() -> None:
        app = create_app()
        app.state.workspace.flush_review_persistence = AsyncMock()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get("/api/v1/review-jobs/UNKNOWN")
                assert response.status_code == 404
                app.state.workspace.flush_review_persistence.assert_awaited_once()
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())
