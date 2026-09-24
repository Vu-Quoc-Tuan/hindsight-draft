"""HTTP boundary over Tier-1B and asynchronous Tier-2 services."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable
from hashlib import sha256
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing import TypeVar

import httpx2
from contracts.v1.enums import MappingMethod, MappingStatus
from contracts.v1.models import AlarmEntityResolution

from nocpro_api import create_app
import nocpro_api.routes as api_routes
from nocpro_api.workspace import Workspace
from nocpro_api.persistence import (
    IngestResult,
    StoredEvolution,
    StoredEvolutionEdge,
    StoredEvolutionNode,
)
from nocpro_api.serializers import evolution_view
from tier2 import audit_artifact_from_dict, audit_artifact_to_dict


T = TypeVar("T")


def run_api_test(test: Callable[[httpx2.AsyncClient], Awaitable[T]], *, workspace: Workspace | None = None) -> T:
    """Exercise ASGI in one event loop; the sandbox cannot wake cross-thread loops."""

    async def run() -> T:
        app = create_app(workspace=workspace)
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
    assert listed.json()["chains"][0] == {
        "chain_id": "C1",
        "member_count": 3,
        "is_singleton": False,
        "title": listed.json()["chains"][0]["title"],
        "start_time": "2026-01-01T00:00:01",
        "end_time": "2026-01-01T00:00:03",
        "duration_seconds": 2.0,
    }
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


def test_chain_analysis_does_not_infer_topology_profile_from_snapshot_name(monkeypatch):
    payload = _payload()
    payload["snapshot"]["snapshot_id"] = "quip-demo"
    for row in payload["alarms"] + payload["chains"] + payload["memberships"]:
        row["snapshot_id"] = "quip-demo"
    workspace = Workspace()
    workspace.replace_snapshot(payload)
    topology_repository = SimpleNamespace(
        get_active_version=AsyncMock(
            return_value=SimpleNamespace(topology_version="ip-active-v1")
        ),
        get_alarm_entity_resolutions=AsyncMock(return_value=[]),
        get_host_modules_map=AsyncMock(return_value=({}, {})),
        save_alarm_entity_resolutions=AsyncMock(),
    )
    monkeypatch.setattr(
        api_routes, "topology_repo", lambda _request: topology_repository
    )

    async def exercise(client: httpx2.AsyncClient):
        return await client.get("/api/v1/chains/C1")

    response = run_api_test(exercise, workspace=workspace)

    assert response.status_code == 200
    resolutions = [
        resolution
        for member in response.json()["members"]
        for resolution in member["entity_resolutions"]
    ]
    assert len(resolutions) == 3
    assert all(
        resolution["topology_profile_id"] is None for resolution in resolutions
    )
    topology_repository.get_active_version.assert_not_awaited()
    topology_repository.get_alarm_entity_resolutions.assert_not_awaited()
    topology_repository.get_host_modules_map.assert_not_awaited()
    topology_repository.save_alarm_entity_resolutions.assert_not_awaited()


def test_chain_analysis_skips_topology_map_when_persisted_resolutions_cover_chain(
    monkeypatch,
):
    payload = _payload()
    payload["snapshot"]["topology_ref"] = {
        "profile_id": "IT_SERVICES",
        "topology_version": "it-v1",
    }
    workspace = Workspace()
    workspace.replace_snapshot(payload)
    persisted = [
        AlarmEntityResolution(
            alarm_id=f"a{index}",
            entity_role="OBSERVED_HOST",
            raw_value="D1",
            status=MappingStatus.UNMAPPED,
            method=MappingMethod.NONE,
            topology_profile_id="IT_SERVICES",
            topology_version="it-v1",
        )
        for index in range(1, 4)
    ]
    topology_repository = SimpleNamespace(
        get_active_version=AsyncMock(),
        get_alarm_entity_resolutions=AsyncMock(return_value=persisted),
        get_host_modules_map=AsyncMock(side_effect=AssertionError("map must not load")),
        save_alarm_entity_resolutions=AsyncMock(),
    )
    monkeypatch.setattr(
        api_routes, "topology_repo", lambda _request: topology_repository
    )
    monkeypatch.setattr(
        api_routes.AlarmEntityResolver,
        "from_package",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fully persisted chain must not rebuild a package resolver")
        ),
    )

    async def exercise(client: httpx2.AsyncClient):
        return await client.get("/api/v1/chains/C1")

    response = run_api_test(exercise, workspace=workspace)

    assert response.status_code == 200
    topology_repository.get_active_version.assert_not_awaited()
    topology_repository.get_alarm_entity_resolutions.assert_awaited_once_with(
        ["a1", "a2", "a3"], "IT_SERVICES", "it-v1"
    )
    topology_repository.get_host_modules_map.assert_not_awaited()
    topology_repository.save_alarm_entity_resolutions.assert_not_awaited()


def test_chain_analysis_loads_topology_map_only_for_unpersisted_alarms(monkeypatch):
    payload = _payload()
    payload["snapshot"]["topology_ref"] = {
        "profile_id": "IT_SERVICES",
        "topology_version": "it-v1",
    }
    workspace = Workspace()
    workspace.replace_snapshot(payload)
    persisted = [
        AlarmEntityResolution(
            alarm_id="a1",
            entity_role="OBSERVED_HOST",
            raw_value="D1",
            status=MappingStatus.UNMAPPED,
            method=MappingMethod.NONE,
            topology_profile_id="IT_SERVICES",
            topology_version="it-v1",
        )
    ]
    topology_repository = SimpleNamespace(
        get_active_version=AsyncMock(),
        get_alarm_entity_resolutions=AsyncMock(return_value=persisted),
        get_host_modules_map=AsyncMock(return_value=({}, {})),
        save_alarm_entity_resolutions=AsyncMock(),
    )
    monkeypatch.setattr(
        api_routes, "topology_repo", lambda _request: topology_repository
    )

    async def exercise(client: httpx2.AsyncClient):
        return await client.get("/api/v1/chains/C1")

    response = run_api_test(exercise, workspace=workspace)

    assert response.status_code == 200
    topology_repository.get_active_version.assert_not_awaited()
    topology_repository.get_alarm_entity_resolutions.assert_awaited_once_with(
        ["a1", "a2", "a3"], "IT_SERVICES", "it-v1"
    )
    topology_repository.get_host_modules_map.assert_awaited_once_with(
        "IT_SERVICES", topology_version="it-v1"
    )
    saved = topology_repository.save_alarm_entity_resolutions.await_args.args[0]
    assert {resolution.alarm_id for resolution in saved} == {"a2", "a3"}


def test_chain_overview_cards_reads_persisted_projection_without_provider():
    workspace = Workspace()
    workspace.replace_snapshot(_payload())
    repository = SimpleNamespace(
        chain_quality_assessment=AsyncMock(
            return_value=SimpleNamespace(
                status="EVALUATED",
                stars=4,
                input_fingerprint="fp-1",
                payload={
                    "method": "HEURISTIC_V1",
                    "status": "EVALUATED",
                    "stars": 4,
                    "label": "Khá vững",
                    "overview_projection": {
                            "projection_version": "CHAIN_OVERVIEW_V3",
                            "pipeline_version": "DETERMINISTIC_QUALITY_V3",
                            "snapshot_id": "s1",
                            "snapshot_version": "1",
                            "topology_version": "topology-1",
                            "config_version": workspace.config.config_version,
                            "input_fingerprint": "fp-1",
                        "representative_member": {
                            "status": "AVAILABLE",
                            "alarm_id": "a1",
                            "alarm_name": "LINK DOWN",
                            "device_code": "D1",
                            "role": "CORE",
                        },
                        "topology": {
                            "mapped_device_count": 1,
                            "total_device_count": 1,
                            "device_mapping_ratio": 1,
                            "connected_pair_count": 1,
                            "pair_total": 1,
                            "mapped_resources": ["R1", "R2"],
                            "display_paths_truncated": False,
                            "display_paths": [{
                                "source": "R1",
                                "target": "R2",
                                "source_devices": ["D1"],
                                "target_devices": ["D2"],
                                "hop_count": 1,
                                "path": ["R1", "R2"],
                                "relation_type": "IP_ADJACENCY",
                                "traversal_semantic": "UNDIRECTED_STRUCTURAL_CONNECTIVITY",
                            }],
                        },
                        "quality_assessment": {
                            "method": "HEURISTIC_V1",
                            "status": "EVALUATED",
                            "stars": 4,
                            "label": "Khá vững",
                            "reasons": [],
                            "available_dimension_count": 5,
                        },
                        "recommendations": {
                            "status": "AVAILABLE",
                            "count": 0,
                            "split_recommended": False,
                        },
                    },
                },
            )
        )
    )
    workspace.repository = repository

    async def exercise(client: httpx2.AsyncClient):
        response = await client.get("/api/v1/chains/C1/overview-cards")
        return response

    response = run_api_test(exercise, workspace=workspace)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY"
    assert body["representative_member"]["alarm_id"] == "a1"
    assert body["topology"]["mapped_device_count"] == 1
    assert body["topology_version"] == "topology-1"
    assert body["topology"]["display_paths"][0]["path"] == ["R1", "R2"]
    assert body["topology"]["display_paths_truncated"] is False
    repository.chain_quality_assessment.assert_awaited_once()


def test_chain_overview_cards_reports_pending_without_projection():
    workspace = Workspace()
    workspace.replace_snapshot(_payload())
    workspace.repository = SimpleNamespace(
        chain_quality_assessment=AsyncMock(
            return_value=SimpleNamespace(status="EVALUATED", stars=4, payload={})
        )
    )

    async def exercise(client: httpx2.AsyncClient):
        return await client.get("/api/v1/chains/C1/overview-cards")

    response = run_api_test(exercise, workspace=workspace)
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"
    assert response.json()["reason"] == "DETERMINISTIC_OVERVIEW_PROJECTION_PENDING"


def test_selecting_the_active_snapshot_is_a_noop():
    workspace = Workspace()
    workspace.replace_snapshot(_payload())
    workspace.ingest_snapshot = AsyncMock(side_effect=AssertionError("must not ingest active snapshot"))

    async def exercise(client: httpx2.AsyncClient):
        return await client.post("/api/v1/snapshots/select", json={"snapshot_id": "s1"})

    response = run_api_test(exercise, workspace=workspace)
    assert response.status_code == 200
    assert response.json()["snapshot_id"] == "s1"
    assert response.json()["snapshot_version"] == "1"
    workspace.ingest_snapshot.assert_not_awaited()


def test_workspace_promotes_exact_prepared_activation_without_recomputing():
    """A background-prepared exact payload is promoted without a cold parse."""
    payload = _payload()
    prepared_payload = copy.deepcopy(payload)
    def rewrite_snapshot_identity(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "snapshot_id":
                    value[key] = "s2"
                elif key == "snapshot_version":
                    value[key] = "2"
                else:
                    rewrite_snapshot_identity(child)
        elif isinstance(value, list):
            for child in value:
                rewrite_snapshot_identity(child)

    rewrite_snapshot_identity(prepared_payload)

    workspace = Workspace()
    workspace.replace_snapshot(payload)
    prepared_package, prepared_result = workspace.compute_snapshot(prepared_payload)
    workspace.store_prepared_activation(
        prepared_payload,
        prepared_package,
        prepared_result,
        config_version=workspace.config.config_version,
    )

    class Repository:
        async def ingest_direct(self, incoming):
            snapshot = incoming["snapshot"]
            return IngestResult(
                snapshot["snapshot_id"],
                snapshot["snapshot_version"],
                "COMPLETE",
                duplicate=True,
                completed_now=False,
            )

    workspace.repository = Repository()
    workspace.coordinator = SimpleNamespace()
    workspace.compute_snapshot = lambda _payload: (_ for _ in ()).throw(
        AssertionError("prepared activation must not recompute")
    )

    async def exercise():
        result = await workspace.ingest_snapshot(prepared_payload)
        assert result is prepared_result
        assert workspace.active_identity() == ("s2", "2")

    try:
        asyncio.run(exercise())
    finally:
        workspace.close()


def test_workspace_activates_an_already_persisted_snapshot_on_explicit_selection():
    """Catalog selection must not fail merely because its payload was persisted earlier.

    This is the normal dev-demo state: Kafka/startup may have activated another
    snapshot, while a catalog preset already exists as a READY durable row.
    """

    class PersistedRepository:
        async def ingest_direct(self, payload: dict):
            package = payload["snapshot"]
            return IngestResult(
                package["snapshot_id"],
                package["snapshot_version"],
                "COMPLETE",
                duplicate=True,
                completed_now=False,
            )

    class Coordinator:
        async def run(self, snapshot_id: str, snapshot_version: str):
            raise AssertionError("a duplicate persisted snapshot must not be re-claimed")

    async def exercise():
        workspace = Workspace()
        try:
            workspace.replace_snapshot(_payload())
            selected = _payload()
            selected["snapshot"] = {
                **selected["snapshot"],
                "snapshot_id": "catalog-persisted",
            }
            for alarm in selected["alarms"]:
                alarm["snapshot_id"] = "catalog-persisted"
            for chain in selected["chains"]:
                chain["snapshot_id"] = "catalog-persisted"
            for membership in selected["memberships"]:
                membership["snapshot_id"] = "catalog-persisted"

            workspace.repository = PersistedRepository()
            workspace.coordinator = Coordinator()

            result = await workspace.ingest_snapshot(selected)

            assert result.snapshot_id == "catalog-persisted"
            assert workspace.require_package().snapshot.snapshot_id == "catalog-persisted"
        finally:
            workspace.close()

    asyncio.run(exercise())


def test_select_snapshot_falls_back_to_repository_live_snapshot():
    """Live snapshots pushed through Kafka without a local preset file can be selected."""

    class MockRepo:
        def __init__(self):
            payload = _payload()
            payload["snapshot"]["snapshot_id"] = "live_kafka_snap_001"
            for alarm in payload["alarms"]:
                alarm["snapshot_id"] = "live_kafka_snap_001"
            for chain in payload["chains"]:
                chain["snapshot_id"] = "live_kafka_snap_001"
            for membership in payload["memberships"]:
                membership["snapshot_id"] = "live_kafka_snap_001"
            self.live_payload = payload

        async def get_ready_snapshot_payload(self, snapshot_id: str):
            if snapshot_id == "live_kafka_snap_001":
                return self.live_payload
            return None

        async def ingest_direct(self, payload: dict):
            pkg = payload["snapshot"]
            return IngestResult(pkg["snapshot_id"], pkg["snapshot_version"], "COMPLETE", duplicate=True, completed_now=False)

    class MockCoord:
        async def run(self, *args):
            return None

    ws = Workspace()
    ws.repository = MockRepo()
    ws.coordinator = MockCoord()

    async def exercise(client: httpx2.AsyncClient):
        selected = await client.post(
            "/api/v1/snapshots/select",
            json={"snapshot_id": "live_kafka_snap_001"},
        )
        return selected

    response = run_api_test(exercise, workspace=ws)
    assert response.status_code == 200
    assert response.json()["snapshot_id"] == "live_kafka_snap_001"


def test_configured_initial_snapshot_overrides_a_stale_startup_snapshot(
    monkeypatch,
):
    """Demo startup must activate its configured full replay, not Kafka's last row."""

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("KAFKA_ENABLED", "false")
    monkeypatch.setenv("NOCPRO_INITIAL_SNAPSHOT_ID", "real_alarm_ip_demo")

    async def exercise():
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        try:
            async with app.router.lifespan_context(app):
                async with httpx2.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    response = await client.get("/api/v1/chains")
            assert response.status_code == 200
            payload = response.json()
            assert payload["snapshot_id"] == "real_alarm_ip_demo"
            assert len(payload["chains"]) == 258
        finally:
            app.state.workspace.close()

    asyncio.run(exercise())


