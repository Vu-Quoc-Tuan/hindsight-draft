"""Consumer for chunked, compressed topology stream over Kafka."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition

from .ingest.topology_wire import (
    TopologyWireEventError,
    parse_topology_wire_event,
)
from .persistence import TopologyRepository
from .tier1a_coordinator import Tier1ACoordinator

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class KafkaTopologyConsumerConfig:
    bootstrap_servers: str
    topic: str = "nocpro.topology.v1"
    dlq_topic: str = "nocpro.topology.v1.dlq"
    group_id: str = "nocpro-chain-explain-topology"
    retry_backoff_seconds: float = 1.0


class KafkaTopologyConsumer:
    """Consumes nocpro.topology.v1, deduplicates atomically, and materializes versioned graphs in DB."""

    def __init__(
        self,
        config: KafkaTopologyConsumerConfig,
        repository: TopologyRepository,
        coordinator: Tier1ACoordinator | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.coordinator = coordinator
        self.consumer = AIOKafkaConsumer(
            self.config.topic,
            bootstrap_servers=self.config.bootstrap_servers,
            group_id=self.config.group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_partition_fetch_bytes=8 * 1024 * 1024,
        )
        self.dlq = AIOKafkaProducer(bootstrap_servers=self.config.bootstrap_servers)
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        await self.consumer.start()
        await self.dlq.start()
        self._running = True
        self._task = asyncio.create_task(self._consume_loop(), name="kafka-topology-consumer")
        LOGGER.info("Kafka topology consumer started on topic %s", self.config.topic)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.consumer.stop()
        await self.dlq.stop()
        LOGGER.info("Kafka topology consumer stopped")

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                msg_batch = await self.consumer.getmany(timeout_ms=1000, max_records=10)
                for _tp, messages in msg_batch.items():
                    for message in messages:
                        await self.process_message(message)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                LOGGER.error("Topology consumer batch iteration failed: %s", exc)
                await asyncio.sleep(self.config.retry_backoff_seconds)

    async def process_message(self, message) -> None:
        key_str = message.key.decode("utf-8") if message.key else None

        # 1. Parse JSON
        try:
            raw = json.loads(message.value)
            if not isinstance(raw, dict):
                raise TopologyWireEventError("Payload must be a JSON object")
        except Exception as exc:
            LOGGER.error("Unparseable JSON topology event at %s/%s/%s: %s", message.topic, message.partition, message.offset, exc)
            await self._publish_dlq(message, f"Invalid JSON: {exc}")
            await self._commit(message)
            return

        # 2. Parse canonical wire envelope
        try:
            event = parse_topology_wire_event(raw)
        except TopologyWireEventError as exc:
            LOGGER.error("Contract violation in topology event at %s/%s/%s: %s", message.topic, message.partition, message.offset, exc)
            await self._publish_dlq(message, f"Contract violation: {exc}")
            await self._commit(message)
            return

        # 3. Validate message key (supports both profile_id and profile_id:topology_version)
        if message.key:
            expected_keys = {
                event.profile_id.encode("utf-8"),
                f"{event.profile_id}:{event.topology_version}".encode("utf-8"),
            }
            if message.key not in expected_keys:
                err = f"Message key {message.key!r} not in expected {expected_keys!r}"
                LOGGER.error(err)
                await self._publish_dlq(message, err)
                await self._commit(message)
                return

        # 4. Atomic ingest & deduplication
        try:
            committed = await self.repository.process_kafka_event(
                event,
                topic=message.topic,
                partition=message.partition,
                offset=message.offset,
                message_key=key_str,
            )
            if committed is not None and self.coordinator is not None:
                profile_id, topology_version = committed
                await self.coordinator.wake_pending_topology(profile_id, topology_version)
        except ValueError as exc:
            # Fatal payload corruption / checksum mismatch -> DLQ and commit
            LOGGER.error("Payload corruption in topology event at %s/%s/%s: %s", message.topic, message.partition, message.offset, exc)
            await self._publish_dlq(message, f"Payload corruption: {exc}")
            await self._commit(message)
            return
        except Exception:
            # Operational database or transient error -> do NOT commit, re-raise to retry
            LOGGER.exception("Transient database failure processing topology event at %s/%s/%s; retrying", message.topic, message.partition, message.offset)
            raise

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
                "raw_key": message.key.decode("utf-8", errors="replace") if message.key else None,
                "raw_value": message.value.decode("utf-8", errors="replace") if message.value else None,
            }
        ).encode("utf-8")
        await self.dlq.send_and_wait(self.config.dlq_topic, key=message.key, value=value)
