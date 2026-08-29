from __future__ import annotations

import asyncio

import pytest

from nocpro_api.tier1a_coordinator import Tier1ACoordinator


class Repository:
    def __init__(self) -> None:
        self.released: list[tuple[str, str, str]] = []

    async def claim_tier1a(self, snapshot_id: str, snapshot_version: str):
        return {"snapshot": {"snapshot_id": snapshot_id}}

    async def release_tier1a(
        self, snapshot_id: str, snapshot_version: str, *, error: str
    ) -> None:
        self.released.append((snapshot_id, snapshot_version, error))


class FailingWorkspace:
    def replace_snapshot(self, payload):
        raise RuntimeError("temporary worker failure")


def test_tier1a_failure_releases_claim_for_kafka_redelivery():
    repository = Repository()
    coordinator = Tier1ACoordinator(repository, FailingWorkspace())

    with pytest.raises(RuntimeError, match="temporary worker failure"):
        asyncio.run(coordinator.run("s1", "1"))

    assert repository.released == [("s1", "1", "temporary worker failure")]
