"""Measure warm persisted chain reads safely, with disruptive acceptance gated.

The default ``read-only`` mode only issues GET requests to the snapshot catalog
and identity-pinned persisted Overview projection. It never connects to
PostgreSQL or Docker. The CLI writes its JSON report to the selected output path.
``acceptance-restart`` is a separate, explicitly disruptive mode for a verified
dedicated Compose stack; it may write benchmark Review rows and restart its API.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from statistics import median
from threading import Lock
from typing import Callable
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services/api"))
sys.path.insert(0, str(ROOT / "services/analysis-worker"))

DEFAULT_OUTPUT = Path("/tmp/hindsight-warm-chain.json")
READ_ONLY_ENDPOINTS = {
    "snapshot_catalog": "/api/v1/snapshots",
    "overview_projection": "/api/v1/chains/{chain_id}/overview-cards",
}


@dataclass(frozen=True)
class BenchmarkOptions:
    mode: str
    api_url: str
    chain_id: str
    snapshot_id: str
    snapshot_version: str
    repetitions: int
    warmups: int
    output: Path
    overwrite: bool
    allow_disruption: bool
    compose_project: str | None
    database_url: str | None


def observed_nearest_rank(values: list[float], percentile: float = 0.95) -> float:
    """Return an observed nearest-rank percentile without interpolation."""
    if not values:
        raise ValueError("at least one timing is required")
    if not 0.0 < percentile <= 1.0:
        raise ValueError("percentile must be in (0, 1]")
    return sorted(values)[math.ceil(percentile * len(values)) - 1]


def summarize_samples(
    samples: list[float], errors: list[str] | None = None
) -> dict[str, object]:
    """Summarize available samples while retaining failures and empty runs."""
    error_types = Counter(errors or [])
    return {
        "sample_count": len(samples),
        "error_count": sum(error_types.values()),
        "error_types": dict(sorted(error_types.items())),
        "p50_s": median(samples) if samples else None,
        "p95_s": observed_nearest_rank(samples) if samples else None,
        "samples_s": samples,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("read-only", "acceptance-restart"),
        default="read-only",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("NOCPRO_E2E_API_URL", "http://127.0.0.1:8800"),
    )
    parser.add_argument(
        "--chain-id",
        default=os.environ.get("REVIEW_CHAIN_ID", "SYN-CHAIN-MOVE-SOURCE"),
    )
    parser.add_argument(
        "--snapshot-id",
        default=os.environ.get("NOCPRO_BENCHMARK_SNAPSHOT_ID"),
    )
    parser.add_argument(
        "--snapshot-version",
        default=os.environ.get("NOCPRO_BENCHMARK_SNAPSHOT_VERSION"),
    )
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-disruption", action="store_true")
    parser.add_argument(
        "--compose-project",
        help="Required only for acceptance-restart; must name an isolated acceptance stack.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("NOCPRO_E2E_DATABASE_URL"),
        help="Required only for acceptance-restart; never emitted in the report.",
    )
    return parser


def parse_options(argv: list[str] | None = None) -> BenchmarkOptions:
    args = build_parser().parse_args(argv)
    api_uri = urlparse(args.api_url)
    if (
        api_uri.scheme not in {"http", "https"}
        or not api_uri.hostname
        or api_uri.username is not None
        or api_uri.password is not None
        or api_uri.query
        or api_uri.fragment
        or api_uri.path not in {"", "/"}
    ):
        raise ValueError("--api-url must be an HTTP(S) origin without credentials or extra path")
    if not args.snapshot_id or not args.snapshot_version:
        raise ValueError("--snapshot-id and --snapshot-version must identify the active snapshot")
    if args.repetitions < 30:
        raise ValueError("--repetitions must be >= 30 for stable P95 reporting")
    if args.warmups < 0:
        raise ValueError("--warmups must be >= 0")
    output = args.output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("benchmark output must be outside the repository")
    if args.mode == "acceptance-restart":
        if not args.allow_disruption:
            raise ValueError("acceptance-restart requires --allow-disruption")
        if not args.compose_project:
            raise ValueError("acceptance-restart requires explicit --compose-project")
        if not args.database_url:
            raise ValueError("acceptance-restart requires --database-url")
        if "acceptance" not in args.compose_project.lower():
            raise ValueError("--compose-project must identify a dedicated acceptance stack")
    return BenchmarkOptions(
        mode=args.mode,
        api_url=args.api_url.rstrip("/"),
        chain_id=args.chain_id,
        snapshot_id=str(args.snapshot_id),
        snapshot_version=str(args.snapshot_version),
        repetitions=args.repetitions,
        warmups=args.warmups,
        output=output,
        overwrite=args.overwrite,
        allow_disruption=args.allow_disruption,
        compose_project=args.compose_project,
        database_url=args.database_url,
    )


def request_headers(options: BenchmarkOptions) -> dict[str, str]:
    return {
        "X-Nocpro-Snapshot-Id": options.snapshot_id,
        "X-Nocpro-Snapshot-Version": options.snapshot_version,
    }


def get_json(
    api_url: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[dict, float]:
    request = Request(
        f"{api_url}{path}",
        headers={"Accept": "application/json", **(headers or {})},
        method="GET",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - caller-supplied API URL
        raw = response.read(2 * 1024 * 1024 + 1)
    elapsed = time.perf_counter() - started
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("benchmark response exceeded the 2 MiB safety limit")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("API returned a non-object JSON response")
    return payload, elapsed


def _assert_active_identity(catalog_payload: dict, options: BenchmarkOptions) -> None:
    actual = (
        str(catalog_payload.get("active_snapshot_id") or ""),
        str(catalog_payload.get("active_snapshot_version") or ""),
    )
    expected = (options.snapshot_id, options.snapshot_version)
    if actual != expected:
        raise RuntimeError("active snapshot identity does not match the requested benchmark identity")


def _validate_overview(payload: dict, options: BenchmarkOptions) -> None:
    actual = (
        str(payload.get("snapshot_id", "")),
        str(payload.get("snapshot_version", "")),
        str(payload.get("chain_id", "")),
    )
    expected = (options.snapshot_id, options.snapshot_version, options.chain_id)
    if actual != expected:
        raise RuntimeError("overview response identity differs from the pinned benchmark identity")


def _measure(
    call,
    *,
    warmups: int,
    repetitions: int,
) -> dict[str, object]:
    for _ in range(warmups):
        call()
    samples: list[float] = []
    errors: list[str] = []
    for _ in range(repetitions):
        try:
            samples.append(call())
        except (OSError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
            # Never persist response bodies, alarm data, credentials, or full URLs.
            errors.append(type(exc).__name__)
    return summarize_samples(samples, errors)


def _run_read_only(
    options: BenchmarkOptions,
    *,
    get: Callable[..., tuple[dict, float]] = get_json,
) -> dict:
    catalog, preflight_seconds = get(
        options.api_url, READ_ONLY_ENDPOINTS["snapshot_catalog"]
    )
    _assert_active_identity(catalog, options)
    overview_path = READ_ONLY_ENDPOINTS["overview_projection"].format(
        chain_id=quote(options.chain_id, safe="")
    )
    pinned_headers = request_headers(options)
    projection_states: Counter[str] = Counter()
    projection_versions: Counter[str] = Counter()
    topology_versions: Counter[str] = Counter()
    projection_states_lock = Lock()
    observed_topology = False
    expected_topology_version: str | None = None

    def measured_get(path: str, headers: dict[str, str] | None = None) -> float:
        nonlocal observed_topology, expected_topology_version
        payload, elapsed = get(options.api_url, path, headers=headers)
        if path == overview_path:
            _validate_overview(payload, options)
            status = str(payload.get("status") or "UNKNOWN").upper()
            if status not in {"READY", "PENDING", "UNAVAILABLE", "NOT_APPLICABLE"}:
                status = "OTHER"
            topology_version = payload.get("topology_version")
            with projection_states_lock:
                projection_states[status] += 1
                projection_version = str(payload.get("projection_version") or "UNKNOWN")
                topology_version_label = str(topology_version or "UNKNOWN")
                projection_versions[projection_version] += 1
                topology_versions[topology_version_label] += 1
                if status == "READY":
                    normalized_topology = (
                        str(topology_version) if topology_version is not None else None
                    )
                    if observed_topology and normalized_topology != expected_topology_version:
                        raise RuntimeError("topology version changed during benchmark sampling")
                    observed_topology = True
                    expected_topology_version = normalized_topology
        return elapsed

    overview = _measure(
        lambda: measured_get(overview_path, pinned_headers),
        warmups=options.warmups,
        repetitions=options.repetitions,
    )

    def concurrent_overview_batch(
        pool: ThreadPoolExecutor,
    ) -> list[tuple[str | None, float | None]]:
        return list(
            pool.map(
                lambda _index: _timed_outcome(
                    lambda: measured_get(overview_path, pinned_headers)
                ),
                range(10),
            )
        )

    concurrent_samples: list[float] = []
    concurrent_errors: list[str] = []
    with ThreadPoolExecutor(max_workers=10, thread_name_prefix="nocpro-benchmark") as pool:
        for _ in range(options.warmups):
            warmup = concurrent_overview_batch(pool)
            if any(error_type is not None for error_type, _ in warmup):
                raise RuntimeError("concurrent benchmark warmup failed")
        for _ in range(options.repetitions):
            for error_type, elapsed in concurrent_overview_batch(pool):
                if error_type is not None:
                    concurrent_errors.append(error_type)
                elif elapsed is not None:
                    concurrent_samples.append(elapsed)

    return {
        "contract": "warm-chain-benchmark-v2",
        "mode": "read-only",
        "scope": "PINNED_API_READS_ONLY",
        "origin": "LIVE_API_RESPONSE" if get is get_json else "TEST_INJECTED_RESPONSE",
        "production_validation": "NOT_ESTABLISHED",
        "api_url": options.api_url,
        "chain_id": options.chain_id,
        "snapshot_id": options.snapshot_id,
        "snapshot_version": options.snapshot_version,
        "repetitions": options.repetitions,
        "warmups": options.warmups,
        "preflight_seconds": preflight_seconds,
        "measurements": {
            "overview_projection": overview,
            "overview_projection_statuses": dict(sorted(projection_states.items())),
            "projection_versions": dict(sorted(projection_versions.items())),
            "topology_versions": dict(sorted(topology_versions.items())),
            "topology_version": expected_topology_version if observed_topology else None,
            "topology_version_stable": (
                len(set(topology_versions) - {"UNKNOWN"}) <= 1
                if observed_topology
                else None
            ),
            "concurrent_overview_10": summarize_samples(
                concurrent_samples, concurrent_errors
            ),
        },
        "not_measured": {
            "chain_list": "GET /chains may enqueue snapshot-wide quality precomputation",
            "chain_analysis": "GET /chains/{id} may persist newly resolved mappings",
            "deep_dive": "GET may flush pending persistence; no side-effect-free contract is exposed",
            "review": "GET may flush persistence and invoke provider enrichment",
            "reason": "Read-only mode intentionally measures only routes verified as persisted reads",
        },
        "safety": {
            "docker_subprocesses": 0,
            "database_connections_opened_by_benchmark": 0,
            "http_methods": ["GET"],
            "jobs_submitted_by_benchmark_requests": 0,
            "target_stack_mutations_requested": False,
            "benchmark_report_file_written": True,
            "provider_calls_requested_by_benchmark": 0,
        },
        "machine": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "memory_bytes": _physical_memory_bytes(),
        },
        "provider_mode": "NOT_USED_BY_MEASURED_ENDPOINTS",
        "background_load": "NOT_MEASURED",
        "dataset_hash": "NOT_EXPOSED_BY_READ_ONLY_API",
        "commit": os.environ.get("HINDSIGHT_BENCHMARK_COMMIT"),
        "budgets": {
            "overview_projection_p95_ms": 300,
            "overview_projection_p95_pass": _budget_pass(overview, 0.300),
            "concurrent_overview_10_p95_ms": 750,
            "concurrent_overview_10_p95_pass": _budget_pass(
                summarize_samples(concurrent_samples, concurrent_errors), 0.750
            ),
        },
    }


def _physical_memory_bytes() -> int | None:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def _budget_pass(summary: dict[str, object], seconds: float) -> bool | None:
    p95 = summary.get("p95_s")
    if p95 is None or summary.get("error_count", 0):
        return None
    return float(p95) <= seconds


def _timed_outcome(call: Callable[[], float]) -> tuple[str | None, float | None]:
    try:
        return None, call()
    except (OSError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
        return type(exc).__name__, None


def persistence_payload(template: dict, *, job_id: str) -> dict:
    """Clone one terminal Review under a unique identity for acceptance writes."""
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


def _loopback_host(host: str | None) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"}


def _inspect_stack(options: BenchmarkOptions) -> tuple[str, str]:
    """Return verified API/Postgres container IDs for an isolated stack."""
    assert options.compose_project is not None
    if "acceptance" not in options.compose_project.lower():
        raise ValueError("refusing disruption outside an explicitly named acceptance project")
    if options.compose_project in {"nocpro", "hindsight", "default"}:
        raise ValueError("refusing to restart a non-acceptance Compose project")
    compose = [
        "docker",
        "compose",
        "-p",
        options.compose_project,
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.dev.yml",
    ]
    def service_container(service: str) -> str:
        result = subprocess.run(
            [*compose, "ps", "-q", service],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(ids) != 1:
            raise RuntimeError(
                f"acceptance stack must have exactly one {service} container"
            )
        return ids[0]

    api_id = service_container("api")
    postgres_id = service_container("postgres")

    def inspect(container_id: str) -> tuple[dict, dict]:
        labels_raw = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Config.Labels}}", container_id],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        ports_raw = subprocess.run(
            ["docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", container_id],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return json.loads(labels_raw), json.loads(ports_raw)

    api_labels, api_ports = inspect(api_id)
    db_labels, db_ports = inspect(postgres_id)
    for labels, expected_service in (
        (api_labels, "api"),
        (db_labels, "postgres"),
    ):
        if labels.get("com.docker.compose.project") != options.compose_project:
            raise RuntimeError("container Compose project label did not match the explicit acceptance project")
        if labels.get("com.docker.compose.service") != expected_service:
            raise RuntimeError("container Compose service label did not match the requested service")
        working_dir = labels.get("com.docker.compose.project.working_dir")
        if working_dir and Path(working_dir).resolve() != ROOT:
            raise RuntimeError("acceptance container was not created from this repository directory")

    api_uri = urlparse(options.api_url)
    db_uri = urlparse(options.database_url or "")
    if not _loopback_host(api_uri.hostname) or not _loopback_host(db_uri.hostname):
        raise ValueError("acceptance restart is limited to loopback-published API and PostgreSQL ports")
    if str(api_uri.port or 80) not in _published_loopback_ports(
        api_ports, "8000/tcp"
    ):
        raise RuntimeError("API URL port is not published by the verified acceptance API container")
    if str(db_uri.port or 5432) not in _published_loopback_ports(
        db_ports, "5432/tcp"
    ):
        raise RuntimeError("database URL port is not published by the verified acceptance PostgreSQL container")
    expected_database = db_uri.path.lstrip("/")
    actual_database = asyncio.run(_current_database(options.database_url or ""))
    if actual_database != expected_database:
        raise RuntimeError("PostgreSQL current_database() differs from the explicitly configured database URL")
    return api_id, postgres_id


def _published_loopback_ports(ports: dict, container_port: str) -> set[str]:
    bindings = ports.get(container_port) or []
    return {
        str(binding.get("HostPort"))
        for binding in bindings
        if isinstance(binding, dict)
        and binding.get("HostPort")
        and _loopback_host(str(binding.get("HostIp") or ""))
    }


def _assert_provider_disabled(api_container_id: str) -> None:
    environment_raw = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .Config.Env}}",
            api_container_id,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    try:
        environment = json.loads(environment_raw)
    except json.JSONDecodeError:
        raise RuntimeError("could not verify provider configuration for acceptance API") from None
    if not isinstance(environment, list):
        raise RuntimeError("could not verify provider configuration for acceptance API")
    provider_is_configured = any(
        key in {"AI_API_KEY", "AI_BASE_URL"} and value.strip()
        for item in environment
        if isinstance(item, str)
        for key, separator, value in [item.partition("=")]
        if separator
    )
    if provider_is_configured:
        raise RuntimeError(
            "acceptance Review hydration requires AI_API_KEY and AI_BASE_URL to be unset"
        )


async def _current_database(database_url: str) -> str:
    from sqlalchemy import text

    from nocpro_api.persistence import Database

    normalized = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    database = Database(normalized)
    try:
        async with database.sessions() as session:
            return str((await session.execute(text("SELECT current_database()"))).scalar_one())
    except Exception as exc:
        raise RuntimeError(
            f"could not verify acceptance database identity ({type(exc).__name__})"
        ) from None
    finally:
        await database.close()


def _measure_persistence(
    template: dict,
    *,
    repetitions: int,
    database_url: str,
) -> list[float]:
    from sqlalchemy import delete, func, select

    from nocpro_api.persistence import Database, SnapshotRepository
    from nocpro_api.persistence.models import CounterfactualJobRecord

    normalized = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    database = Database(normalized)
    repository = SnapshotRepository(database.sessions)
    durations: list[float] = []
    job_ids: list[str] = []

    async def measure() -> None:
        try:
            for _ in range(repetitions):
                job_id = f"benchmark-persistence-{uuid4().hex}"
                job_ids.append(job_id)
                payload = persistence_payload(template, job_id=job_id)
                started = time.perf_counter()
                stored = await repository.persist_counterfactual_job(payload)
                durations.append(time.perf_counter() - started)
                if stored.job_id != payload["job_id"] or stored.status != "SUCCEEDED":
                    raise RuntimeError("Review persistence read-back did not match the write")
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
                        raise RuntimeError(f"failed to clean up {remaining} benchmark rows")
            finally:
                await database.close()

    try:
        asyncio.run(measure())
    except Exception as exc:
        raise RuntimeError(
            f"acceptance persistence measurement failed ({type(exc).__name__})"
        ) from None
    return durations


def _wait_health(options: BenchmarkOptions) -> float:
    started = time.perf_counter()
    deadline = started + 60
    while time.perf_counter() < deadline:
        try:
            payload, _ = get_json(options.api_url, "/api/v1/health")
            if payload:
                return time.perf_counter() - started
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(0.2)
    raise RuntimeError("verified acceptance API did not recover within 60 seconds")


def _verified_review_identity(payload: dict, options: BenchmarkOptions) -> tuple[dict, dict]:
    analysis_identity = payload.get("analysis_identity")
    artifact_revision = payload.get("artifact_revision")
    review_identity = payload.get("identity")
    if (
        not isinstance(analysis_identity, dict)
        or not isinstance(artifact_revision, dict)
        or not isinstance(review_identity, dict)
    ):
        raise RuntimeError("persisted Review has no complete analysis identity and artifact revision")
    if (
        analysis_identity.get("identity_version") != "analysis-identity-v1"
        or str(analysis_identity.get("snapshot_id", "")) != options.snapshot_id
        or str(analysis_identity.get("snapshot_version", "")) != options.snapshot_version
        or str(analysis_identity.get("chain_id", "")) != options.chain_id
        or not analysis_identity.get("pipeline_version")
        or not analysis_identity.get("input_fingerprint")
        or analysis_identity.get("analysis_config_version")
        != review_identity.get("analysis_version")
        or analysis_identity.get("review_config_version")
        != review_identity.get("config_version")
        or analysis_identity.get("pipeline_version") != review_identity.get("engine_version")
        or analysis_identity.get("input_fingerprint")
        != review_identity.get("tier1b_artifact_fingerprint")
        or analysis_identity.get("topology_version")
        != review_identity.get("topology_version")
        or artifact_revision.get("resource_kind") != "counterfactual_review"
        or not artifact_revision.get("fingerprint")
    ):
        raise RuntimeError("persisted Review identity does not match the pinned acceptance target")
    return analysis_identity, artifact_revision


def _acceptance_latest_review(options: BenchmarkOptions) -> tuple[dict, float]:
    path = f"/api/v1/chains/{quote(options.chain_id, safe='')}/review"
    payload, elapsed = get_json(
        options.api_url,
        path,
        headers=request_headers(options),
    )
    if payload.get("status") != "SUCCEEDED" or not isinstance(payload.get("result"), dict):
        raise RuntimeError("no compatible persisted SUCCEEDED Review exists for acceptance")
    identity = payload.get("identity", {})
    if (
        str(identity.get("snapshot_id", "")) != options.snapshot_id
        or str(identity.get("snapshot_version", "")) != options.snapshot_version
        or str(payload.get("chain_id", "")) != options.chain_id
    ):
        raise RuntimeError("persisted Review identity does not match the pinned acceptance target")
    _verified_review_identity(payload, options)
    return payload, elapsed


def _acceptance_review(
    options: BenchmarkOptions,
    job_id: str,
    expected_analysis_identity: dict,
    expected_artifact_revision: dict,
) -> tuple[dict, float]:
    path = f"/api/v1/review-jobs/{quote(job_id, safe='')}"
    payload, elapsed = get_json(
        options.api_url,
        path,
        headers=request_headers(options),
    )
    if payload.get("status") != "SUCCEEDED" or not isinstance(payload.get("result"), dict):
        raise RuntimeError("no compatible persisted SUCCEEDED Review exists for acceptance")
    identity = payload.get("identity", {})
    if (
        str(identity.get("snapshot_id", "")) != options.snapshot_id
        or str(identity.get("snapshot_version", "")) != options.snapshot_version
        or str(payload.get("chain_id", "")) != options.chain_id
    ):
        raise RuntimeError("persisted Review identity does not match the pinned acceptance target")
    actual_analysis_identity, actual_artifact_revision = _verified_review_identity(
        payload, options
    )
    if (
        actual_analysis_identity != expected_analysis_identity
        or actual_artifact_revision != expected_artifact_revision
    ):
        raise RuntimeError("persisted Review analysis identity changed during API restart")
    return payload, elapsed


def _run_acceptance_restart(options: BenchmarkOptions) -> dict:
    if not options.allow_disruption or not options.compose_project or not options.database_url:
        raise ValueError("acceptance-restart requires explicit disruption, project, and database identity")
    api_container_id, _ = _inspect_stack(options)
    _assert_provider_disabled(api_container_id)
    catalog, _ = get_json(
        options.api_url, READ_ONLY_ENDPOINTS["snapshot_catalog"]
    )
    _assert_active_identity(catalog, options)
    template, _ = _acceptance_latest_review(options)
    expected_analysis_identity, expected_artifact_revision = _verified_review_identity(
        template, options
    )
    persistence = _measure_persistence(
        template,
        repetitions=options.repetitions,
        database_url=options.database_url,
    )

    restart_to_health: list[float] = []
    hydrate: list[float] = []
    for _ in range(options.repetitions):
        subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                options.compose_project,
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.dev.yml",
                "restart",
                "api",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        restart_to_health.append(_wait_health(options))
        _, elapsed = _acceptance_review(
            options,
            str(template["job_id"]),
            expected_analysis_identity,
            expected_artifact_revision,
        )
        hydrate.append(elapsed)

    return {
        "contract": "warm-chain-benchmark-v2",
        "mode": "acceptance-restart",
        "scope": "ISOLATED_LOCAL_COMPOSE_ACCEPTANCE_ONLY",
        "production_validation": "NOT_ESTABLISHED",
        "compose_project": options.compose_project,
        "chain_id": options.chain_id,
        "snapshot_id": options.snapshot_id,
        "snapshot_version": options.snapshot_version,
        "repetitions": options.repetitions,
        "measurements": {
            "review_persistence": summarize_samples(persistence),
            "restart_to_health": summarize_samples(restart_to_health),
            "persisted_review_hydration": summarize_samples(hydrate),
        },
        "safety": {
            "disruption_explicitly_authorized_by_flag": True,
            "database_identity_verified": True,
            "api_and_database_containers_verified_in_project": True,
            "provider_disabled_by_container_configuration": True,
            "latest_review_route_may_flush_pending_review_persistence": True,
            "benchmark_review_rows_cleaned": True,
        },
    }


def run(options: BenchmarkOptions | None = None) -> dict:
    options = options or parse_options()
    if options.output.exists() and not options.overwrite:
        raise FileExistsError(
            "benchmark output already exists; choose another --output or pass --overwrite"
        )
    result = (
        _run_read_only(options)
        if options.mode == "read-only"
        else _run_acceptance_restart(options)
    )
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run()