def test_configured_initial_snapshot_is_activated_before_recovery_worker(
    monkeypatch,
):
    app_module = importlib.import_module("nocpro_api.app")
    events: list[str] = []

    class FakeDatabase:
        def __init__(self, _url: str):
            self.sessions = object()

        async def close(self):
            return None

    class FakeRepository:
        def __init__(self, _sessions, **_kwargs):
            return None

    class FakeTopologyRepository:
        def __init__(self, _sessions):
            return None

    class FakeCoordinator:
        def __init__(self, repository, _service, **_kwargs):
            self.repository = repository

        async def hydrate_active(self):
            return None

    class FakeWorkspace:
        def __init__(self):
            self.package = None
            self.config = SimpleNamespace(
                chunk_retention=SimpleNamespace(mode="KEEP")
            )

        def attach_persistence(self, _repository, _coordinator):
            return None

        async def ingest_snapshot(self, _payload):
            await asyncio.sleep(0)
            events.append("activate_initial_snapshot")

        def close(self):
            return None

        async def flush_review_persistence(self):
            return None

        async def flush_deep_dive_persistence(self):
            return None

        async def flush_audit_persistence(self):
            return None

    async def fake_recovery_loop(*_args, **_kwargs):
        events.append("start_recovery")
        await asyncio.Event().wait()

    monkeypatch.setattr(app_module, "Database", FakeDatabase)
    monkeypatch.setattr(app_module, "SnapshotRepository", FakeRepository)
    monkeypatch.setattr(app_module, "TopologyRepository", FakeTopologyRepository)
    monkeypatch.setattr(app_module, "Tier1ACoordinator", FakeCoordinator)
    monkeypatch.setattr(app_module, "_recovery_loop", fake_recovery_loop)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test")
    monkeypatch.setenv("KAFKA_ENABLED", "false")
    monkeypatch.setenv("AUTO_CALIBRATE_ON_STARTUP", "false")
    monkeypatch.setenv("NOCPRO_INITIAL_SNAPSHOT_ID", "real_alarm_ip_demo")

    async def exercise():
        app = create_app(workspace=FakeWorkspace())
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

    asyncio.run(exercise())

    assert events == ["activate_initial_snapshot", "start_recovery"]


