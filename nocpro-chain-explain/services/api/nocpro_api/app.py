"""FastAPI application factory with no analysis logic in the transport layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .workspace import Workspace
from .kafka_consumer import KafkaConsumerConfig, KafkaSnapshotConsumer
from .kafka_topology_consumer import KafkaTopologyConsumer, KafkaTopologyConsumerConfig
from .persistence import Database, SnapshotRepository, TopologyRepository
from .runtime_env import load_project_environment
from .tier1a_coordinator import Tier1ACoordinator


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
            service.attach_persistence(repository, coordinator)
            # READY remains available while older pending/stale work resumes in
            # the background.  Logical ordering is owned by the repository.
            await coordinator.hydrate_active()
            recovery_task = asyncio.create_task(
                _recovery_loop(
                    coordinator,
                    float(os.environ.get("TIER1A_RECOVERY_INTERVAL_SECONDS", "2")),
                    int(os.environ.get("KAFKA_RECEIVING_TTL_SECONDS", str(24 * 60 * 60))),
                ),
                name="tier1a-recovery-worker",
            )
            if os.environ.get("KAFKA_ENABLED", "false").lower() == "true":
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

        if database_url and os.environ.get("AUTO_CALIBRATE_ON_STARTUP", "true").lower() in {"1", "true", "yes"}:
            try:
                LOGGER.info("Starting background auto-calibration from PostgreSQL...")
                report = await service.calibrate_from_database(include_fixtures=True)
                LOGGER.info(
                    "Auto-calibration from PostgreSQL completed: status=%s, version=%s",
                    report.get("status"),
                    service.config.config_version,
                )
            except Exception as e:
                LOGGER.warning("Background auto-calibration skipped or failed: %s", e)
        try:
            yield
        finally:
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
