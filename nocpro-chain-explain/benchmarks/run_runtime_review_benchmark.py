"""Measure persisted Counterfactual Review recovery through the live API.

This runner deliberately measures the operational path that an in-process
benchmark cannot prove:

    Docker API restart -> health recovery -> repository-backed Review hydrate

It assumes the explicit acceptance stack is already up and contains a
compatible persisted Review for ``REVIEW_CHAIN_ID``.  It never submits a new
recommendation, mutates a partition, or fabricates an in-memory result.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from statistics import median
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy import delete, func, select


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services/api"))
sys.path.insert(0, str(ROOT / "services/analysis-worker"))

from nocpro_api.persistence import Database, SnapshotRepository
from nocpro_api.persistence.models import CounterfactualJobRecord


RESULTS_PATH = ROOT / "benchmarks" / "results" / "runtime-review-latest.json"
API_URL = os.environ.get("NOCPRO_E2E_API_URL", "http://127.0.0.1:8800")
PROJECT = os.environ.get("NOCPRO_E2E_COMPOSE_PROJECT", "nocpro-acceptance")
CHAIN_ID = os.environ.get("REVIEW_CHAIN_ID", "SYN-CHAIN-MOVE-SOURCE")
REPETITIONS = int(os.environ.get("BENCHMARK_RUNTIME_REPETITIONS", "20"))
DATABASE_URL = os.environ.get(
    "NOCPRO_E2E_DATABASE_URL",
    "postgresql://nocpro:nocpro@127.0.0.1:55432/nocpro",
).replace("postgresql://", "postgresql+asyncpg://", 1)


def observed_nearest_rank(values: list[float], percentile: float = 0.95) -> float:
    """Return an observed nearest-rank percentile without interpolation."""
    if not values:
        raise ValueError("at least one timing is required")
    if not 0.0 < percentile <= 1.0:
        raise ValueError("percentile must be in (0, 1]")
    return sorted(values)[math.ceil(percentile * len(values)) - 1]


def _get(path: str) -> tuple[dict, float]:
    started = time.perf_counter()
    with urlopen(f"{API_URL}{path}", timeout=15) as response:  # noqa: S310 - explicit local acceptance URL
        payload = json.loads(response.read())
    return payload, time.perf_counter() - started


def _wait_health() -> float:
    started = time.perf_counter()
    deadline = started + 60
    last_error: Exception | None = None
    while time.perf_counter() < deadline:
        try:
            payload, _ = _get("/api/v1/health")
            if payload:
                return time.perf_counter() - started
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"API did not recover within 60 seconds: {last_error}")


def _persisted_review() -> tuple[dict, float]:
    payload, elapsed = _get(f"/api/v1/chains/{CHAIN_ID}/review")
    if payload.get("status") != "SUCCEEDED":
        raise RuntimeError(f"persisted Review did not hydrate as SUCCEEDED: {payload}")
    if not isinstance(payload.get("result"), dict):
        raise RuntimeError("persisted Review response has no result payload")
    return payload, elapsed


def _assert_persisted_review() -> float:
    _, elapsed = _persisted_review()
    return elapsed


def persistence_payload(template: dict, *, job_id: str) -> dict:
    """Clone one terminal Review under a unique identity for write timing."""
    identity = template["identity"]
    return {
        "job_id": job_id,
        "snapshot_id": identity["snapshot_id"],
        "snapshot_version": identity["snapshot_version"],
        "chain_id": template["chain_id"],
        "cache_fingerprint": template["cache_fingerprint"],
        "status": template["status"],
        "progress_percent": template["progress_percent"],
        "cache_hit": template["cache_hit"],
        "identity": identity,
        "result": template["result"],
        "error": template.get("error"),
    }


async def _measure_persistence(template: dict) -> list[float]:
    database = Database(DATABASE_URL)
    repository = SnapshotRepository(database.sessions)
    durations: list[float] = []
    job_ids: list[str] = []
    try:
        for _ in range(REPETITIONS):
            job_id = f"benchmark-persistence-{uuid4().hex}"
            job_ids.append(job_id)
            payload = persistence_payload(
                template,
                job_id=job_id,
            )
            started = time.perf_counter()
            stored = await repository.persist_counterfactual_job(payload)
            durations.append(time.perf_counter() - started)
            if stored.job_id != payload["job_id"] or stored.status != "SUCCEEDED":
                raise RuntimeError("Review persistence read-back did not match write")
    finally:
        try:
            if job_ids:
                async with database.sessions.begin() as session:
                    await session.execute(
                        delete(CounterfactualJobRecord).where(
                            CounterfactualJobRecord.job_id.in_(job_ids)
                        )
                    )
                async with database.sessions() as session:
                    remaining = await session.scalar(
                        select(func.count())
                        .select_from(CounterfactualJobRecord)
                        .where(CounterfactualJobRecord.job_id.in_(job_ids))
                    )
                if remaining:
                    raise RuntimeError(
                        f"failed to clean up {remaining} persistence benchmark rows"
                    )
        finally:
            await database.close()
    return durations


def run() -> dict:
    if REPETITIONS < 20:
        raise ValueError("BENCHMARK_RUNTIME_REPETITIONS must be >= 20 for P95")

    # Ensure the input is actually a durable Review before disrupting API state.
    template, _ = _persisted_review()
    persistence = asyncio.run(_measure_persistence(template))
    restart_to_health: list[float] = []
    hydrate: list[float] = []
    for _ in range(REPETITIONS):
        subprocess.run(
            ["docker", "compose", "-p", PROJECT, "restart", "api"],
            cwd=ROOT,
            check=True,
        )
        restart_to_health.append(_wait_health())
        hydrate.append(_assert_persisted_review())

    result = {
        "contract": "runtime-review-benchmark-v1",
        "scope": "LOCAL_DOCKER_RUNTIME_ONLY",
        "compose_project": PROJECT,
        "api_url": API_URL,
        "chain_id": CHAIN_ID,
        "repetitions": REPETITIONS,
        "p95_method": "observed nearest-rank",
        "restart_to_health": {
            "p50_s": median(restart_to_health),
            "p95_s": observed_nearest_rank(restart_to_health),
            "p95_reliable": True,
            "samples_s": restart_to_health,
        },
        "review_persistence": {
            "p50_s": median(persistence),
            "p95_s": observed_nearest_rank(persistence),
            "p95_reliable": True,
            "samples_s": persistence,
        },
        "persisted_review_hydration": {
            "p50_s": median(hydrate),
            "p95_s": observed_nearest_rank(hydrate),
            "p95_reliable": True,
            "samples_s": hydrate,
        },
    }
    RESULTS_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run()