def test_evolution_is_unavailable_for_a_single_direct_snapshot():
    async def exercise(client: httpx2.AsyncClient):
        await client.post("/api/v1/snapshots", json=_payload())
        return await client.get("/api/v1/chains/C1/evolution")

    response = run_api_test(exercise)

    assert response.status_code == 200
    assert response.json() == {
        "status": "UNAVAILABLE",
        "reason": "SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE",
        "source_kind": "SYNTHETIC_TEST",
        "sequence_status": "UNAVAILABLE",
        "production_validation": "NOT_ESTABLISHED",
        "lineage_component_id": None,
        "branch_id": None,
        "snapshot_id": "s1",
        "snapshot_version": "1",
        "chain_id": "C1",
        "nodes": [],
        "edges": [],
    }


def test_evolution_serializer_keeps_verified_synthetic_artifact_provenance():
    from datetime import datetime, timezone

    result = evolution_view(
        StoredEvolution(
            status="AVAILABLE",
            reason=None,
            source_kind="SYNTHETIC_TEST",
            sequence_status="VERIFIED",
            production_validation="NOT_ESTABLISHED",
            lineage_component_id="lc-test",
            branch_id="lc-test:b0",
            snapshot_id="s2",
            snapshot_version="2",
            chain_id="C2",
            nodes=(
                StoredEvolutionNode(
                    snapshot_id="s1",
                    snapshot_version="1",
                    chain_id="C1",
                    snapshot_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    lineage_component_id="lc-test",
                    branch_id="lc-test:b0",
                    source_kind="SYNTHETIC_TEST",
                ),
                StoredEvolutionNode(
                    snapshot_id="s2",
                    snapshot_version="2",
                    chain_id="C2",
                    snapshot_time=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
                    lineage_component_id="lc-test",
                    branch_id="lc-test:b0",
                    source_kind="SYNTHETIC_TEST",
                ),
            ),
            edges=(
                StoredEvolutionEdge(
                    parent_snapshot_id="s1",
                    parent_snapshot_version="1",
                    parent_chain_id="C1",
                    child_snapshot_id="s2",
                    child_snapshot_version="2",
                    child_chain_id="C2",
                    event_type="CONTINUE",
                    overlap_count=3,
                    contain_parent=1.0,
                    contain_child=1.0,
                ),
            ),
        )
    )

    assert result.status == "AVAILABLE"
    assert result.source_kind == "SYNTHETIC_TEST"
    assert result.production_validation == "NOT_ESTABLISHED"
    assert result.edges[0].event_type == "CONTINUE"
    assert result.edges[0].overlap_count == 3


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


