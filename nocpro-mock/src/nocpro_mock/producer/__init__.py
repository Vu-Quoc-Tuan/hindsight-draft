"""Output producers. Direct Snapshot first; Kafka is a later optional adapter."""

from .direct_snapshot import DirectSnapshotProducer

__all__ = ["DirectSnapshotProducer"]
