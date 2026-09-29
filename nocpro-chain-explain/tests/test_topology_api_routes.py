"""Unit tests for /api/v1/topology REST routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from fastapi import FastAPI

from nocpro_api.routes import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    repo = MagicMock()
    repo.list_profiles = AsyncMock(return_value=["ALARM_ONLY", "IP_NETWORK", "IT_SERVICES"])
    repo.get_projection = AsyncMock(
        return_value={
            "status": "AVAILABLE",
            "profile": "IT_SERVICES",
            "dataset_profile": "IT_SERVICES",
            "topology_kind": "DIRECTED_SOURCE_RELATIONS",
            "direction_kind": "SOURCE_RELATION",
            "dependency_semantics": "UNVERIFIED",
            "topology": {
                "availability": "AVAILABLE",
                "relation_model": "DIRECTED_SOURCE_RELATIONS",
                "direction_kind": "SOURCE_RELATION",
                "dependency_semantics": "UNVERIFIED",
                "navigation_mapping": "PARTIAL_SOURCE_FIELD_EXACT",
                "alarm_resource_mapping": "UNAVAILABLE",
            },
            "semantic_notice": "Navigation notice",
            "source_version": "sha256:abc",
            "tree": {
                "resource_id": "svc1",
                "resource_type": "SERVICE",
                "display_name": "Order Service",
                "children": [],
                "hidden_child_count": 0,
                "reference_kind": None,
                "linked_parent_count": 0,
            },
        }
    )
    repo.search_nodes = AsyncMock(
        return_value={
            "status": "AVAILABLE",
            "dataset_profile": "IT_SERVICES",
            "results": [
                {"resource_id": "svc1", "resource_type": "SERVICE", "display_name": "Order Service"}
            ],
        }
    )
    repo.resolve_identifier = AsyncMock(
        return_value={
            "status": "AVAILABLE",
            "dataset_profile": "IT_SERVICES",
            "identifier": "order-srv",
            "resource_id": "svc1",
            "mapping_status": "UNIQUE_SOURCE_FIELD_MATCH",
            "source_field": "service_name",
            "navigation_eligible": True,
            "dependency_semantics": "UNVERIFIED",
        }
    )
    repo.get_subgraph = AsyncMock(
        return_value={
            "status": "AVAILABLE",
            "profile_id": "IT_SERVICES",
            "topology_version": "v1",
            "nodes": [
                {"id": "svc1", "name": "Order Service", "type": "SERVICE", "is_seed": False},
                {"id": "host1", "name": "10.210.48.136", "type": "INSTANCE", "is_seed": True},
            ],
            "edges": [
                {"id": "edge-1", "source": "svc1", "target": "host1", "relation": "SERVICE_HAS_MODULE"},
            ],
        }
    )
    app.state.topology_repository = repo
    return app


async def _get(app: FastAPI, path: str) -> httpx2.Response:
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.get(path)


@pytest.mark.anyio
async def test_topology_profiles(app: FastAPI):
    res = await _get(app, "/api/v1/topology/profiles")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "AVAILABLE"
    assert "IT_SERVICES" in data["profiles"]
    assert "IP_NETWORK" in data["profiles"]
    assert "ALARM_ONLY" in data["profiles"]


@pytest.mark.anyio
async def test_topology_projection(app: FastAPI):
    res = await _get(app, "/api/v1/topology/projection?profile_id=IT_SERVICES&root_id=svc1")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "AVAILABLE"
    assert data["profile"] == "IT_SERVICES"
    assert data["direction_kind"] == "SOURCE_RELATION"
    assert data["dependency_semantics"] == "UNVERIFIED"
    assert data["tree"]["resource_id"] == "svc1"


@pytest.mark.anyio
async def test_topology_search(app: FastAPI):
    res = await _get(app, "/api/v1/topology/search?profile_id=IT_SERVICES&q=Order")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "AVAILABLE"
    assert len(data["results"]) == 1
    assert data["results"][0]["resource_id"] == "svc1"


@pytest.mark.anyio
async def test_topology_resolve(app: FastAPI):
    res = await _get(app, "/api/v1/topology/resolve?profile_id=IT_SERVICES&identifier=order-srv")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "AVAILABLE"
    assert data["resource_id"] == "svc1"
    assert data["dependency_semantics"] == "UNVERIFIED"


@pytest.mark.anyio
async def test_topology_subgraph(app: FastAPI):
    res = await _get(app, "/api/v1/topology/subgraph?profile_id=IT_SERVICES&seeds=10.210.48.136&hops=2")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "AVAILABLE"
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    assert data["nodes"][1]["is_seed"] is True


@pytest.mark.anyio
async def test_topology_subgraph_accepts_four_hops_and_pins_version(app: FastAPI):
    res = await _get(
        app,
        "/api/v1/topology/subgraph?profile_id=IT_SERVICES&seeds=host1&hops=4&version=v1",
    )

    assert res.status_code == 200
    app.state.topology_repository.get_subgraph.assert_awaited_once_with(
        "IT_SERVICES", seeds=["host1"], max_hops=4, max_nodes=150, topology_version="v1"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("hops", [0, 5])
async def test_topology_subgraph_rejects_hops_outside_supported_range(app: FastAPI, hops: int):
    res = await _get(
        app,
        f"/api/v1/topology/subgraph?profile_id=IT_SERVICES&seeds=10.210.48.136&hops={hops}",
    )

    assert res.status_code == 422
    app.state.topology_repository.get_subgraph.assert_not_awaited()
