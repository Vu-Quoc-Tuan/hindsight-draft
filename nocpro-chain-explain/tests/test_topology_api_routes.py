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
            "p2_mapping_eligible": False,
            "dependency_semantics": "UNVERIFIED",
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
    assert data["p2_mapping_eligible"] is False
    assert data["dependency_semantics"] == "UNVERIFIED"
