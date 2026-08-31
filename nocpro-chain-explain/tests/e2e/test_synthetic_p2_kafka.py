"""Docker acceptance for versioned synthetic topology over the real Kafka path.

This proves implementation behavior only. ``SYNTHETIC_TEST`` output remains
ineligible for production validation.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from uuid import uuid4

import asyncpg
import httpx2
import pytest

if os.environ.get("NOCPRO_RUN_DOCKER_E2E") != "1":
    pytest.skip(
        "set NOCPRO_RUN_DOCKER_E2E=1 to run synthetic Kafka P2 acceptance",
        allow_module_level=True,
    )

pytest.importorskip("nocpro_mock")

from nocpro_mock.contract import (
    AlarmResourceMapping,
    MappingMethod,
    MappingStatus,
    Topology,
)
from nocpro_mock.producer.kafka_snapshot import (
    KafkaSnapshotConfig,
    publish_snapshot,
)
from nocpro_mock.scenarios import (
    build_synthetic_snapshot,
    generate_dependency_hierarchy,
    parse_scenario,
)


pytestmark = pytest.mark.docker

KAFKA_BOOTSTRAP = os.environ.get("NOCPRO_E2E_KAFKA", "127.0.0.1:29092")
DATABASE_URL = os.environ.get(
    "NOCPRO_E2E_DATABASE_URL",
    "postgresql://nocpro:nocpro@127.0.0.1:55432/nocpro",
)
API_URL = os.environ.get("NOCPRO_E2E_API_URL", "http://127.0.0.1:8800")
GENERATOR_VERSION = "mockgen-synthetic-p2-e2e-v1"
TOPOLOGY_SOURCE_ID = "synthetic-topology"
TOPOLOGY_SOURCE_VERSION = "syn-topo-p2-e2e-v1"


def _versioned_package(case: str, minute_offset: int):
    token = uuid4().hex[:10]
    scenario_id = f"synthetic_p2_kafka_{case.lower()}_{token}"
    chain_id = f"SYN-CHAIN-{case}-{token}"
    alarm_ids = tuple(f"SYN-ALARM-{case}-{index}-{token}" for index in range(1, 4))
    resource_ids = ("SYN-R1", "SYN-R2", "SYN-R3")
    scenario = parse_scenario(
        {
            "scenario_id": scenario_id,
            "source_kind": "SYNTHETIC_TEST",
            "seed": 20260831,
            "topology_source": {
                "source_id": TOPOLOGY_SOURCE_ID,
                "source_version": TOPOLOGY_SOURCE_VERSION,
            },
            "topology": {
                "relation_type": "LOGICAL_DEPENDENCY",
                "directed": True,
                "edges": [
                    ["SYN-ROOT", "SYN-R1"],
                    ["SYN-R1", "SYN-R2"],
                    ["SYN-R2", "SYN-R3"],
                ],
            },
        }
    )
    nodes, edges = generate_dependency_hierarchy(
        scenario, generator_version=GENERATOR_VERSION
    )
    mappings = tuple(
        AlarmResourceMapping(
            alarm_id=alarm_id,
            resource_id=resource_id,
            mapping_status=MappingStatus.EXACT,
            mapping_method=MappingMethod.EXACT_IDENTITY,
            mapping_confidence=1.0,
            source_version=TOPOLOGY_SOURCE_VERSION,
        )
        for alarm_id, resource_id in zip(alarm_ids, resource_ids, strict=True)
    )
    package = build_synthetic_snapshot(
        scenario_id=scenario_id,
        seed=scenario.seed,
        generator_version=GENERATOR_VERSION,
        snapshot_index=0,
        chains={chain_id: list(alarm_ids)},
        topology=Topology(nodes=nodes, edges=edges, mappings=mappings),
        topology_source=scenario.topology_source,
    )
    logical_time = datetime.now(timezone.utc) + timedelta(minutes=minute_offset)
    package = replace(
        package,
        snapshot=replace(
            package.snapshot,
            snapshot_time=logical_time.isoformat(),
            produced_at=logical_time.isoformat(),
        ),
    )
    return package, chain_id


async def _wait_for_ready(snapshot_id: str, *, timeout: float = 60.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        connection = await asyncpg.connect(DATABASE_URL)
        try:
            last = await connection.fetchrow(
                """
                SELECT status, tier1a_status, lineage_status, similarity_status
                  FROM snapshot_ingest
                 WHERE snapshot_id = $1 AND snapshot_version = '1'
                """,
                snapshot_id,
            )
        finally:
            await connection.close()
        if (
            last is not None
            and last["status"] == "COMPLETE"
            and last["tier1a_status"] == "READY"
            and last["lineage_status"] == "READY"
            and last["similarity_status"] == "READY"
        ):
            return
        await asyncio.sleep(0.25)
    raise AssertionError(f"snapshot {snapshot_id} did not become READY; last={last}")


async def _wait_until_active(client: httpx2.AsyncClient, snapshot_id: str) -> None:
    deadline = asyncio.get_running_loop().time() + 30.0
    last = None
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get("/api/v1/chains")
        if response.status_code == 200:
            last = response.json()
            if last.get("snapshot_id") == snapshot_id:
                return
        await asyncio.sleep(0.25)
    raise AssertionError(f"snapshot {snapshot_id} was READY but not active; last={last}")


async def _deep_dive(client: httpx2.AsyncClient, chain_id: str) -> dict:
    submitted = await client.post(f"/api/v1/chains/{chain_id}/deep-dive")
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["job_id"]
    deadline = asyncio.get_running_loop().time() + 30.0
    last = None
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] == "SUCCEEDED":
            return last["result"]["topology_hypotheses"]
        if last["status"] == "FAILED":
            raise AssertionError(f"Tier-2 job failed: {last}")
        await asyncio.sleep(0.1)
    raise AssertionError(f"Tier-2 job did not finish; last={last}")


def _assert_trace(result: dict) -> None:
    assert result["source_id"] == TOPOLOGY_SOURCE_ID
    assert result["source_version"] == TOPOLOGY_SOURCE_VERSION
    assert result["scenario_id"].startswith("synthetic_p2_kafka_versioned_")
    assert result["generator_version"] == GENERATOR_VERSION
    assert result["source_version"] != result["generator_version"]


def test_01_versioned_synthetic_topology_reaches_available_p2_through_kafka():
    async def exercise() -> None:
        package, chain_id = _versioned_package("VERSIONED", 30)
        await publish_snapshot(
            package,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            config=KafkaSnapshotConfig(chunk_target_bytes=128),
        )
        await _wait_for_ready(package.snapshot.snapshot_id)
        async with httpx2.AsyncClient(base_url=API_URL, timeout=10.0) as client:
            await _wait_until_active(client, package.snapshot.snapshot_id)
            topology = await _deep_dive(client, chain_id)

        assert topology["dominator"]["status"] == "AVAILABLE"
        assert topology["propagation"]["status"] == "AVAILABLE", json.dumps(
            topology["propagation"], indent=2, sort_keys=True
        )
        assert topology["dependency_scope"]["status"] == "AVAILABLE"
        _assert_trace(topology["dominator"])
        _assert_trace(topology["propagation"])
        _assert_trace(topology["dependency_scope"])

    asyncio.run(exercise())


def test_02_foreign_unversioned_topology_keeps_tier1a_but_disables_p2():
    async def exercise() -> None:
        package, chain_id = _versioned_package("UNVERSIONED", 31)
        foreign_topology = replace(
            package.topology,
            edges=tuple(
                replace(edge, source_version=None) for edge in package.topology.edges
            ),
        )
        package = replace(package, topology=foreign_topology)
        await publish_snapshot(
            package,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            config=KafkaSnapshotConfig(chunk_target_bytes=128),
        )
        await _wait_for_ready(package.snapshot.snapshot_id)
        async with httpx2.AsyncClient(base_url=API_URL, timeout=10.0) as client:
            await _wait_until_active(client, package.snapshot.snapshot_id)
            topology = await _deep_dive(client, chain_id)

        for capability in ("dominator", "propagation", "dependency_scope"):
            assert topology[capability]["status"] == "UNAVAILABLE"
            assert (
                topology[capability]["reason"]
                == "TOPOLOGY_SOURCE_VERSION_MISSING"
            )

    asyncio.run(exercise())