def test_pair_why_exposes_history_as_config_incomplete_without_changing_other_channels():
    async def exercise(client: httpx2.AsyncClient):
        loaded = await client.post("/api/v1/snapshots", json=_payload())
        assert loaded.status_code == 201
        return await client.get("/api/v1/chains/C1/pairs/a1/a2")

    response = run_api_test(exercise)

    assert response.status_code == 200
    history = next(
        item for item in response.json()["evidence"] if item["channel_family"] == "H"
    )
    assert history["state"] == "UNAVAILABLE"
    assert history["detail"] == "HISTORY_CONFIG_INCOMPLETE"
    assert history["threshold"] is None
    assert history["provenance_class"] == "BEHAVIORAL"
    delay = next(
        item
        for item in response.json()["evidence"]
        if item["channel_family"] == "T_delay"
    )
    # The production baseline carries neither the complete frozen DelayModel
    # policy nor authoritative taxonomy.  Existing TimeWindow metadata must
    # not silently make learned T_delay available.
    assert delay["state"] == "UNAVAILABLE"
    assert delay["detail"] == "TEMPORAL_DELAY_CONFIG_INCOMPLETE"
    assert delay["provenance_class"] == "POST_HOC"


def test_chain_analysis_exposes_indexed_t_delay_unavailable_reason():
    async def exercise(client: httpx2.AsyncClient):
        loaded = await client.post("/api/v1/snapshots", json=_payload())
        assert loaded.status_code == 201
        return await client.get("/api/v1/chains/C1")

    response = run_api_test(exercise)
    assert response.status_code == 200
    temporal = next(
        group
        for group in response.json()["members"][0]["group_fits"]
        if group["derivation_tag"] == "temporal_delay"
    )
    assert temporal["fit"] is None
    assert temporal["unavailable_reasons"] == {
        "T_delay": "NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH"
    }


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
    assert polled.json()["snapshot_id"] == "s1"
    assert polled.json()["snapshot_version"] == "1"
    assert polled.json()["result"]["chain_id"] == "C1"
    assert polled.json()["result"]["audit_graph_mode"] == "EXACT_FULL"
    assert polled.json()["result"]["similarity_status"] == "UNAVAILABLE"
    assert polled.json()["result"]["similarity_model_version"] is None
    assert polled.json()["result"]["similarity_trained_until_exclusive"] is None
    assert polled.json()["result"]["similarity_corpus_policy"] is None
    assert polled.json()["result"]["similarity_model_update_policy"] is None
    attribution = polled.json()["result"]["evidence_attribution"]
    assert attribution["status"] == "AVAILABLE"
    assert attribution["mode"] == "EXACT"
    assert attribution["reason"] is None
    assert attribution["chain_size"] == 3
    assert attribution["total_pair_count"] == 3
    assert attribution["total_coverage"] == 1.0
    evaluation = polled.json()["result"]["evidence_attribution_evaluation"]
    assert evaluation["status"] == "AVAILABLE"
    assert evaluation["mode"] == "EXACT"
    assert evaluation["group_count"] == len(attribution["contributions"])
    assert evaluation["primary"]["coverage_curve"][0] == 1.0
    assert evaluation["primary"]["coverage_curve"][-1] == 0.0
    assert evaluation["random"]["algorithm"] == "SPLITMIX64_FISHER_YATES_V1"
    assert evaluation["random"]["seed"] == 42
    assert evaluation["random"]["repetitions"] == 100
    assert evaluation["random"]["repetitions_executed"] == 100
    topology = polled.json()["result"]["topology_hypotheses"]
    assert topology["dominator"]["status"] == "UNAVAILABLE"
    assert topology["dominator"]["reason"] is not None
    assert "positive_score" not in topology["dominator"]
    assert topology["propagation"]["status"] == "UNAVAILABLE"
    assert topology["propagation"]["reason"] == "PROPAGATION_CONFIG_INCOMPLETE"
    assert topology["dependency_scope"]["status"] == "UNAVAILABLE"
    assert topology["dependency_scope"]["resource_details"]["missing_resources"] is None
    assert topology["dependency_scope"]["resource_details"]["extra_resources"] is None


