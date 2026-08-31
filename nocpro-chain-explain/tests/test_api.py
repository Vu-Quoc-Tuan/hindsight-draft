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
                    "source_version": "v17",
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
    assert {item["source_id"] for item in dependencies} == {"inventory"}
    assert {item["source_version"] for item in dependencies} == {"v17"}
    assert {item["scenario_id"] for item in dependencies} == {None}
    assert {item["generator_version"] for item in dependencies} == {None}


def test_pair_why_keeps_snapshot_available_but_disables_unversioned_topology():
    payload = _payload()
    payload["snapshot"]["topology_version"] = "must-not-be-a-fallback"
    payload["topology"] = {
        "active_paths": [
            {
                "path_id": "p-a",
                "resource_id": "RA",
                "nodes": ["RA", "ROOT"],
                "source_id": "foreign-topology",
                "source_kind": "REAL_EXPORT_REPLAY",
            }
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
        loaded = await client.post("/api/v1/snapshots", json=payload)
        assert loaded.status_code == 201
        return await client.get("/api/v1/chains/C1/pairs/a1/a2")

    response = run_api_test(exercise)

    assert response.status_code == 200
    active_path = next(
        item
        for item in response.json()["evidence"]
        if item["dependency_semantic"] == "SHARED_ACTIVE_PATH"
    )
    assert active_path["state"] == "UNAVAILABLE"
    assert active_path["detail"] == "TOPOLOGY_SOURCE_VERSION_MISSING"
    assert active_path["source_version"] is None


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
    assert polled.json()["result"]["similarity_status"] == "UNAVAILABLE"
    assert polled.json()["result"]["similarity_model_version"] is None
    assert polled.json()["result"]["similarity_trained_until_exclusive"] is None
    assert polled.json()["result"]["similarity_corpus_policy"] is None
    assert polled.json()["result"]["similarity_model_update_policy"] is None
    topology = polled.json()["result"]["topology_hypotheses"]
    assert topology["dominator"]["status"] == "UNAVAILABLE"
    assert topology["dominator"]["reason"] is not None
    assert "positive_score" not in topology["dominator"]
    assert topology["propagation"]["status"] == "UNAVAILABLE"
    assert topology["propagation"]["reason"] == "PROPAGATION_CONFIG_INCOMPLETE"
    assert topology["dependency_scope"]["status"] == "UNAVAILABLE"
    assert topology["dependency_scope"]["resource_details"]["missing_resources"] is None
    assert topology["dependency_scope"]["resource_details"]["extra_resources"] is None
