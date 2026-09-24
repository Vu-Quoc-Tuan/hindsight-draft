"""Declarative contract for alarm fields actively consumed by Mock/Explain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ActiveAlarmField:
    key: str
    label: str
    group: str
    source_fields: tuple[str, ...]
    active_consumer: str
    data_type: str = "text"
    required: bool = False


ACTIVE_ALARM_FIELDS: tuple[ActiveAlarmField, ...] = (
    ActiveAlarmField("logical_row", "Row", "Identity", ("CSV row",), "stable identity and pagination", "integer", True),
    ActiveAlarmField("alarm_id", "Alarm ID", "Identity", ("cah.id",), "contract identity and analysis", required=True),
    ActiveAlarmField("chaining_id", "Chain ID", "Identity", ("chaining_id",), "observed chain partition", required=True),
    ActiveAlarmField("chaining_name", "Chain Name", "Identity", ("chaining_name",), "chain context"),
    ActiveAlarmField("raw_start_time", "Raw Start", "Time & State", ("cah.start_time",), "raw reconstruction and time quality"),
    ActiveAlarmField("canonical_start_time", "Canonical Start", "Time & State", ("parsed cah.start_time",), "sorting, slicing, temporal evidence", "datetime", True),
    ActiveAlarmField("raw_end_time", "Raw End", "Time & State", ("end_time",), "raw reconstruction and time quality"),
    ActiveAlarmField("canonical_end_time", "Canonical End", "Time & State", ("parsed end_time",), "duration and state interpretation", "datetime"),
    ActiveAlarmField("create_time", "Create Time", "Time & State", ("cah.create_time",), "sequence slicing fallback", "datetime"),
    ActiveAlarmField("alarm_status", "Alarm Status", "Time & State", ("alarm_status",), "observed upstream state"),
    ActiveAlarmField("alarm_name", "Alarm Name", "Semantics", ("alarm_name",), "evidence, descriptors, redundancy and similarity"),
    ActiveAlarmField("severity_name", "Severity", "Semantics", ("severity_name",), "canonical alarm and descriptors"),
    ActiveAlarmField("fault_id", "Fault ID", "Semantics", ("fault_id",), "taxonomy type fallback"),
    ActiveAlarmField("alarm_type_name", "Alarm Type", "Semantics", ("alarm_type_name",), "taxonomy and fingerprint fallback"),
    ActiveAlarmField("group_name", "Group", "Semantics", ("group_name",), "taxonomy family and similarity"),
    ActiveAlarmField("network_class_name", "Network Class", "Semantics", ("network_class_name",), "category fallback and descriptors"),
    ActiveAlarmField("monitor_type_name", "Monitor Type", "Semantics", ("monitor_type_name",), "category fallback"),
    ActiveAlarmField("device_code", "Device Code", "Entity", ("device_code",), "entity, burst, mapping and redundancy"),
    ActiveAlarmField("device_name", "Device Name", "Entity", ("device_name",), "cohesion advisor fallback label"),
    ActiveAlarmField("node_reference", "Node Reference", "Entity", ("node_reference",), "entity, descriptors, redundancy and mapping"),
    ActiveAlarmField("component", "Component", "Entity", ("component", "port"), "component entity and descriptors"),
    ActiveAlarmField("location_code", "Location Code", "Entity", ("location_code",), "site entity, burst and descriptors"),
    ActiveAlarmField("remote_node", "Remote Node", "Entity", ("remote_node",), "remote entity and descriptors"),
    ActiveAlarmField("device_type_name", "Device Type", "Entity", ("device_type_name",), "similar chains and reviewer context"),
    ActiveAlarmField("mapping_status", "Mapping Status", "Derived", ("resource mapper",), "mapping interpretation", required=True),
    ActiveAlarmField("resource_id", "Resource ID", "Derived", ("resource mapper",), "resolved topology resource"),
    ActiveAlarmField("quality_flags", "Quality Flags", "Derived", ("canonical loader",), "parse and missing-data facts", "list"),
)


def _raw_value(raw: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def project_active_alarm(
    *,
    logical_row: int,
    alarm_id: str,
    chaining_id: str | None,
    canonical_start_time: str | None,
    canonical_end_time: str | None,
    severity_name: str | None,
    mapping_status: str,
    resource_id: str | None,
    raw: Mapping[str, Any],
    quality_flags: Sequence[str] = (),
) -> dict[str, Any]:
    """Project one indexed alarm into the stable active-field API shape."""
    raw_status = _raw_value(raw, "alarm_status")
    return {
        "logical_row": logical_row,
        "alarm_id": alarm_id,
        "chaining_id": chaining_id or "",
        "chaining_name": _raw_value(raw, "chaining_name"),
        "raw_start_time": _raw_value(raw, "cah.start_time"),
        "canonical_start_time": canonical_start_time,
        "raw_end_time": _raw_value(raw, "end_time"),
        "canonical_end_time": canonical_end_time,
        "create_time": _raw_value(raw, "cah.create_time"),
        "alarm_status": raw_status or "UNKNOWN",
        "alarm_name": _raw_value(raw, "alarm_name"),
        "severity_name": severity_name or _raw_value(raw, "severity_name"),
        "fault_id": _raw_value(raw, "fault_id"),
        "alarm_type_name": _raw_value(raw, "alarm_type_name"),
        "group_name": _raw_value(raw, "group_name"),
        "network_class_name": _raw_value(raw, "network_class_name"),
        "monitor_type_name": _raw_value(raw, "monitor_type_name"),
        "device_code": _raw_value(raw, "device_code"),
        "device_name": _raw_value(raw, "device_name"),
        "node_reference": _raw_value(raw, "node_reference"),
        "component": _raw_value(raw, "component", "port"),
        "location_code": _raw_value(raw, "location_code"),
        "remote_node": _raw_value(raw, "remote_node"),
        "device_type_name": _raw_value(raw, "device_type_name"),
        "mapping_status": mapping_status,
        "resource_id": resource_id or "",
        "quality_flags": list(quality_flags),
    }


def has_value(value: Any) -> bool:
    """Treat zero as present while keeping null/blank/list-empty as unavailable."""
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(str(value).strip())