def test_latest_deep_dive_rehydrates_the_full_in_memory_result():
    async def exercise(client: httpx2.AsyncClient):
        await client.post("/api/v1/snapshots", json=_payload())
        submission = await client.post("/api/v1/chains/C1/deep-dive")
        job_id = submission.json()["job_id"]
        for _ in range(40):
            polled = await client.get(f"/api/v1/jobs/{job_id}")
            if polled.json()["status"] in {"SUCCEEDED", "FAILED"}:
                break
            await asyncio.sleep(0.01)
        latest = await client.get("/api/v1/chains/C1/deep-dive")
        return polled, latest

    polled, latest = run_api_test(exercise)

    assert polled.json()["status"] == "SUCCEEDED"
    assert latest.status_code == 200
    assert latest.json() == polled.json()
    assert latest.json()["result"]["evidence_attribution"]["status"] == "AVAILABLE"


def test_latest_deep_dive_returns_empty_without_submitting_work():
    async def exercise(client: httpx2.AsyncClient):
        await client.post("/api/v1/snapshots", json=_payload())
        return await client.get("/api/v1/chains/C1/deep-dive")

    response = run_api_test(exercise)

    assert response.status_code == 200
    assert response.json() is None


def test_audit_visualization_read_is_unavailable_without_submitting_deep_dive():
    async def run():
        service = Workspace()
        app = create_app(workspace=service)
        transport = httpx2.ASGITransport(app=app)
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                await client.post("/api/v1/snapshots", json=_payload())
                before = len(service.jobs._jobs)
                response = await client.get(
                    "/api/v1/chains/C1/audit-visualization"
                )
                after = len(service.jobs._jobs)
                return response, before, after
        finally:
            service.close()

    response, before, after = asyncio.run(run())

    assert response.status_code == 200
    assert before == after == 0
    body = response.json()
    assert body["snapshot_id"] == "s1"
    assert body["snapshot_version"] == "1"
    assert body["chain_id"] == "C1"
    assert body["audit_artifact_id"] is None
    assert body["audit_artifact_fingerprint"] is None
    assert body["visualization"]["status"] == "UNAVAILABLE"
    assert body["visualization"]["reason"] == "AUDIT_ARTIFACT_NOT_AVAILABLE"
    assert body["visualization"]["nodes"] == []
    assert body["visualization"]["edges"] == []


