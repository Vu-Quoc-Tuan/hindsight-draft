"""Transport-neutral snapshot ingest primitives."""

from .wire import SnapshotEventError, parse_snapshot_event

__all__ = ["SnapshotEventError", "parse_snapshot_event"]
