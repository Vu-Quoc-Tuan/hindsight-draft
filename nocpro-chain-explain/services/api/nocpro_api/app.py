"""FastAPI application factory with no analysis logic in the transport layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .workspace import Workspace
from .kafka_consumer import KafkaConsumerConfig, KafkaSnapshotConsumer
from .persistence import Database, SnapshotRepository
from .tier1a_coordinator import Tier1ACoordinator


def create_app(*, workspace: Workspace | None = None) -> FastAPI:
    service = workspace or Workspace()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database = None
        consumer = None
        database_url = os.environ.get("DATABASE_URL")
        if database_url:
            database = Database(database_url)
            repository = SnapshotRepository(database.sessions)
            coordinator = Tier1ACoordinator(repository, service)
            service.attach_persistence(repository, coordinator)
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
                    ),
                    repository,
                    coordinator,
                )
                await consumer.start()
        try:
            yield
        finally:
            if consumer is not None:
                await consumer.stop()
            if database is not None:
                await database.close()
            service.close()

    app = FastAPI(
        title="NocPro Chain Explain API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.workspace = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