def test_audit_visualization_read_returns_the_frozen_job_projection():
    async def exercise(client: httpx2.AsyncClient):
        await client.post("/api/v1/snapshots", json=_payload())
        submission = await client.post("/api/v1/chains/C1/deep-dive")
        job_id = submission.json()["job_id"]
        polled = await client.get(f"/api/v1/jobs/{job_id}")
        for _ in range(20):
            if polled.json()["status"] in {"SUCCEEDED", "FAILED"}:
                break
            await asyncio.sleep(0.01)
            polled = await client.get(f"/api/v1/jobs/{job_id}")
        projected = await client.get("/api/v1/chains/C1/audit-visualization")
        return polled, projected

    polled, projected = run_api_test(exercise)

    assert polled.json()["status"] == "SUCCEEDED"
    assert projected.status_code == 200
    body = projected.json()
    assert body["audit_artifact_id"]
    assert body["audit_artifact_fingerprint"]
    assert body["visualization"] == polled.json()["result"]["audit_visualization"]
    assert body["visualization"]["status"] == "AVAILABLE"
    assert body["visualization"]["shown_node_count"] == 3
    assert len(body["visualization"]["nodes"]) == 3


def test_audit_visualization_payload_is_identical_after_workspace_hydration():
    async def run():
        live = Workspace()
        live.replace_snapshot(_payload())
        submission = live.submit_deep_dive("C1")
        for _ in range(40):
            job = live.jobs.get(submission.job_id)
            if job.status.value in {"SUCCEEDED", "FAILED"}:
                break
            await asyncio.sleep(0.01)
        assert job.status.value == "SUCCEEDED"
        artifact = job.audit_artifact
        assert artifact is not None
        live_lookup = await live.latest_audit_visualization("C1")

        class FrozenRepository:
            async def latest_compatible_audit_artifact(self, **_identity):
                return artifact

        restarted = Workspace()
        restarted.replace_snapshot(_payload())
        restarted.repository = FrozenRepository()
        try:
            hydrated_lookup = await restarted.latest_audit_visualization("C1")
            return (
                live_lookup.visualization,
                hydrated_lookup.visualization,
                hydrated_lookup.audit_artifact,
            )
        finally:
            live.close()
            restarted.close()

    live_value, hydrated_value, hydrated_artifact = asyncio.run(run())

    assert hydrated_value == live_value
    assert hydrated_artifact is not None
    assert hydrated_artifact.artifact_fingerprint


