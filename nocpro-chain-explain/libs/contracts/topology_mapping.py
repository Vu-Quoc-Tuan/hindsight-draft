"""One order-independent, fail-closed alarm-to-resource resolution policy.

A disputed alarm is unresolved; it must not contribute to a structural path,
quality score, or dependency channel. Callers may require all alarms (P2) or
use only individually resolved alarms (P0 and descriptive connectivity). A
navigation-only consumer may explicitly opt into structured-field-unique
matches; that opt-in does not make them dependency-eligible.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any


RESOLVED_STATUSES = frozenset({
    "EXACT", "VERIFIED_ALIAS", "EXACT_RESOURCE_ID", "UNIQUE_SOURCE_FIELD_MATCH",
})
UNRESOLVED_STATUSES = frozenset({"AMBIGUOUS", "UNMAPPED"})


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _canonical(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_canonical(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_canonical(item) for item in value))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def resolve_topology_mappings(
    raw_mappings: Iterable[dict[str, Any]],
    alarm_ids: Iterable[str] | None = None,
    *,
    require_all: bool = False,
    allow_structured_field_unique: bool = False,
) -> dict[str, dict[str, Any]] | None:
    """Return unambiguous rows, or ``None`` if complete resolution is required.

    Identical duplicate claims are harmless. Different status, resource, or
    provenance fields for one alarm make *that alarm* unresolved regardless of
    row order. Unknown statuses and a resource on an unresolved row fail closed.
    """
    requested = frozenset(alarm_ids) if alarm_ids is not None else None
    if requested is not None and (
        not requested or any(not isinstance(alarm_id, str) or not alarm_id for alarm_id in requested)
    ):
        return None if require_all else {}

    rows_by_alarm: dict[str, list[dict[str, Any]]] = {}
    for row in raw_mappings or ():
        if not isinstance(row, dict):
            continue
        alarm_id = row.get("alarm_id")
        if not isinstance(alarm_id, str) or not alarm_id:
            continue
        if requested is not None and alarm_id not in requested:
            continue
        rows_by_alarm.setdefault(alarm_id, []).append(row)

    resolved: dict[str, dict[str, Any]] = {}
    accepted_statuses = (
        RESOLVED_STATUSES | {"STRUCTURED_FIELD_UNIQUE"}
        if allow_structured_field_unique
        else RESOLVED_STATUSES
    )
    for alarm_id, rows in rows_by_alarm.items():
        statuses = {_canonical(row.get("mapping_status")) for row in rows}
        if len(statuses) != 1 or not statuses <= accepted_statuses:
            continue
        if statuses == {"STRUCTURED_FIELD_UNIQUE"} and any(
            _canonical(row.get("mapping_method")) != "STRUCTURED_FIELD_EXACT"
            for row in rows
        ):
            continue
        signatures = {
            tuple(sorted(
                (str(key), _canonical(value))
                for key, value in row.items() if key != "alarm_id"
            ))
            for row in rows
        }
        if len(signatures) != 1:
            continue
        resource_id = rows[0].get("resource_id")
        if not isinstance(resource_id, str) or not resource_id:
            continue
        resolved[alarm_id] = rows[0]

    if require_all and (requested is None or set(resolved) != requested):
        return None
    return resolved


def resolve_resource_ids(
    raw_mappings: Iterable[dict[str, Any]],
    alarm_ids: Iterable[str] | None = None,
    *,
    require_all: bool = False,
) -> dict[str, str] | None:
    rows = resolve_topology_mappings(raw_mappings, alarm_ids, require_all=require_all)
    if rows is None:
        return None
    return {alarm_id: row["resource_id"] for alarm_id, row in rows.items()}
