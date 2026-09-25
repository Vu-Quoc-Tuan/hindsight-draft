"""Build source-grounded recurrence summaries for the active chain."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, literal_column, or_, select, tuple_

from recurrent_alarms import AlarmOccurrence, count_alarm_recurrences

from .persistence.models import Alarm, Snapshot, SnapshotIngest
from libs.contracts.topology_identity import snapshot_topology_profile


LOGGER = logging.getLogger(__name__)
_FUTURE_OUTLIER = "TIMESTAMP_FUTURE_OUTLIER"
_MAX_OCCURRENCES_PER_GROUP = 50


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value") and isinstance(value.value, str):
        value = value.value
    normalized = str(value).strip()
    return normalized or None


def _parse_time(value: Any, *, profile_id: str) -> tuple[datetime | None, bool]:
    """Parse event time, applying the existing UTC convention only to IP."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None, False
    else:
        return None, False

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if profile_id.upper() != "IP_NETWORK":
            return None, False
        return parsed.replace(tzinfo=timezone.utc), True
    return parsed.astimezone(timezone.utc), False


def _make_occurrence(
    *,
    source_id: str,
    alarm_id: Any,
    device_code: Any,
    fault_id: Any,
    occurred_at: Any,
    snapshot_id: Any,
    snapshot_version: Any,
    quality_flags: Any,
    profile_id: str,
) -> tuple[AlarmOccurrence, bool]:
    event_time, assumed_utc = _parse_time(occurred_at, profile_id=profile_id)
    flags = quality_flags if isinstance(quality_flags, (list, tuple, set)) else ()
    if _FUTURE_OUTLIER in flags:
        event_time = None
        assumed_utc = False
    return (
        AlarmOccurrence(
            source_id=source_id,
            alarm_id=_text(alarm_id) or "",
            device_code=_text(device_code),
            fault_id=_text(fault_id),
            occurred_at=event_time,
            snapshot_id=_text(snapshot_id),
            snapshot_version=_text(snapshot_version),
        ),
        assumed_utc,
    )


