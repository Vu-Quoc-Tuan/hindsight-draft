"""Strict alarm-to-resource mapping resolution for P2 topology analyses.

The P0/P1 :class:`channels.dependency.ResourceResolver` intentionally keeps its
historical last-row-wins behavior.  P2 needs a stronger contract because a
chain-level topology claim must not depend on the order of mapping records.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any

from libs.contracts import IngestedPackage


_IDENTITY_KEYS = frozenset({"alarm_id"})
_RESOLVED_STATUSES = frozenset(
    {"EXACT", "VERIFIED_ALIAS", "EXACT_RESOURCE_ID", "UNIQUE_SOURCE_FIELD_MATCH"}
)
_UNRESOLVED_STATUSES = frozenset({"AMBIGUOUS", "UNMAPPED"})


def _canonical(value: Any) -> Any:
    """Make arbitrary mapping metadata deterministic and hashable."""
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


def resolve_p2_mappings(
    package: IngestedPackage, alarm_ids: Iterable[str]
) -> dict[str, str] | None:
    """Resolve every requested alarm exactly once under a strict P2 contract.

    Duplicate rows are accepted only when they are identical mapping claims.
    Any mixture of resolved and unresolved claims, differing resources, or
    differing context/provenance metadata makes the complete mapping result
    unavailable.  Rows for alarms outside ``alarm_ids`` are irrelevant.
    """
    relevant = frozenset(alarm_ids)
    if not relevant or any(not isinstance(alarm_id, str) for alarm_id in relevant):
        return None

    rows_by_alarm: dict[str, list[dict[str, Any]]] = {alarm_id: [] for alarm_id in relevant}
    for raw_mapping in package.topology.get("mappings") or ():
        if not isinstance(raw_mapping, dict):
            continue
        alarm_id = raw_mapping.get("alarm_id")
        if isinstance(alarm_id, str) and alarm_id in rows_by_alarm:
            rows_by_alarm[alarm_id].append(raw_mapping)

    resolved: dict[str, str] = {}
    for alarm_id in sorted(relevant):
        rows = rows_by_alarm[alarm_id]
        if not rows:
            return None

        statuses = {_canonical(row.get("mapping_status")) for row in rows}
        resolved_rows = [
            row
            for row in rows
            if _canonical(row.get("mapping_status")) in _RESOLVED_STATUSES
        ]
        unresolved_rows = [
            row
            for row in rows
            if _canonical(row.get("mapping_status")) in _UNRESOLVED_STATUSES
        ]
        if not statuses <= (_RESOLVED_STATUSES | _UNRESOLVED_STATUSES):
            return None
        if not resolved_rows or unresolved_rows:
            return None

        resource_ids = {
            _canonical(row.get("resource_id")) for row in resolved_rows
        }
        if len(resource_ids) != 1:
            return None
        resource_id = next(iter(resource_ids))
        if not isinstance(resource_id, str) or not resource_id:
            return None

        # Include status, method, and every supplied context/provenance field.
        # Thus identical duplicate claims are harmless, but a hidden metadata
        # disagreement cannot select a result through row ordering.
        signatures = {
            tuple(
                sorted(
                    (str(key), _canonical(value))
                    for key, value in row.items()
                    if key not in _IDENTITY_KEYS
                )
            )
            for row in resolved_rows
        }
        if len(signatures) != 1:
            return None
        resolved[alarm_id] = resource_id

    return resolved
