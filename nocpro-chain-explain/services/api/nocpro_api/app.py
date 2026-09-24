"""FastAPI application factory with no analysis logic in the transport layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routes import router
from .workspace import Workspace
from .kafka_consumer import KafkaConsumerConfig, KafkaSnapshotConsumer
from .kafka_topology_consumer import KafkaTopologyConsumer, KafkaTopologyConsumerConfig
from .persistence import Database, SnapshotRepository, TopologyRepository
from .runtime_env import load_project_environment
from .tier1a_coordinator import Tier1ACoordinator
from .quality_background import SnapshotQualityRunner


load_project_environment()

LOGGER = logging.getLogger(__name__)


async def _recovery_loop(
    coordinator: Tier1ACoordinator,
    interval_seconds: float,
    receiving_ttl_seconds: int,
) -> None:
    while True:
        try:
            await coordinator.repository.expire_receiving(
                ttl_seconds=receiving_ttl_seconds
            )
            while await coordinator.run_pending_once() is not None:
                pass
            while await coordinator.run_lineage_pending_once() is not None:
                pass
            while await coordinator.run_similarity_pending_once() is not None:
                pass
            await coordinator.hydrate_active()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Tier-1A recovery iteration failed; retrying")
        await asyncio.sleep(interval_seconds)


def create_app(*, workspace: Workspace | None = None) -> FastAPI:
    service = workspace or Workspace()

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        database = None
        consumer = None
        topology_consumer = None
        recovery_task = None
        quality_runner = None
        database_url = os.environ.get("DATABASE_URL")
        if database_url:
            database = Database(database_url)
            repository = SnapshotRepository(
                database.sessions,
                max_compressed_snapshot_bytes=int(
                    os.environ.get(
                        "KAFKA_MAX_COMPRESSED_BYTES", str(256 * 1024 * 1024)
                    )
                ),
            )
            topology_repository = TopologyRepository(database.sessions)
            app_instance.state.topology_repository = topology_repository
            coordinator = Tier1ACoordinator(
                repository,
                service,
                max_attempts=int(os.environ.get("TIER1A_MAX_ATTEMPTS", "5")),
                backoff_base_seconds=int(
                    os.environ.get("TIER1A_BACKOFF_BASE_SECONDS", "2")
                ),
                chunk_retention_mode=service.config.chunk_retention.mode,
                topology_repository=topology_repository,
            )
            if hasattr(repository, "interrupt_orphaned_analysis_jobs"):
                interrupted = await repository.interrupt_orphaned_analysis_jobs()
            else:
                # Keep lightweight lifespan fakes usable in API tests and
                # integrations that provide only the repository surface they
                # need; the real SnapshotRepository always has this method.
                interrupted = (0, 0)
            if any(interrupted):
                LOGGER.info(
                    "Interrupted orphaned analysis jobs after restart: deep_dive=%s counterfactual=%s",
                    interrupted[0],
                    interrupted[1],
                )
            service.attach_persistence(repository, coordinator)
            # Calibration changes the active config version and invalidates
            # Tier-1A/Tier-2 caches.  It must happen before rehydrating READY
            # state; otherwise restart can serve a package built under the
            # previous config while new quality workers use the new version.
            if os.environ.get("AUTO_CALIBRATE_ON_STARTUP", "true").lower() in {"1", "true", "yes"}:
                try:
                    LOGGER.info("Starting auto-calibration from PostgreSQL before activation...")
                    report = await service.calibrate_from_database(include_fixtures=True)
                    LOGGER.info(
                        "Auto-calibration from PostgreSQL completed: status=%s, version=%s",
                        report.get("status"),
                        service.config.config_version,
                    )
                except Exception as e:
                    LOGGER.warning("Auto-calibration skipped or failed: %s", e)
            # READY remains available while older pending/stale work resumes in
            # the background.  Logical ordering is owned by the repository.
            await coordinator.hydrate_active()
        initial_snapshot_id = os.environ.get("NOCPRO_INITIAL_SNAPSHOT_ID", "").strip()
        if initial_snapshot_id:
            try:
                from .catalog import load_preset_payload

                payload, _ = load_preset_payload(initial_snapshot_id)
                await service.ingest_snapshot(payload)
                LOGGER.info("Activated configured initial snapshot: %s", initial_snapshot_id)
            except Exception:
                LOGGER.exception(
                    "Configured initial snapshot activation failed: %s",
                    initial_snapshot_id,
                )
        elif service.package is None and os.environ.get("AUTO_SEED_DEFAULT_SNAPSHOT", "true").lower() == "true":
            try:
                from .catalog import load_preset_payload
                payload, _ = load_preset_payload("real_alarm_20260907_demo")
                await service.ingest_snapshot(payload)
                LOGGER.info("Auto-seeded default snapshot: real_alarm_20260907_demo")
            except Exception:
                LOGGER.warning("Auto-seed default snapshot skipped or failed")

        # Start Kafka only after the explicit startup snapshot has claimed and
        # activated its Tier-1A row.  Starting the consumer first lets it race
        # the same claim and produces the misleading
        # ``Tier-1A snapshot claim was not acquired`` error in dev-demo.
        if database_url and os.environ.get("KAFKA_ENABLED", "false").lower() == "true":
            consumer = KafkaSnapshotConsumer(
                KafkaConsumerConfig(
                    bootstrap_servers=os.environ.get(
                        "KAFKA_BOOTSTRAP_SERVERS", "kafka:19092"
                    ),
                    topic=os.environ.get("KAFKA_SNAPSHOT_TOPIC", "nocpro.snapshot.v1"),
                    dlq_topic=os.environ.get(
                        "KAFKA_DLQ_TOPIC", "nocpro.snapshot.v1.dlq"
                    ),
                    max_chunks=int(os.environ.get("KAFKA_MAX_CHUNKS", "1024")),
                    max_chunk_bytes=int(
                        os.environ.get("KAFKA_MAX_CHUNK_BYTES", str(4 * 1024 * 1024))
                    ),
                    max_uncompressed_bytes=int(
                        os.environ.get(
                            "KAFKA_MAX_UNCOMPRESSED_BYTES", str(256 * 1024 * 1024)
                        )
                    ),
                ),
                repository,
                coordinator,
            )
            await consumer.start()

            topology_consumer = KafkaTopologyConsumer(
                KafkaTopologyConsumerConfig(
                    bootstrap_servers=os.environ.get(
                        "KAFKA_BOOTSTRAP_SERVERS", "kafka:19092"
                    ),
                    topic=os.environ.get(
                        "KAFKA_TOPOLOGY_TOPIC", "nocpro.topology.v1"
                    ),
                    dlq_topic=os.environ.get(
                        "KAFKA_TOPOLOGY_DLQ_TOPIC", "nocpro.topology.v1.dlq"
                    ),
                ),
                topology_repository,
                coordinator,
            )
            await topology_consumer.start()

        # The active workspace used to be the only place that queued Tier-2
        # quality work, which made merely opening a snapshot a prerequisite for
        # analysis.  Delegate automatic work to isolated per-snapshot workers
        # once durable persistence is available.  Keep the old active-workspace
        # fallback for the in-memory/demo mode and lightweight test doubles.
        if (
            database_url
            and getattr(service, "auto_chain_quality", False)
            and "repository" in locals()
            and hasattr(repository, "list_live_snapshots")
            and hasattr(repository, "ingest_direct")
            and hasattr(service, "set_quality_background_owner")
        ):
            quality_runner = SnapshotQualityRunner(
                repository,
                coordinator,
                config_path=service._base_config_path,
                config_template=service.config,
            )
            service.set_quality_background_owner(True)
            quality_runner.start()

        if (
            service.package is not None
            and service.auto_chain_quality
            and quality_runner is None
        ):
            queued = service.precompute_snapshot_deep_dive()
            LOGGER.info("Automatic deterministic quality precompute: %s", queued)

        # Initial activation and the recovery worker both claim pending Tier-1A
        # rows. Start recovery only after the explicit startup selection has
        # completed so this process cannot race itself for the same claim.
        if database_url:
            recovery_task = asyncio.create_task(
                _recovery_loop(
                    coordinator,
                    float(os.environ.get("TIER1A_RECOVERY_INTERVAL_SECONDS", "2")),
                    int(os.environ.get("KAFKA_RECEIVING_TTL_SECONDS", str(24 * 60 * 60))),
                ),
                name="tier1a-recovery-worker",
            )

        try:
            yield
        finally:
            if quality_runner is not None:
                await quality_runner.stop()
            if recovery_task is not None:
                recovery_task.cancel()
                with suppress(asyncio.CancelledError):
                    await recovery_task
            if consumer is not None:
                await consumer.stop()
            if topology_consumer is not None:
                await topology_consumer.stop()
            service.close()
            await service.flush_review_persistence()
            await service.flush_deep_dive_persistence()
            await service.flush_audit_persistence()
            if database is not None:
                await database.close()

    app = FastAPI(
        title="NocPro Chain Explain API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.workspace = service
    app.state.topology_repository = None
    app.state.snapshot_context_lock = asyncio.Lock()
    service._snapshot_context_lock = app.state.snapshot_context_lock

    @app.middleware("http")
    async def guard_workspace_snapshot_context(request, call_next):
        path = request.url.path
        is_chain_request = path == "/api/v1/chains" or path.startswith("/api/v1/chains/")
        is_snapshot_selection = (
            request.method == "POST"
            and path in {"/api/v1/snapshots", "/api/v1/snapshots/select"}
        )
        if request.method == "OPTIONS":
            return await call_next(request)

        lock = request.app.state.snapshot_context_lock
        if is_chain_request:
            expected_id = request.headers.get("x-nocpro-snapshot-id")
            expected_version = request.headers.get("x-nocpro-snapshot-version")
            expected_topology_version = request.headers.get("x-nocpro-topology-version")
            service = request.app.state.workspace

            def context_conflict(expected_generation=None, allow_topology_refresh=False):
                if expected_id is not None or expected_version is not None:
                    active_identity = service.active_identity()
                    package = service.current_package()
                    topology = getattr(package, "topology", None)
                    active_topology_version = (
                        topology.get("topology_version")
                        if isinstance(topology, dict)
                        else None
                    )
                    if active_topology_version is None and package is not None:
                        topology_ref = getattr(package.snapshot, "topology_ref", None)
                        active_topology_version = getattr(
                            topology_ref,
                            "topology_version",
                            None,
                        )
                    generation_changed = (
                        not allow_topology_refresh
                        and expected_generation is not None
                        and hasattr(service, "active_generation")
                        and service.active_generation() != expected_generation
                    )
                    topology_changed = (
                        not allow_topology_refresh
                        and expected_topology_version is not None
                        and expected_topology_version != str(active_topology_version or "")
                    )
                    if (
                        not expected_id
                        or not expected_version
                        or active_identity != (expected_id, expected_version)
                        or generation_changed
                        or topology_changed
                    ):
                        return JSONResponse(
                            status_code=409,
                            content={
                                "detail": "Active snapshot changed in another session; reload or select the intended snapshot before continuing.",
                                "active_snapshot_id": active_identity[0] if active_identity else None,
                                "active_snapshot_version": active_identity[1] if active_identity else None,
                            },
                        )
                return None

            if request.method not in {"GET", "HEAD"}:
                async with lock:
                    conflict = context_conflict()
                    if conflict is not None:
                        return conflict
                    return await call_next(request)

            generation = service.active_generation() if hasattr(service, "active_generation") else None
            allow_topology_refresh = path == "/api/v1/chains" and request.method == "GET"
            conflict = context_conflict(generation, allow_topology_refresh)
            if conflict is not None:
                return conflict
            response = await call_next(request)
            # Read-only handlers may await DB/LLM work. Do not hold the global
            # selection lock across that latency; instead discard a response
            # if another request switched the active workspace mid-flight.
            conflict = context_conflict(generation, allow_topology_refresh)
            return conflict if conflict is not None else response

        if is_snapshot_selection:
            async with lock:
                return await call_next(request)
        return await call_next(request)

    cors_env = os.environ.get("CORS_ORIGINS", "").strip()
    allow_origins = (
        [o.strip() for o in cors_env.split(",") if o.strip()]
        if cors_env
        else [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
