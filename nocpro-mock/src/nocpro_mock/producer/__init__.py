"""Output producers. Direct Snapshot first; Kafka is a later optional adapter."""

from .direct_snapshot import DirectSnapshotProducer

__all__ = ["DirectSnapshotProducer"]
from .kafka_snapshot import (
    KafkaSnapshotConfig,
    SnapshotWireBatch,
    build_snapshot_wire_batch,
    publish_snapshot,
)

__all__ = [
    "KafkaSnapshotConfig",
    "SnapshotWireBatch",
    "build_snapshot_wire_batch",
    "publish_snapshot",
]
