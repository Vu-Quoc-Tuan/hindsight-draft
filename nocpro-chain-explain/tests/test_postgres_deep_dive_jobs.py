from __future__ import annotations

import asyncio
from copy import deepcopy
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete

from nocpro_api.persistence import Database, SnapshotRepository
from nocpro_api.persistence.models import AuditArtifactRecord, DeepDiveJobRecord
from nocpro_api.serializers import job_view
from nocpro_api.workspace import Workspace
from tests.test_api import _payload as snapshot_payload


pytestmark = pytest.mark.postgres


def _job_payload(job_id: str, status: str, result=None) -> dict:
    return {
        "job_id": job_id,
        "snapshot_id": "s-deep-dive",
        "snapshot_version": "1",
        "chain_id": "C1",
        "cache_fingerprint": "a" * 64,
        "status": status,
        "progress_percent": 100 if status in {"SUCCEEDED", "FAILED"} else 20,
        "cache_hit": False,
        "result": result,
        "error": None,
    }


def test_deep_dive_result_round_trips_and_active_run_is_interrupted() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise() -> None:
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        succeeded_id = uuid4().hex
        running_id = uuid4().hex
        try:
            expected_result = {
                "chain_id": "C1",
                "component_status": {"audit": "AVAILABLE", "topology": "UNAVAILABLE"},
            }
            await repository.persist_deep_dive_job(
                _job_payload(succeeded_id, "SUCCEEDED", expected_result)
            )
            stored = await repository.deep_dive_job(succeeded_id)
            assert stored is not None
            assert stored.status == "SUCCEEDED"
            assert stored.result == expected_result

            await repository.persist_deep_dive_job(
                _job_payload(running_id, "RUNNING")
            )
            interrupted = await repository.deep_dive_job(
                running_id, interrupt_active=True
            )
            assert interrupted is not None
            assert interrupted.status == "INTERRUPTED"
            assert interrupted.error == "API_RESTART_INTERRUPTED"
        finally:
            async with database.sessions.begin() as session:
                await session.execute(
                    delete(DeepDiveJobRecord).where(
                        DeepDiveJobRecord.job_id.in_((succeeded_id, running_id))
                    )
                )
            await database.close()

    asyncio.run(exercise())


def test_workspace_listener_persists_and_rehydrates_full_deep_dive() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise() -> None:
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        identity = uuid4().hex
        payload = deepcopy(snapshot_payload())
        payload["snapshot"]["snapshot_id"] = f"deep-dive-{identity}"
        for alarm in payload["alarms"]:
            alarm["snapshot_id"] = payload["snapshot"]["snapshot_id"]
        for chain in payload["chains"]:
            chain["snapshot_id"] = payload["snapshot"]["snapshot_id"]
        for membership in payload["memberships"]:
            membership["snapshot_id"] = payload["snapshot"]["snapshot_id"]

        live = Workspace()
        restarted = Workspace()
        job_id = None
        try:
            live.attach_persistence(repository, object())
            live.replace_snapshot(payload)
            submission = live.submit_deep_dive("C1")
            job_id = submission.job_id
            for _ in range(80):
                view = live.jobs.get(job_id)
                if view.status.value in {"SUCCEEDED", "FAILED"}:
                    break
                await asyncio.sleep(0.01)
            assert view.status.value == "SUCCEEDED"
            await live.flush_deep_dive_persistence()
            await live.flush_audit_persistence()
            expected = job_view(view).model_dump(mode="json")

            restarted.replace_snapshot(payload)
            restarted.repository = repository
            hydrated = await restarted.latest_deep_dive("C1")
            assert hydrated is not None
            assert job_view(hydrated).model_dump(mode="json") == expected
        finally:
            live.close()
            await live.flush_deep_dive_persistence()
            await live.flush_audit_persistence()
            restarted.close()
            async with database.sessions.begin() as session:
                if job_id is not None:
                    await session.execute(
                        delete(DeepDiveJobRecord).where(
                            DeepDiveJobRecord.job_id == job_id
                        )
                    )
                await session.execute(
                    delete(AuditArtifactRecord).where(
                        AuditArtifactRecord.snapshot_id
                        == payload["snapshot"]["snapshot_id"]
                    )
                )
            await database.close()

    asyncio.run(exercise())