def test_legacy_audit_artifact_returns_explicit_visualization_unavailability():
    async def run():
        source = Workspace()
        source.replace_snapshot(_payload())
        submission = source.submit_deep_dive("C1")
        for _ in range(40):
            job = source.jobs.get(submission.job_id)
            if job.status.value in {"SUCCEEDED", "FAILED"}:
                break
            await asyncio.sleep(0.01)
        assert job.audit_artifact is not None
        payload = audit_artifact_to_dict(job.audit_artifact)
        payload["artifact_version"] = "review-audit-v1"
        payload.pop("visualization")
        payload.pop("artifact_fingerprint")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["artifact_fingerprint"] = sha256(encoded.encode()).hexdigest()
        legacy = audit_artifact_from_dict(payload)

        class LegacyRepository:
            async def latest_compatible_audit_artifact(self, **_identity):
                return legacy

        restarted = Workspace()
        restarted.replace_snapshot(_payload())
        restarted.repository = LegacyRepository()
        try:
            return await restarted.latest_audit_visualization("C1")
        finally:
            source.close()
            restarted.close()

    lookup = asyncio.run(run())

    assert lookup.audit_artifact is not None
    assert lookup.audit_artifact.artifact_version == "review-audit-v1"
    assert lookup.visualization.status == "UNAVAILABLE"
    assert (
        lookup.visualization.reason
        == "BOUNDED_PUBLIC_AUDIT_GRAPH_ARTIFACT_NOT_AVAILABLE"
    )


