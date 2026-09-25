"""Pure counting core for repeated device/fault alarms."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


@dataclass(frozen=True)
class AlarmOccurrence:
    """One alarm observation from one snapshot."""

    source_id: str
    alarm_id: str
    device_code: str | None
    fault_id: str | None
    occurred_at: datetime | None
    snapshot_id: str | None = None
    snapshot_version: str | None = None


@dataclass(frozen=True)
class OccurrenceEvidence:
    source_id: str
    alarm_id: str
    occurred_at: datetime
    snapshots: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class RecurrenceGroup:
    device_code: str
    fault_id: str
    occurrences: tuple[OccurrenceEvidence, ...]

    @property
    def count(self) -> int:
        return len(self.occurrences)

    @property
    def first_seen(self) -> datetime:
        return self.occurrences[0].occurred_at

    @property
    def last_seen(self) -> datetime:
        return self.occurrences[-1].occurred_at


@dataclass(frozen=True)
class RecurrenceCountResult:
    as_of: datetime
    window_start: datetime | None
    groups: tuple[RecurrenceGroup, ...]
    duplicate_observations: int
    conflicting_event_keys: int
    skipped_observations: int


def _text(value: str | None) -> str | None:
    value = value.strip() if isinstance(value, str) else ""
    return value or None


def _utc(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    if value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def count_alarm_recurrences(
    observations: Iterable[AlarmOccurrence],
    *,
    as_of: datetime,
    window: timedelta | None = None,
) -> RecurrenceCountResult:
    """Count distinct ``(device_code, fault_id)`` events in available history.

    An event is keyed by ``(source_id, alarm_id, occurred_at)`` so repeated
    copies across snapshots count once. Conflicting device/fault mappings are
    excluded. Times must be timezone-aware; callers must resolve local times.
    By default all supplied history through ``as_of`` is counted. Set ``window``
    to bound the count to a trailing interval. An empty result does not prove
    complete history coverage or device health.
    """
    as_of_utc = _utc(as_of)
    if as_of_utc is None:
        raise ValueError("as_of must be timezone-aware")
    if window is not None and (
        not isinstance(window, timedelta) or window <= timedelta(0)
    ):
        raise ValueError("window must be a positive timedelta")

    window_start = as_of_utc - window if window is not None else None
    # key -> [device, fault, set of snapshots]
    events: dict[
        tuple[str, str, datetime],
        tuple[str, str, set[tuple[str, str | None]]],
    ] = {}
    conflicts: set[tuple[str, str, datetime]] = set()
    duplicates = skipped = 0

    for row in observations:
        source, alarm = _text(row.source_id), _text(row.alarm_id)
        device, fault = _text(row.device_code), _text(row.fault_id)
        occurred_at = _utc(row.occurred_at)
        if (
            source is None
            or alarm is None
            or device is None
            or fault is None
            or occurred_at is None
        ):
            skipped += 1
            continue

        key = (source, alarm, occurred_at)
        if key in conflicts:
            duplicates += 1
            continue

        snapshot = _text(row.snapshot_id)
        refs = {(snapshot, _text(row.snapshot_version))} if snapshot else set()
        previous = events.get(key)
        if previous is None:
            events[key] = (device, fault, refs)
            continue

        duplicates += 1
        old_device, old_fault, old_refs = previous
        if (old_device, old_fault) != (device, fault):
            conflicts.add(key)
            del events[key]
        else:
            old_refs.update(refs)

    grouped: dict[tuple[str, str], list[OccurrenceEvidence]] = defaultdict(list)
    for (source, alarm, occurred_at), (device, fault, refs) in events.items():
        if occurred_at <= as_of_utc and (
            window_start is None or window_start <= occurred_at
        ):
            snapshots = tuple(sorted(refs, key=lambda ref: (ref[0], ref[1] or "")))
            grouped[(device, fault)].append(
                OccurrenceEvidence(source, alarm, occurred_at, snapshots)
            )

    groups = []
    for (device, fault), occurrences in sorted(grouped.items()):
        occurrences.sort(key=lambda item: (item.occurred_at, item.source_id, item.alarm_id))
        groups.append(RecurrenceGroup(device, fault, tuple(occurrences)))

    return RecurrenceCountResult(
        as_of=as_of_utc,
        window_start=window_start,
        groups=tuple(groups),
        duplicate_observations=duplicates,
        conflicting_event_keys=len(conflicts),
        skipped_observations=skipped,
    )
