"""Kafka/PostgreSQL/API acceptance for synthetic Counterfactual Review P0/P1.1."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import asyncpg
import httpx2
import pytest

if os.environ.get("NOCPRO_RUN_DOCKER_E2E") != "1":
    pytest.skip(
        "set NOCPRO_RUN_DOCKER_E2E=1 to run Counterfactual acceptance",
        allow_module_level=True,
    )

pytest.importorskip("nocpro_mock")

from nocpro_mock.config import GENERATOR_VERSION
from nocpro_mock.producer.kafka_snapshot import KafkaSnapshotConfig, publish_snapshot
from nocpro_mock.scenarios import COUNTERFACTUAL_FIXTURES, build_synthetic_snapshot


pytestmark = pytest.mark.docker
KAFKA_BOOTSTRAP = os.environ.get("NOCPRO_E2E_KAFKA", "127.0.0.1:29092")
DATABASE_URL = os.environ.get(
    "NOCPRO_E2E_DATABASE_URL",
    "postgresql://nocpro:nocpro@127.0.0.1:55432/nocpro",
)
API_URL = os.environ.get("NOCPRO_E2E_API_URL", "http://127.0.0.1:8800")
PROJECT = os.environ.get("NOCPRO_E2E_COMPOSE_PROJECT", "nocpro-acceptance")
ROOT = Path(__file__).resolve().parents[2]


def _restart_api() -> None:
    subprocess.run(
        ["docker", "compose", "-p", PROJECT, "restart", "api"],
        cwd=ROOT,
        check=True,
    )


async def _next_logical_time() -> datetime:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        latest = await connection.fetchval(
            "SELECT max(logical_snapshot_time) FROM snapshot_ingest"
        )
    finally:
        await connection.close()
    baseline = datetime.now(timezone.utc)
    if latest is not None and latest > baseline:
        baseline = latest
    return baseline + timedelta(minutes=1)


def _package(fixture, logical_time: datetime):
    token = uuid4().hex[:10]
    scenario_id = f"{fixture.scenario_id}_{token}"
    package = build_synthetic_snapshot(
        scenario_id=scenario_id,
        seed=42,
        generator_version=GENERATOR_VERSION,
        snapshot_index=0,
        chains=fixture.snapshot_chains(),
        alarm_profiles=fixture.alarm_profiles,
        generation_rule=f"COUNTERFACTUAL {fixture.mutation} Docker fixture",
    )
    old_time = datetime.fromisoformat(package.snapshot.snapshot_time)
    delta = logical_time - old_time
    return replace(
        package,
        snapshot=replace(
            package.snapshot,
            snapshot_time=logical_time.isoformat(),
            produced_at=logical_time.isoformat(),
        ),
        alarms=tuple(
            replace(
                alarm,
                raw={
                    **alarm.raw,
                    "cah.start_time": (
                        datetime.fromisoformat(alarm.canonical_start_time) + delta
                    ).isoformat(),
                },
                raw_start_time=(
                    datetime.fromisoformat(alarm.raw_start_time) + delta
                ).isoformat(),
                canonical_start_time=(
                    datetime.fromisoformat(alarm.canonical_start_time) + delta
                ).isoformat(),
            )
            for alarm in package.alarms
        ),
    )


async def _wait_ready(snapshot_id: str, timeout: float = 60) -> None:
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
        if last and tuple(last.values()) == ("COMPLETE", "READY", "READY", "READY"):
            return
        await asyncio.sleep(0.25)
    raise AssertionError(f"snapshot did not become READY: {last}")


async def _chunk_count(snapshot_id: str) -> int:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        return int(
            await connection.fetchval(
                """
                SELECT count(*)
                  FROM snapshot_chunks
                 WHERE snapshot_id = $1 AND snapshot_version = '1'
                """,
                snapshot_id,
            )
            or 0
        )
    finally:
        await connection.close()


async def _wait_active(client, snapshot_id: str) -> None:
    deadline = asyncio.get_running_loop().time() + 30
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get("/api/v1/chains")
        if response.status_code == 200 and response.json()["snapshot_id"] == snapshot_id:
            return
        await asyncio.sleep(0.25)
    raise AssertionError(f"snapshot {snapshot_id} did not become active")


async def _wait_health(client) -> None:
    deadline = asyncio.get_running_loop().time() + 60
    while asyncio.get_running_loop().time() < deadline:
        try:
            response = await client.get("/api/v1/health")
            if response.status_code == 200:
                return
        except httpx2.HTTPError:
            # The old keep-alive socket is expected to close when the API
            # process restarts; retry with a fresh pooled connection.
            pass
        await asyncio.sleep(0.25)
    raise AssertionError("API did not recover after restart")


async def _poll(client, path: str) -> dict:
    deadline = asyncio.get_running_loop().time() + 30
    last = None
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(path)
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] == "SUCCEEDED":
            return last
        if last["status"] == "FAILED":
            raise AssertionError(last)
        await asyncio.sleep(0.1)
    raise AssertionError(f"job did not finish: {last}")


async def _run_case(client, fixture, logical_time):
    package = _package(fixture, logical_time)
    await publish_snapshot(
        package,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        config=KafkaSnapshotConfig(chunk_target_bytes=128),
    )
    await _wait_ready(package.snapshot.snapshot_id)
    # This E2E deployment explicitly chooses DELETE_AFTER_READY.  The API must
    # remain usable from canonical persistence after the transport bytes vanish.
    assert await _chunk_count(package.snapshot.snapshot_id) == 0
    await _wait_active(client, package.snapshot.snapshot_id)

    audit_submission = await client.post(
        f"/api/v1/chains/{fixture.chain_id}/deep-dive"
    )
    assert audit_submission.status_code == 202, audit_submission.text
    audit = await _poll(
        client, f"/api/v1/jobs/{audit_submission.json()['job_id']}"
    )
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        artifact = await connection.fetchrow(
            """
            SELECT artifact_fingerprint, mode, status
              FROM audit_artifact
             WHERE snapshot_id = $1 AND snapshot_version = $2 AND chain_id = $3
             ORDER BY created_at DESC
             LIMIT 1
            """,
            package.snapshot.snapshot_id,
            package.snapshot.snapshot_version,
            fixture.chain_id,
        )
    finally:
        await connection.close()
    assert audit["result"]["audit_graph_mode"] == "EXACT_FULL"
    assert artifact is not None
    assert artifact["status"] == "AVAILABLE"
    assert artifact["mode"] == "EXACT"

    _restart_api()
    await _wait_health(client)
    await _wait_active(client, package.snapshot.snapshot_id)
    review_submission = await client.post(
        f"/api/v1/chains/{fixture.chain_id}/review"
    )
    assert review_submission.status_code == 202, review_submission.text
    review = await _poll(
        client, f"/api/v1/review-jobs/{review_submission.json()['job_id']}"
    )
    return package, review, artifact["artifact_fingerprint"]


def test_counterfactual_review_operations_survive_real_transport_and_persistence():
    async def exercise() -> None:
        base = await _next_logical_time()
        async with httpx2.AsyncClient(base_url=API_URL, timeout=15) as client:
            # The Chromium Review acceptance is run immediately after this
            # test and intentionally renders the MOVE proposal.  Keep the
            # transport assertions for every operation, but make the final
            # active snapshot explicit rather than implicitly relying on the
            # fixture declaration order.
            fixtures = tuple(
                fixture
                for fixture in COUNTERFACTUAL_FIXTURES
                if fixture.mutation != "MISASSIGNED_MEMBER"
            ) + tuple(
                fixture
                for fixture in COUNTERFACTUAL_FIXTURES
                if fixture.mutation == "MISASSIGNED_MEMBER"
            )
            for index, fixture in enumerate(fixtures):
                package, review, artifact_fingerprint = await _run_case(
                    client, fixture, base + timedelta(minutes=index)
                )
                result = review["result"]
                assert result["recommendation_status"] == "AVAILABLE"
                # Review contract v1 deliberately keeps recommendations as
                # lightweight candidate references.  Assertions about an
                # operation belong to the canonical evaluated-candidate
                # registry, filtered by the selected frontier references.
                selected_ids = {
                    item["candidate_id"] for item in result["recommendations"]
                }
                recommendations = [
                    item
                    for item in result["evaluated_candidates"]
                    if item["candidate_id"] in selected_ids
                ]
                assert recommendations
                if fixture.mutation == "MISASSIGNED_MEMBER":
                    matching = [
                        item
                        for item in recommendations
                        if item["operation"] == "MOVE_MEMBER"
                        and item["operation_specific_evidence"]["alarm_id"]
                        == "SYN-MOVE-MISASSIGNED"
                        and item["operation_specific_evidence"]["source_chain_id"]
                        == "SYN-CHAIN-MOVE-SOURCE"
                        and item["operation_specific_evidence"]["target_chain_id"]
                        == "SYN-CHAIN-MOVE-TARGET"
                        and item["hard_gate_result"]["status"] == "PASSED"
                        and item["pareto_state"] == "FRONTIER_SELECTED"
                    ]
                    assert matching, "expected MOVE_MEMBER absent from frontier"
                elif fixture.mutation == "UNDER_MERGE":
                    matching = [
                        item
                        for item in recommendations
                        if item["operation"] == "MERGE_CHAINS"
                        and item["operation_specific_evidence"]["merged_chain_ids"]
                        == ["SYN-CHAIN-MERGE-LEFT", "SYN-CHAIN-MERGE-RIGHT"]
                        and item["hard_gate_result"]["status"] == "PASSED"
                        and item["pareto_state"] == "FRONTIER_SELECTED"
                    ]
                    assert matching, "expected MERGE_CHAINS absent from frontier"
                    assert matching[0]["edit_cost"]["membership_reassignments"] == 0
                    assert (
                        matching[0]["operation_specific_evidence"]
                        ["cross_chain_evidence"]["cross_audit_edge_count"]
                        >= 1
                    )
                else:
                    expected_operation = (
                        "REMOVE_MEMBER"
                        if fixture.mutation == "EXTRA_MEMBER"
                        else "SPLIT_CHAIN"
                    )
                    assert recommendations[0]["operation"] == expected_operation
                assert result["identity"]["snapshot_id"] == package.snapshot.snapshot_id
                assert result["identity"]["config_version"] == (
                    "synthetic-counterfactual-v1"
                )
                assert (
                    result["identity"]["structural_audit_artifact_fingerprint"]
                    == artifact_fingerprint
                )

                connection = await asyncpg.connect(DATABASE_URL)
                try:
                    stored = await connection.fetchrow(
                        """
                        SELECT status, identity_payload, result_payload
                          FROM counterfactual_job
                         WHERE job_id = $1
                        """,
                        review["job_id"],
                    )
                finally:
                    await connection.close()
                identity_payload = stored["identity_payload"]
                result_payload = stored["result_payload"]
                if isinstance(identity_payload, str):
                    identity_payload = json.loads(identity_payload)
                if isinstance(result_payload, str):
                    result_payload = json.loads(result_payload)
                assert stored["status"] == "SUCCEEDED"
                assert identity_payload["snapshot_id"] == package.snapshot.snapshot_id
                assert result_payload["recommendation_status"] == "AVAILABLE"

    asyncio.run(exercise())
