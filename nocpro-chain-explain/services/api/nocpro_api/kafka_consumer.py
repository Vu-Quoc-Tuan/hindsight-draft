from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition

from .ingest import SnapshotEventError, parse_snapshot_event
from .persistence import SnapshotRepository
from .tier1a_coordinator import Tier1ACoordinator


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class KafkaConsumerConfig:
    bootstrap_servers: str
    topic: str = "nocpro.snapshot.v1"
    dlq_topic: str = "nocpro.snapshot.v1.dlq"
    group_id: str = "nocpro-chain-explain"
    retry_backoff_seconds: float = 1.0
    max_chunks: int = 1024
    max_chunk_bytes: int = 4 * 1024 * 1024
    max_uncompressed_bytes: int = 256 * 1024 * 1024


class KafkaSnapshotConsumer:
    def __init__(
        self,
        config: KafkaConsumerConfig,
        repository: SnapshotRepository,
        coordinator: Tier1ACoordinator,
    ) -> None:
        self.config = config
        self.repository = repository
        self.coordinator = coordinator
        self.consumer = AIOKafkaConsumer(
            config.topic,
            bootstrap_servers=config.bootstrap_servers,
            group_id=config.group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_partition_fetch_bytes=8 * 1024 * 1024,
            fetch_max_bytes=32 * 1024 * 1024,
        )
        self.dlq = AIOKafkaProducer(
            bootstrap_servers=config.bootstrap_servers,
            enable_idempotence=True,
            max_request_size=8 * 1024 * 1024,
        )
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.consumer.start()
        await self.dlq.start()
        self.task = asyncio.create_task(self._run(), name="snapshot-kafka-consumer")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.consumer.stop()
        await self.dlq.stop()

    async def _run(self) -> None:
        async for message in self.consumer:
            while True:
                try:
                    await self.process_message(message)
                    break
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "transient snapshot processing failure at %s/%s/%s; retrying",
                        message.topic,
                        message.partition,
                        message.offset,
                    )
                    await asyncio.sleep(self.config.retry_backoff_seconds)

    async def process_message(self, message) -> None:
        raw: dict[str, Any] | None = None
        try:
            raw = json.loads(message.value)
            event = parse_snapshot_event(
                raw,
                max_chunks=self.config.max_chunks,
                max_chunk_bytes=self.config.max_chunk_bytes,
                max_uncompressed_bytes=self.config.max_uncompressed_bytes,
            )
            expected_key = event.snapshot_id.encode("utf-8")
            if message.key != expected_key:
                raise SnapshotEventError("Kafka key must equal snapshot_id")
        except (UnicodeDecodeError, json.JSONDecodeError, SnapshotEventError) as exc:
            if isinstance(raw, dict):
                snapshot_id = raw.get("snapshot_id")
                snapshot_version = raw.get("snapshot_version")
                if isinstance(snapshot_id, str) and isinstance(snapshot_version, str):
                    await self.repository.invalidate(
                        snapshot_id, snapshot_version, str(exc)
                    )
            await self._publish_dlq(message, str(exc))
            await self._commit(message)
            return

        result = await self.repository.record_kafka_event(
            event,
            topic=message.topic,
            partition=message.partition,
            offset=message.offset,
        )
        if result.status == "INVALID":
            await self._publish_dlq(message, result.invalid_reason or "invalid")
        # COMPLETE leaves a durable PENDING claim.  The recovery worker owns
        # logical-oldest scheduling; the consumer must not bypass that order.
        await self._commit(message)

    async def _commit(self, message) -> None:
        await self.consumer.commit(
            {
                TopicPartition(message.topic, message.partition): message.offset + 1
            }
        )

    async def _publish_dlq(self, message, reason: str) -> None:
        value = json.dumps(
            {
                "schema_version": "v1",
                "error": reason,
                "source_topic": message.topic,
                "source_partition": message.partition,
                "source_offset": message.offset,
                "original_value": message.value.decode("utf-8", errors="replace"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        await self.dlq.send_and_wait(
            self.config.dlq_topic, key=message.key, value=value
        )
