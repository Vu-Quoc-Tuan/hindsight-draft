"""Bounded, version-scoped cache tests for the topology resolver index."""

from __future__ import annotations

import asyncio

import pytest
from contracts.v1.enums import MappingMethod, MappingStatus
from contracts.v1.models import AlarmEntityResolution

from nocpro_api.persistence.topology_repository import TopologyRepository


class _Rows:
    def all(self):
        return []


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def scalars(self, _statement):
        await asyncio.sleep(0)
        return _Rows()

    async def execute(self, _statement):
        await asyncio.sleep(0)
        return _Rows()


class _Sessions:
    def __init__(self):
        self.open_count = 0

    def __call__(self):
        self.open_count += 1
        return _Session()


pytestmark = pytest.mark.anyio


async def test_host_module_map_cache_uses_exact_profile_and_version_and_is_bounded():
    sessions = _Sessions()
    repository = TopologyRepository(sessions)

    await repository.get_host_modules_map("IT_SERVICES", topology_version="it-v1")
    await repository.get_host_modules_map("IT_SERVICES", topology_version="it-v1")
    await repository.get_host_modules_map("IT_SERVICES", topology_version="it-v2")
    await repository.get_host_modules_map("IP_NETWORK", topology_version="it-v2")

    assert sessions.open_count == 3
    assert len(repository._host_modules_cache) == 2

    # The oldest exact pair was evicted; it must be reloaded, not served from
    # another profile/version's cached mapping.
    await repository.get_host_modules_map("IT_SERVICES", topology_version="it-v1")
    assert sessions.open_count == 4
    assert len(repository._host_modules_cache) == 2


async def test_concurrent_host_module_cache_misses_share_one_topology_load():
    sessions = _Sessions()
    repository = TopologyRepository(sessions)

    await asyncio.gather(
        *[
            repository.get_host_modules_map(
                "IT_SERVICES", topology_version="it-v1"
            )
            for _ in range(8)
        ]
    )

    assert sessions.open_count == 1


async def test_unversioned_entity_resolution_is_not_persisted_under_a_guessed_profile():
    sessions = _Sessions()
    repository = TopologyRepository(sessions)
    resolution = AlarmEntityResolution(
        alarm_id="a1",
        entity_role="OBSERVED_HOST",
        raw_value="10.0.0.1",
        status=MappingStatus.UNMAPPED,
        method=MappingMethod.NONE,
    )

    with pytest.raises(ValueError, match="explicit topology profile and version"):
        await repository.save_alarm_entity_resolutions([resolution])

    assert sessions.open_count == 0