async def chain_recurrence_history(
    package: Any,
    *,
    chain_id: str,
    repository: Any | None,
) -> dict[str, Any]:
    """Count device/fault observations in matching persisted and active data.

    The source/profile scope prevents similarly named devices in unrelated
    datasets from being mixed. The active package is included even when it is
    a file-backed preset that has not been persisted to PostgreSQL.
    """
    if chain_id not in package.chains:
        raise KeyError(f"Unknown chain_id: {chain_id!r}")

    snapshot = package.snapshot
    snapshot_id = str(snapshot.snapshot_id)
    snapshot_version = str(snapshot.snapshot_version)
    source = _text(snapshot.source) or ""
    source_kind = _text(snapshot.source_kind) or ""
    topology_ref = getattr(snapshot, "topology_ref", None)
    explicit_profile = (
        topology_ref.get("profile_id")
        if isinstance(topology_ref, dict)
        else getattr(topology_ref, "profile_id", None)
    )
    profile_id = (
        snapshot_topology_profile(
            snapshot_id,
            _text(explicit_profile),
        )
        or ""
    )

    targets: set[tuple[str, str]] = set()
    unmatched_chain_alarm_count = 0
    for alarm in package.alarms_of(chain_id):
        device = _text(alarm.device_code)
        fault = _text((alarm.raw or {}).get("fault_id"))
        if device and fault:
            targets.add((device, fault))
        else:
            unmatched_chain_alarm_count += 1

    observations: list[AlarmOccurrence] = []
    assumed_utc_count = 0
    seen_snapshots: set[tuple[str, str]] = {(snapshot_id, snapshot_version)}
    for alarm in package.alarms.values():
        device = _text(alarm.device_code)
        fault = _text((alarm.raw or {}).get("fault_id"))
        if not device or not fault or (device, fault) not in targets:
            continue
        occurrence, assumed_utc = _make_occurrence(
            source_id=source or source_kind or "unknown-source",
            alarm_id=alarm.alarm_id,
            device_code=device,
            fault_id=fault,
            occurred_at=alarm.canonical_start_time,
            snapshot_id=alarm.snapshot_id,
            snapshot_version=snapshot_version,
            quality_flags=alarm.quality_flags,
            profile_id=profile_id,
        )
        observations.append(occurrence)
        assumed_utc_count += int(assumed_utc)

    persisted_history_available = False
    history_issue: str | None = None
    if repository is not None and source and source_kind and profile_id and targets:
        try:
            profile_filter = SnapshotIngest.topology_profile_id == profile_id
            legacy_profile_marker = {
                "IP_NETWORK": "_ip_",
                "IT_SERVICES": "_it_",
            }.get(profile_id)
            if legacy_profile_marker is not None:
                profile_filter = or_(
                    profile_filter,
                    and_(
                        SnapshotIngest.topology_profile_id.is_(None),
                        func.lower(Snapshot.snapshot_id).contains(
                            legacy_profile_marker
                        ),
                    ),
                )
            snapshot_statement = (
                select(Snapshot.snapshot_id, Snapshot.snapshot_version)
                .join(
                    SnapshotIngest,
                    and_(
                        Snapshot.snapshot_id == SnapshotIngest.snapshot_id,
                        Snapshot.snapshot_version == SnapshotIngest.snapshot_version,
                    ),
                )
                .where(
                    Snapshot.status == "COMPLETE",
                    Snapshot.source == source,
                    Snapshot.source_kind == source_kind,
                    SnapshotIngest.status == "COMPLETE",
                    profile_filter,
                )
            )
            async with repository.sessions() as session:
                snapshot_ref_rows = (await session.execute(snapshot_statement)).all()
                snapshot_refs = [
                    (str(row_snapshot_id), str(row_snapshot_version))
                    for row_snapshot_id, row_snapshot_version in snapshot_ref_rows
                ]
                seen_snapshots.update(snapshot_refs)
                fault_expr = Alarm.raw.op("->>")(literal_column("'fault_id'"))
                alarm_statement = select(
                    Alarm.snapshot_id,
                    Alarm.snapshot_version,
                    Alarm.alarm_id,
                    Alarm.device_code,
                    fault_expr,
                    Alarm.canonical_start_time,
                    Alarm.quality_flags,
                ).where(
                    tuple_(Alarm.snapshot_id, Alarm.snapshot_version).in_(snapshot_refs),
                    tuple_(Alarm.device_code, fault_expr).in_(sorted(targets)),
                )
                rows = (await session.execute(alarm_statement)).all()
            persisted_history_available = True
            for (
                row_snapshot_id,
                row_snapshot_version,
                alarm_id,
                device_code,
                fault_id,
                occurred_at,
                quality_flags,
            ) in rows:
                row_snapshot_id = str(row_snapshot_id)
                row_snapshot_version = str(row_snapshot_version)
                occurrence, assumed_utc = _make_occurrence(
                    source_id=source or source_kind,
                    alarm_id=alarm_id,
                    device_code=device_code,
                    fault_id=fault_id,
                    occurred_at=occurred_at,
                    snapshot_id=row_snapshot_id,
                    snapshot_version=row_snapshot_version,
                    quality_flags=quality_flags,
                    profile_id=profile_id,
                )
                observations.append(occurrence)
                assumed_utc_count += int(assumed_utc)
        except Exception:
            LOGGER.exception("Could not read persisted alarm recurrence history")
            history_issue = "PERSISTED_HISTORY_UNAVAILABLE"

    result = count_alarm_recurrences(
        observations,
        as_of=datetime.now(timezone.utc),
        window=None,
    )
    groups = [
        {
            "device_code": group.device_code,
            "fault_id": group.fault_id,
            "count": group.count,
            "first_seen": group.first_seen.isoformat().replace("+00:00", "Z"),
            "last_seen": group.last_seen.isoformat().replace("+00:00", "Z"),
            "occurrences": [
                {
                    "source_id": occurrence.source_id,
                    "alarm_id": occurrence.alarm_id,
                    "occurred_at": occurrence.occurred_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "snapshots": [
                        {"snapshot_id": sid, "snapshot_version": version}
                        for sid, version in occurrence.snapshots
                    ],
                }
                for occurrence in group.occurrences[-_MAX_OCCURRENCES_PER_GROUP:]
            ],
            "occurrences_truncated": group.count > _MAX_OCCURRENCES_PER_GROUP,
        }
        for group in result.groups
    ]

    reason = None
    if not targets:
        reason = "NO_DEVICE_FAULT_PAIRS_IN_CHAIN"
    elif not groups:
        reason = "NO_TIMEZONE_VALID_HISTORICAL_OCCURRENCES"

    return {
        "snapshot_id": snapshot_id,
        "snapshot_version": snapshot_version,
        "chain_id": chain_id,
        "profile_id": profile_id or None,
        "source_id": source or None,
        "history_scope": (
            "MATCHING_PERSISTED_SNAPSHOTS"
            if persisted_history_available
            else "ACTIVE_SNAPSHOT_ONLY"
        ),
        "history_issue": history_issue,
        "snapshot_count": len(seen_snapshots),
        "assumed_utc_count": assumed_utc_count,
        "unmatched_chain_alarm_count": unmatched_chain_alarm_count,
        "duplicate_observations": result.duplicate_observations,
        "conflicting_event_keys": result.conflicting_event_keys,
        "skipped_observations": result.skipped_observations,
        "status": "AVAILABLE" if groups else "UNAVAILABLE",
        "reason": reason,
        "groups": groups,
    }
