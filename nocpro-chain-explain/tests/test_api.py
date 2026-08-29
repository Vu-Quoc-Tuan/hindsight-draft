"""HTTP boundary over Tier-1B and asynchronous Tier-2 services."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx2

from nocpro_api import create_app


T = TypeVar("T")


def run_api_test(test: Callable[[httpx2.AsyncClient], Awaitable[T]]) -> T:
    """Exercise ASGI in one event loop; the sandbox cannot wake cross-thread loops."""

    async def run() -> T:
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await test(client)
        finally:
            app.state.workspace.close()

    return asyncio.run(run())


def _payload() -> dict:
    alarms = [
        {
            "alarm_id": f"a{index}",
            "snapshot_id": "s1",
            "source_kind": "SYNTHETIC_TEST",
            "provenance_class": "SYSTEM_FACT",
            "raw": {"location_code": "SITE-A"},
            "alarm_name": "LINK DOWN",
            "device_code": "D1",
            "node_reference": "R1",
            "canonical_start_time": f"2026-01-01T00:00:0{index}",
        }
        for index in range(1, 4)
    ]
    return {
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": "s1",
            "snapshot_version": "1",
            "snapshot_time": "2026-01-01T00:00:00",
            "status": "COMPLETE",
            "source": "api-test",
            "source_kind": "SYNTHETIC_TEST",
            "produced_at": "2026-01-01T00:00:00",
        },
        "alarms": alarms,
        "chains": [
            {
                "chain_id": "C1",
                "snapshot_id": "s1",
                "member_count": 3,
                "source_kind": "SYNTHETIC_TEST",
                "provenance_class": "SYSTEM_FACT",
            }
        ],
        "memberships": [
            {
                "chain_id": "C1",
                "alarm_id": alarm["alarm_id"],
                "snapshot_id": "s1",
                "source_kind": "SYNTHETIC_TEST",
            }
            for alarm in alarms
        ],
    }


def test_workspace_requires_a_snapshot_before_analysis():
    async def exercise(client: httpx2.AsyncClient):
        return await client.get("/api/v1/chains")

    response = run_api_test(exercise)
    assert response.status_code == 409
    assert response.json()["detail"] == "no snapshot loaded"


def test_snapshot_ingest_lists_and_explains_chains():
    async def exercise(client: httpx2.AsyncClient):
        ingested = await client.post("/api/v1/snapshots", json=_payload())
        listed = await client.get("/api/v1/chains")
        explained = await client.get("/api/v1/chains/C1")
        return ingested, listed, explained

    ingested, listed, explained = run_api_test(exercise)

    assert ingested.status_code == 201
    assert ingested.json() == {
        "snapshot_id": "s1",
        "snapshot_version": "1",
        "alarm_count": 3,
        "chain_count": 1,
        "incremental_snapshot": {
            "mode": "disabled",
            "reason": "sequential_production_snapshots_not_available",
        },
    }
    assert listed.status_code == 200
    assert listed.json()["chains"][0]["chain_id"] == "C1"
    assert explained.status_code == 200
    body = explained.json()
    assert body["chain_id"] == "C1"
    assert body["member_count"] == 3
    assert body["audit_graph_mode"] == "NOT_COMPUTED"
    assert len(body["members"]) == 3
    assert body["members"][0]["role"] in {
        "CORE",
        "PERIPHERAL",
        "WEAK",
        "INSUFFICIENT_DATA",
    }
    assert body["descriptors"]


def test_pair_why_serializes_channel_family_and_dependency_semantic():
    payload = _payload()
    payload["snapshot"]["topology_version"] = "v17"
    payload["topology"] = {
            "edges": [
                {
                    "edge_id": f"edge-{resource}",
                    "source_resource_id": "ROOT",
                    "target_resource_id": resource,
                    "relation_type": "LOGICAL_DEPENDENCY",
                    "directed": True,
                    "source_id": "inventory",
                    "source_kind": "REAL_EXPORT_REPLAY",
                    "source_version": "v17",
                }
            for resource in ("RA", "RB")
        ],
        "active_paths": [
            {
                "path_id": f"p-{resource}",
                "resource_id": resource,
                    "nodes": [resource, "ROOT"],
                    "source_id": "inventory",
                    "source_kind": "REAL_EXPORT_REPLAY",
            }
            for resource in ("RA", "RB")
        ],
        "mappings": [
                {
                    "alarm_id": "a1",
                    "resource_id": "RA",
                    "mapping_status": "EXACT",
                    "mapping_method": "EXACT_IDENTITY",
                },
                {
                    "alarm_id": "a2",
                    "resource_id": "RB",
                    "mapping_status": "EXACT",
                    "mapping_method": "EXACT_IDENTITY",
                },
        ],
    }

    async def exercise(client: httpx2.AsyncClient):
        await client.post("/api/v1/snapshots", json=payload)
        return await client.get("/api/v1/chains/C1/pairs/a1/a2")

    response = run_api_test(exercise)

    assert response.status_code == 200
    dependencies = [
        item
        for item in response.json()["evidence"]
        if item["channel_family"] == "DEP_UPSTREAM"
    ]
    assert {item["dependency_semantic"] for item in dependencies} == {
        "SHARED_ANCESTOR",
        "SHARED_ACTIVE_PATH",
    }
    assert {item["derivation_tag"] for item in dependencies} == {
        "dependency:inventory@v17"
    }


def test_deep_dive_is_submitted_and_polled_as_a_job():
    async def exercise(client: httpx2.AsyncClient):
        await client.post("/api/v1/snapshots", json=_payload())
        submission = await client.post("/api/v1/chains/C1/deep-dive")
        assert submission.status_code == 202
        job_id = submission.json()["job_id"]
        polled = await client.get(f"/api/v1/jobs/{job_id}")
        for _ in range(20):
            if polled.json()["status"] in {"SUCCEEDED", "FAILED"}:
                break
            await asyncio.sleep(0.01)
            polled = await client.get(f"/api/v1/jobs/{job_id}")
        return polled

    polled = run_api_test(exercise)

    assert polled.status_code == 200
    assert polled.json()["status"] == "SUCCEEDED"
    assert polled.json()["result"]["chain_id"] == "C1"
    assert polled.json()["result"]["audit_graph_mode"] == "EXACT_FULL"