def test_singleton_deep_dive_serializes_not_applicable_attribution():
    payload = _payload()
    payload["alarms"] = payload["alarms"][:1]
    payload["memberships"] = payload["memberships"][:1]
    payload["chains"][0]["member_count"] = 1

    async def exercise(client: httpx2.AsyncClient):
        await client.post("/api/v1/snapshots", json=payload)
        submission = await client.post("/api/v1/chains/C1/deep-dive")
        job_id = submission.json()["job_id"]
        polled = await client.get(f"/api/v1/jobs/{job_id}")
        for _ in range(20):
            if polled.json()["status"] in {"SUCCEEDED", "FAILED"}:
                break
            await asyncio.sleep(0.01)
            polled = await client.get(f"/api/v1/jobs/{job_id}")
        return polled

    response = run_api_test(exercise)
    attribution = response.json()["result"]["evidence_attribution"]
    assert response.json()["status"] == "SUCCEEDED"
    assert attribution["status"] == "NOT_APPLICABLE"
    assert attribution["mode"] == "UNAVAILABLE"
    assert attribution["reason"] == "SINGLETON"
    assert attribution["detail"] == "SINGLETON_CHAIN"
    assert attribution["total_coverage"] is None
    assert attribution["contributions"] == []
    evaluation = response.json()["result"]["evidence_attribution_evaluation"]
    assert evaluation["status"] == "UNAVAILABLE"
    assert evaluation["reason"] == "ATTRIBUTION_UNAVAILABLE"
    assert evaluation["primary"]["coverage_curve"] == []
    assert evaluation["primary"]["auc"] is None
