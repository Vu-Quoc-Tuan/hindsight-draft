from __future__ import annotations

import asyncio

import pytest

from configuration import ChunkRetentionMode
from nocpro_api.tier1a_coordinator import Tier1ACoordinator
from nocpro_api.persistence import Tier1AClaim


class Repository:
    def __init__(self) -> None:
        self.failures: list[tuple[str, str, str, int, int]] = []

    async def claim_next_tier1a(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ):
        return Tier1AClaim(
            snapshot_id="s1",
            snapshot_version="1",
            payload={"snapshot": {"snapshot_id": "s1"}},
            worker_id=worker_id,
            attempt_count=1,
        )

    async def heartbeat_tier1a(self, *args, **kwargs):
        return True

    async def record_tier1a_failure(
        self,
        snapshot_id: str,
        snapshot_version: str,
        *,
        error: str,
        worker_id: str,
        max_attempts: int,
        backoff_base_seconds: int,
    ) -> str:
        self.failures.append(
            (
                snapshot_id,
                snapshot_version,
                error,
                max_attempts,
                backoff_base_seconds,
            )
        )
        return "PENDING"


class FailingWorkspace:
    def compute_snapshot(self, payload):
        raise RuntimeError("temporary worker failure")


class SuccessfulRepository:
    def __init__(self) -> None:
        self.claimed = False
        self.finish_kwargs = None

    async def claim_next_tier1a(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ):
        if self.claimed:
            return None
        self.claimed = True
        return Tier1AClaim(
            snapshot_id="old-replay",
            snapshot_version="1",
            payload={"snapshot": {"snapshot_id": "old-replay", "snapshot_version": "1"}},
            worker_id=worker_id,
            attempt_count=1,
        )

    async def heartbeat_tier1a(self, *args, **kwargs):
        return True

    async def finish_tier1a(self, *args, **kwargs):
        self.finish_kwargs = kwargs
        return None

    async def latest_ready_payload(self):
        return {"snapshot": {"snapshot_id": "newer", "snapshot_version": "1"}}


class RecordingWorkspace:
    def __init__(self) -> None:
        self.active = None

    def compute_snapshot(self, payload):
        snapshot = payload["snapshot"]
        precompute = type(
            "Precompute",
            (),
            {
                "snapshot_id": snapshot["snapshot_id"],
                "alarm_count": 0,
                "chain_count": 0,
                "singleton_count": 0,
                "config_version": "v1",
            },
        )()
        return payload, precompute

    def activate_snapshot(self, package, precompute):
        self.active = package["snapshot"]["snapshot_id"]


def test_tier1a_failure_records_the_frozen_retry_policy():
    repository = Repository()
    coordinator = Tier1ACoordinator(repository, FailingWorkspace())

    with pytest.raises(RuntimeError, match="temporary worker failure"):
        asyncio.run(coordinator.run("s1", "1"))

    assert repository.failures == [
        ("s1", "1", "temporary worker failure", 5, 2)
    ]


def test_completed_old_replay_never_replaces_newer_logical_ready_snapshot():
    workspace = RecordingWorkspace()
    repository = SuccessfulRepository()
    coordinator = Tier1ACoordinator(repository, workspace)

    result = asyncio.run(coordinator.run_pending_once())

    assert result is not None
    assert result[0] == ("old-replay", "1")
    assert workspace.active == "newer"
    assert repository.finish_kwargs["delete_chunks_after_ready"] is False


def test_tier1a_passes_explicit_delete_after_ready_policy_only_when_selected():
    workspace = RecordingWorkspace()
    repository = SuccessfulRepository()
    coordinator = Tier1ACoordinator(
        repository,
        workspace,
        chunk_retention_mode=ChunkRetentionMode.DELETE_AFTER_READY,
    )

    result = asyncio.run(coordinator.run_pending_once())

    assert result is not None
    assert repository.finish_kwargs["delete_chunks_after_ready"] is True


def test_hydrate_active_preserves_an_explicit_in_process_selection():
    class HydrationRepository:
        async def latest_ready_payload(self):
            return {"snapshot": {"snapshot_id": "stale-golden", "snapshot_version": "1"}}

    class SelectedWorkspace:
        precompute = object()
        similarity_index = object()
        historical_model = object()
        temporal_delay_model = object()

        def active_identity(self):
            return "catalog-replay", "1"

        def compute_snapshot(self, payload):
            raise AssertionError("recovery must not replace an explicit selection")

    workspace = SelectedWorkspace()
    result = asyncio.run(Tier1ACoordinator(HydrationRepository(), workspace).hydrate_active())

    assert result is workspace.precompute


def test_payload_hydration_resolves_aliases_at_the_snapshot_topology_version():
    class TopologyRepository:
        def __init__(self) -> None:
            self.resolved_versions: list[str | None] = []

        async def resolve_identifier(self, _profile_id, _identifier, *, topology_version=None):
            self.resolved_versions.append(topology_version)
            return {"resource_id": "resource-v1"}

        async def hydrate_graph_for_analysis(self, *_args, **_kwargs):
            return {"edges": [], "nodes": []}

    topology_repository = TopologyRepository()
    coordinator = Tier1ACoordinator(
        Repository(),
        SuccessfulRepository(),
        topology_repository=topology_repository,
    )
    payload = {
        "snapshot": {
            "snapshot_id": "replay",
            "topology_ref": {"profile_id": "IT_SERVICES", "topology_version": "v1"},
        },
        "alarms": [{"alarm_id": "A1", "device_code": "legacy-alias"}],
    }

    asyncio.run(coordinator._hydrate_payload_topology_if_needed(payload))
    assert topology_repository.resolved_versions == ["v1"]
    assert payload["topology"]["mappings"][0]["resource_id"] == "resource-v1"
