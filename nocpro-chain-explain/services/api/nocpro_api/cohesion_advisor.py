"""Cohesion narrative generator grounded on 5 authoritative data sources (ADR-0024).

Produces a natural, expert-toned operational narrative summarizing:
1. Raw alarm composition (alarm types, devices, network classes).
2. Chain WHY / descriptors (strong dimensions, dominant descriptors).
3. Topology mapping (mapped resources, verified resource types).
4. Structural audit findings (conductance, candidate cuts, partition status).
5. Operational context kept separate from the Counterfactual summary card.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from audit import AuditVerdict
from libs.contracts.topology_mapping import resolve_topology_mappings
from libs.contracts.topology_paths import select_path_forest, shortest_paths_to_targets
from .grounded_llm import render_grounded

logger = logging.getLogger(__name__)

_DEFAULT_COHESION_AI_TIMEOUT_SECONDS = 60.0
_MIN_COHESION_AI_TIMEOUT_SECONDS = 8.0
_MAX_COHESION_AI_TIMEOUT_SECONDS = 120.0
MAX_OVERVIEW_DISPLAY_PATHS = 100


def hydrate_persisted_deep_dive(value: Any) -> Any:
    """Restore attribute access for the JSON Deep Dive projection.

    Deep Dive jobs are persisted as the public JSON projection.  After an API
    restart the cohesion extractor used to receive that dict while only
    looking for domain-object attributes, silently dropping all P2 facts and
    falling back to the preliminary recommendation.  Rehydrate only the
    bounded projection (never arbitrary code or pickled objects).
    """
    if not isinstance(value, dict):
        return value

    def convert(item: Any) -> Any:
        if isinstance(item, dict):
            return SimpleNamespace(**{str(key): convert(val) for key, val in item.items()})
        if isinstance(item, list):
            return [convert(child) for child in item]
        return item

    payload = dict(value)
    # The persisted public schema flattens OverMergeVerdict into these two
    # fields.  Recreate the small shape consumed by the deterministic context
    # extractor so a restart has the same evidence as an in-process run.
    if "over_merge" not in payload and (
        "over_merge_strength" in payload or "over_merge_narrative" in payload
    ):
        payload["over_merge"] = {
            "strength": payload.get("over_merge_strength"),
            "narrative": payload.get("over_merge_narrative", ""),
        }
    return convert(payload)


def _cohesion_ai_timeout_seconds() -> float:
    """Return a bounded provider deadline for the evidence-heavy cohesion prompt."""
    raw_value = os.environ.get(
        "AI_COHESION_TIMEOUT_SECONDS",
        str(_DEFAULT_COHESION_AI_TIMEOUT_SECONDS),
    )
    try:
        configured = float(raw_value)
    except (TypeError, ValueError):
        configured = _DEFAULT_COHESION_AI_TIMEOUT_SECONDS
    return min(
        _MAX_COHESION_AI_TIMEOUT_SECONDS,
        max(_MIN_COHESION_AI_TIMEOUT_SECONDS, configured),
    )


@dataclass(frozen=True)
class CohesionNarrativeResult:
    chain_id: str
    narrative: str
    model: str
    provider_status: str | None
    context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finding(
    finding_id: str,
    *,
    kind: str,
    status: str,
    title: str,
    claim: str,
    evidence: list[str],
    limitations: list[str] | None = None,
    confidence_basis: str,
    confidence: str,
) -> dict[str, Any]:
    """Build one stable, UI-safe analytical finding."""
    return {
        "finding_id": finding_id,
        "kind": kind,
        "status": status,
        "title": title,
        "claim": claim,
        "evidence": evidence,
        "limitations": list(limitations or []),
        "confidence_basis": confidence_basis,
        "confidence": confidence,
    }


def _alarm_start(alarm: Any) -> str | None:
    raw = alarm.raw if hasattr(alarm, "raw") and isinstance(alarm.raw, dict) else {}
    value = (
        getattr(alarm, "canonical_start_time", None)
        or raw.get("cah.start_time")
        or raw.get("start_time")
    )
    return str(value) if value else None


def _record_value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _format_offset(seconds: int) -> str:
    minutes, remainder = divmod(max(0, seconds), 60)
    if minutes:
        return f"{minutes}m {remainder:02d}s"
    return f"{remainder}s"


def _build_temporal_progression(raw_alarms: list[Any]) -> dict[str, Any]:
    """Build observed device-onset waves without upgrading order into causality."""
    onset_by_device: dict[str, tuple[datetime, str, str]] = {}
    for alarm in raw_alarms:
        raw = alarm.raw if hasattr(alarm, "raw") and isinstance(alarm.raw, dict) else {}
        device = getattr(alarm, "device_code", None) or raw.get("device_code") or raw.get("device_name")
        start_raw = _alarm_start(alarm)
        start = _parse_time(start_raw)
        if not device or start is None or start_raw is None:
            continue
        alarm_name = getattr(alarm, "alarm_name", None) or raw.get("alarm_name") or "Unknown Alarm"
        previous = onset_by_device.get(str(device))
        if previous is None or start < previous[0]:
            onset_by_device[str(device)] = (start, start_raw, str(alarm_name))

    ordered = sorted(onset_by_device.items(), key=lambda item: (item[1][0], item[0]))
    if not ordered:
        return {"status": "UNAVAILABLE", "device_onsets": [], "waves": []}

    t0 = ordered[0][1][0]
    device_onsets = [
        {
            "device": device,
            "start_time": start_raw,
            "offset_seconds": int((start - t0).total_seconds()),
            "alarm_name": alarm_name,
        }
        for device, (start, start_raw, alarm_name) in ordered
    ]
    grouped: dict[datetime, list[dict[str, Any]]] = {}
    for onset in device_onsets:
        parsed = _parse_time(onset["start_time"])
        if parsed is not None:
            grouped.setdefault(parsed, []).append(onset)
    waves = [
        {
            "start_time": entries[0]["start_time"],
            "offset_seconds": entries[0]["offset_seconds"],
            "devices": [entry["device"] for entry in entries],
            "alarm_names": sorted({entry["alarm_name"] for entry in entries}),
        }
        for _, entries in sorted(grouped.items())
    ]
    return {
        "status": "AVAILABLE",
        "t0": device_onsets[0],
        "first_later_offset_seconds": (
            device_onsets[1]["offset_seconds"] if len(device_onsets) > 1 else None
        ),
        "device_onsets": device_onsets,
        "waves": waves,
    }


def _build_alarm_observation_groups(raw_alarms: list[Any]) -> list[dict[str, Any]]:
    """Compress raw alarms into bounded device/type observations for synthesis."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for alarm in raw_alarms:
        raw = alarm.raw if hasattr(alarm, "raw") and isinstance(alarm.raw, dict) else {}
        device = str(
            getattr(alarm, "device_code", None)
            or raw.get("device_code")
            or raw.get("device_name")
            or "UNKNOWN_DEVICE"
        )
        alarm_name = str(
            getattr(alarm, "alarm_name", None)
            or raw.get("alarm_name")
            or "Unknown Alarm"
        )
        entry = grouped.setdefault((device, alarm_name), {
            "device": device,
            "alarm_name": alarm_name,
            "count": 0,
            "first_observed": None,
            "last_observed": None,
            "components": set(),
            "locations": set(),
            "remote_nodes": set(),
            "severities": set(),
            "ports": set(),
            "peer_hints": set(),
            "device_types": set(),
            "network_classes": set(),
            "alarm_groups": set(),
            "content_examples": set(),
        })
        entry["count"] += 1
        start = _alarm_start(alarm)
        if start:
            if entry["first_observed"] is None or start < entry["first_observed"]:
                entry["first_observed"] = start
            if entry["last_observed"] is None or start > entry["last_observed"]:
                entry["last_observed"] = start
        for field, target in (
            ("component", "components"),
            ("location_code", "locations"),
            ("remote_node", "remote_nodes"),
        ):
            value = getattr(alarm, field, None) or raw.get(field)
            if value:
                entry[target].add(str(value))
        severity = getattr(alarm, "severity_name", None) or raw.get("severity_name")
        if severity:
            entry["severities"].add(str(severity))
        for field, target in (
            ("port", "ports"),
            ("addition_info", "peer_hints"),
            ("link_name", "peer_hints"),
            ("device_type_name", "device_types"),
            ("network_class_name", "network_classes"),
            ("group_name", "alarm_groups"),
        ):
            value = raw.get(field)
            if value:
                entry[target].add(str(value))
        content = re.sub(r"\s+", " ", str(raw.get("content") or "")).strip()
        if content:
            entry["content_examples"].add(content[:140])

    observations: list[dict[str, Any]] = []
    for entry in grouped.values():
        observations.append({
            "device": entry["device"],
            "alarm_name": entry["alarm_name"],
            "count": entry["count"],
            "first_observed": entry["first_observed"],
            "last_observed": entry["last_observed"],
            "components": sorted(entry["components"])[:3],
            "locations": sorted(entry["locations"])[:3],
            "remote_nodes": sorted(entry["remote_nodes"])[:3],
            "severities": sorted(entry["severities"])[:3],
            "ports": sorted(entry["ports"])[:3],
            "peer_hints": sorted(entry["peer_hints"])[:3],
            "device_types": sorted(entry["device_types"])[:2],
            "network_classes": sorted(entry["network_classes"])[:2],
            "alarm_groups": sorted(entry["alarm_groups"])[:2],
            "content_examples": sorted(entry["content_examples"])[:1],
        })
    observations.sort(key=lambda item: (
        str(item["first_observed"] or "9999"),
        -int(item["count"]),
        str(item["device"]),
        str(item["alarm_name"]),
    ))
    return observations[:16]


def _build_topology_connectivity(
    *,
    raw_mappings: Any,
    raw_edges: Any,
    member_ids: set[str],
    alarm_devices: dict[str, str],
    max_hops: int = 4,
) -> dict[str, Any]:
    """Resolve alarm mappings before bounded structural path discovery.

    Directed IT source relations are intentionally traversed as undirected only
    for a bounded connectivity observation. This does not verify dependency or
    propagation direction.
    """
    resource_by_alarm: dict[str, str] = {}
    resource_types: set[str] = set()
    resource_devices: dict[str, set[str]] = {}
    mapped_alarm_ids: set[str] = set()
    resolved_mappings = resolve_topology_mappings(raw_mappings or (), member_ids) or {}
    for alarm_id, mapping in resolved_mappings.items():
        resource_id = mapping["resource_id"]
        mapped_alarm_ids.add(alarm_id)
        resource_by_alarm[alarm_id] = resource_id
        topology_layer = (
            _record_value(mapping, "topology_layer")
            or _record_value(mapping, "resource_type")
            or _record_value(mapping, "type")
        )
        if topology_layer:
            resource_types.add(str(topology_layer))
        if alarm_devices.get(alarm_id):
            resource_devices.setdefault(resource_id, set()).add(alarm_devices[alarm_id])

    adjacency_by_relation: dict[str, dict[str, set[str]]] = {}
    for edge in raw_edges or ():
        source = _record_value(edge, "source_resource_id")
        target = _record_value(edge, "target_resource_id")
        relation = str(_record_value(edge, "relation_type", "CONNECTED"))
        if not source or not target:
            continue
        source, target = str(source), str(target)
        adjacency = adjacency_by_relation.setdefault(relation, {})
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)

    resources = sorted(set(resource_by_alarm.values()))
    paths: list[dict[str, Any]] = []
    transit_counter: Counter[str] = Counter()
    for source_index, source in enumerate(resources):
        targets = resources[source_index + 1:]
        if not targets:
            continue
        best_paths: dict[str, tuple[list[str], str]] = {}
        for relation, adjacency in sorted(adjacency_by_relation.items()):
            candidates = shortest_paths_to_targets(
                adjacency, source, set(targets), max_hops=max_hops
            )
            for target, candidate in candidates.items():
                prior = best_paths.get(target)
                if prior is None or len(candidate) < len(prior[0]):
                    best_paths[target] = candidate, relation
        for target in targets:
            best = best_paths.get(target)
            if best is None:
                continue
            best_path, best_relation = best
            transit_counter.update(best_path[1:-1])
            paths.append({
                "source": source,
                "target": target,
                "source_devices": sorted(resource_devices.get(source, ())),
                "target_devices": sorted(resource_devices.get(target, ())),
                "hop_count": len(best_path) - 1,
                "path": best_path,
                "relation_type": best_relation,
                "traversal_semantic": "UNDIRECTED_STRUCTURAL_CONNECTIVITY",
            })

    pair_total = len(resources) * (len(resources) - 1) // 2
    complete_display_forest = select_path_forest(paths)
    display_paths = complete_display_forest[:MAX_OVERVIEW_DISPLAY_PATHS]
    mapped_device_ids = sorted({
        alarm_devices[alarm_id]
        for alarm_id in mapped_alarm_ids
        if alarm_devices.get(alarm_id)
    })
    return {
        "mapped_alarm_ids": mapped_alarm_ids,
        "mapped_device_ids": mapped_device_ids,
        "resource_by_alarm": resource_by_alarm,
        "resource_types": sorted(resource_types),
        "mapped_resources": resources,
        "paths": paths,
        "display_paths": display_paths,
        "display_paths_truncated": len(complete_display_forest) > len(display_paths),
        "pair_total": pair_total,
        "connected_pair_count": len(paths),
        "max_path_hops": max((path["hop_count"] for path in paths), default=None),
        "shared_transit_resources": [
            {"resource_id": resource_id, "path_count": count}
            for resource_id, count in transit_counter.most_common(5)
        ],
    }


_EVIDENCE_GROUP_LABELS_VI = {
    "temporal_burst": "xuất hiện gần nhau về thời gian",
    "temporal_delay": "thứ tự thời gian tương thích",
    "dependency_hop": "có đường liên kết topology",
    "dependency_topology_embedding": "có ngữ cảnh topology tương tự",
    "semantic": "có nội dung cảnh báo tương đồng",
    "reference": "cùng tham chiếu đối tượng",
    "device": "cùng thiết bị",
    "card": "cùng card/module",
    "site": "cùng site",
    "remote": "cùng đầu xa",
    "historical": "có mẫu lịch sử tương đồng",
}


def _summarize_partition_side(
    member_ids: set[str],
    alarm_by_id: dict[str, Any],
) -> dict[str, Any]:
    device_counts: Counter[str] = Counter()
    alarm_type_counts: Counter[str] = Counter()
    observed: list[tuple[datetime, str, str, str]] = []
    for alarm_id in sorted(member_ids):
        alarm = alarm_by_id.get(alarm_id)
        if alarm is None:
            continue
        raw = alarm.raw if hasattr(alarm, "raw") and isinstance(alarm.raw, dict) else {}
        device = str(
            getattr(alarm, "device_code", None)
            or raw.get("device_code")
            or raw.get("device_name")
            or ""
        ).strip()
        alarm_name = str(
            getattr(alarm, "alarm_name", None)
            or raw.get("alarm_name")
            or "Unknown Alarm"
        ).strip()
        if device:
            device_counts[device] += 1
        if alarm_name:
            alarm_type_counts[alarm_name] += 1
        start_raw = _alarm_start(alarm)
        start = _parse_time(start_raw)
        if start is not None and start_raw is not None:
            observed.append((start, start_raw, device, alarm_name))

    observed.sort(key=lambda item: item[0])
    first = observed[0] if observed else None
    return {
        "alarm_count": len(member_ids),
        "resolved_alarm_count": sum(device_counts.values()),
        "devices": [
            {"device": device, "alarm_count": count}
            for device, count in device_counts.most_common(4)
        ],
        "alarm_types": [
            {"alarm_name": name, "alarm_count": count}
            for name, count in alarm_type_counts.most_common(3)
        ],
        "first_observed": (
            {
                "start_time": first[1],
                "device": first[2],
                "alarm_name": first[3],
            }
            if first is not None
            else None
        ),
    }


def _build_audit_partition_summary(
    *,
    raw_alarms: list[Any],
    best_cut: Any,
    visualization: Any | None,
    topology_connectivity: dict[str, Any],
) -> dict[str, Any] | None:
    """Describe both cut sides and their observed cross-links without causal uplift."""
    cut_members = {
        str(member_id)
        for member_id in (getattr(best_cut, "members", ()) or ())
        if member_id is not None
    }
    alarm_by_id: dict[str, Any] = {}
    for alarm in raw_alarms:
        raw = alarm.raw if hasattr(alarm, "raw") and isinstance(alarm.raw, dict) else {}
        alarm_id = getattr(alarm, "alarm_id", None) or raw.get("alarm_id")
        if alarm_id is not None:
            alarm_by_id[str(alarm_id)] = alarm
    all_members = set(alarm_by_id)
    side_a_members = cut_members & all_members
    side_b_members = all_members - side_a_members
    if not side_a_members or not side_b_members:
        return None

    side_a = _summarize_partition_side(side_a_members, alarm_by_id)
    side_b = _summarize_partition_side(side_b_members, alarm_by_id)

    def member_devices(member_ids: set[str]) -> set[str]:
        values: set[str] = set()
        for member_id in member_ids:
            alarm = alarm_by_id.get(member_id)
            if alarm is None:
                continue
            raw = alarm.raw if hasattr(alarm, "raw") and isinstance(alarm.raw, dict) else {}
            device = (
                getattr(alarm, "device_code", None)
                or raw.get("device_code")
                or raw.get("device_name")
            )
            if device:
                values.add(str(device))
        return values

    side_a_devices = member_devices(side_a_members)
    side_b_devices = member_devices(side_b_members)

    cross_topology_paths: list[dict[str, Any]] = []
    for path in topology_connectivity.get("paths", []):
        source_devices = set(path.get("source_devices") or [])
        target_devices = set(path.get("target_devices") or [])
        crosses = (
            bool(source_devices & side_a_devices) and bool(target_devices & side_b_devices)
        ) or (
            bool(source_devices & side_b_devices) and bool(target_devices & side_a_devices)
        )
        if crosses:
            cross_topology_paths.append({
                "source_devices": sorted(source_devices),
                "target_devices": sorted(target_devices),
                "hop_count": path.get("hop_count"),
                "relation_type": path.get("relation_type"),
                "path": list(path.get("path") or []),
                "traversal_semantic": path.get("traversal_semantic"),
            })

    first_a = side_a.get("first_observed") or {}
    first_b = side_b.get("first_observed") or {}
    onset_a = _parse_time(first_a.get("start_time"))
    onset_b = _parse_time(first_b.get("start_time"))
    onset_gap_seconds = (
        abs(int((onset_b - onset_a).total_seconds()))
        if onset_a is not None and onset_b is not None
        else None
    )

    cross_edges = 0
    internal_edges = 0
    cross_weight = 0.0
    internal_weight = 0.0
    cross_groups: Counter[str] = Counter()
    visualization_status = str(getattr(visualization, "status", ""))
    if visualization is not None and visualization_status == "AVAILABLE":
        for edge in getattr(visualization, "edges", ()) or ():
            weight = float(getattr(edge, "weight", 0.0) or 0.0)
            if bool(getattr(edge, "crosses_best_cut", False)):
                cross_edges += 1
                cross_weight += weight
                cross_groups.update(
                    str(group) for group in (getattr(edge, "supporting_groups", ()) or ())
                )
            else:
                internal_edges += 1
                internal_weight += weight

    supporting_groups = [
        {
            "group": group,
            "label_vi": _EVIDENCE_GROUP_LABELS_VI.get(group, group.replace("_", " ")),
            "edge_count": count,
        }
        for group, count in cross_groups.most_common()
    ]
    visualization_truncated = bool(getattr(visualization, "truncated", False))
    return {
        "status": "AVAILABLE",
        "cut_source": str(getattr(best_cut, "source", "") or ""),
        "cut_label": getattr(best_cut, "label", None),
        "side_a": side_a,
        "side_b": side_b,
        "linkage": {
            "onset_gap_seconds": onset_gap_seconds,
            "topology_paths": cross_topology_paths[:3],
            "supporting_groups": supporting_groups,
        },
        "separation": {
            "cross_edge_count": cross_edges,
            "internal_edge_count": internal_edges,
            "cross_edge_weight": round(cross_weight, 4),
            "internal_edge_weight": round(internal_weight, 4),
            "edge_counts_are_complete": visualization_status == "AVAILABLE" and not visualization_truncated,
            "visualization_truncated": visualization_truncated,
        },
    }


def _resolve_recommendations(review_result: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve selected recommendation ids against their evaluated candidates."""
    if not isinstance(review_result, dict):
        return {
            "status": "NOT_EVALUATED",
            "count": 0,
            "evaluation_completed": False,
            "evaluated_count": 0,
            "rejected_count": 0,
            "reason": None,
            "calibration_status": None,
            "split_recommended": False,
            "best_alternative": None,
        }

    evaluated_candidates = [
        candidate
        for candidate in review_result.get("evaluated_candidates", [])
        if isinstance(candidate, dict) and candidate.get("candidate_id")
    ]
    evaluated = {
        str(candidate.get("candidate_id")): candidate
        for candidate in evaluated_candidates
    }
    selected: list[dict[str, Any]] = []
    for recommendation in review_result.get("recommendations", []):
        if not isinstance(recommendation, dict):
            continue
        candidate_id = str(recommendation.get("candidate_id") or "")
        selected.append(evaluated.get(candidate_id, recommendation))

    operations = {
        str(candidate.get("operation") or "").upper()
        for candidate in selected
    }
    split_recommended = bool(
        operations.intersection({"SPLIT_CHAIN", "REMOVE_MEMBER", "MOVE_MEMBER"})
    )
    best_alternative: dict[str, Any] | None = None
    if selected:
        best = selected[0]
        explanation = best.get("comparative_explanation")
        explanation = explanation if isinstance(explanation, dict) else {}
        best_alternative = {
            "candidate_id": best.get("candidate_id"),
            "operation": best.get("operation"),
            "summary_action": explanation.get("summary_action"),
            "why_better": explanation.get("why_better"),
        }

    raw_status = str(review_result.get("recommendation_status") or "").upper()
    status = raw_status or ("AVAILABLE" if selected else "NO_RECOMMENDATION")
    evaluation_status = str(review_result.get("status") or "").upper()
    evaluation_completed = bool(evaluated_candidates) or evaluation_status in {
        "AVAILABLE",
        "UNAVAILABLE",
    }
    rejected_count = sum(
        1
        for candidate in evaluated_candidates
        if str((candidate.get("hard_gate_result") or {}).get("status") or "").upper() == "REJECTED"
        or str(candidate.get("evaluation_status") or candidate.get("status") or "").upper()
        in {"HARD_GATE_REJECTED", "EXTERNALLY_CONTRADICTED"}
    )
    return {
        "status": status,
        "count": len(selected),
        "evaluation_completed": evaluation_completed,
        "evaluated_count": len(evaluated_candidates),
        "rejected_count": rejected_count,
        "reason": review_result.get("reason"),
        "calibration_status": review_result.get("calibration_status"),
        "split_recommended": split_recommended,
        "best_alternative": best_alternative,
    }


def select_representative_member(
    members: dict[str, Any],
    alarms: dict[str, Any],
) -> dict[str, Any] | None:
    """Select the strongest evidence representative, never a root-cause proxy."""
    role_rank = {"CORE": 2, "PERIPHERAL": 1}
    candidates: list[tuple[tuple[float, float, float, float, float, str], dict[str, Any]]] = []
    for alarm_id, member in members.items():
        role = getattr(member, "role", None)
        verdict = getattr(role, "verdict", None)
        role_value = str(getattr(verdict, "value", verdict or "")).upper()
        if role_value not in role_rank:
            continue
        support = getattr(getattr(member, "support", None), "support", None)
        gate = getattr(role, "gate", None)
        coverage = getattr(gate, "availability_coverage", None)
        computable_groups = getattr(gate, "computable_groups", None)
        representativeness = getattr(member, "representativeness", None)
        alarm = alarms.get(str(alarm_id))
        candidates.append((
            (
                -float(role_rank[role_value]),
                -float(support if support is not None else -1.0),
                -float(coverage if coverage is not None else -1.0),
                -float(computable_groups if computable_groups is not None else -1.0),
                -float(representativeness if representativeness is not None else -1.0),
                str(alarm_id),
            ),
            {
                "status": "AVAILABLE",
                "alarm_id": str(alarm_id),
                "alarm_name": getattr(alarm, "alarm_name", None) if alarm is not None else None,
                "device_code": (
                    getattr(alarm, "device_code", None) or getattr(alarm, "node_reference", None)
                    if alarm is not None else None
                ),
                "role": role_value,
                "membership_support": support,
                "availability_coverage": coverage,
                "computable_groups": computable_groups,
                "representativeness": representativeness,
                "selection_semantic": "EVIDENCE_REPRESENTATIVE_NOT_ROOT_CAUSE",
            },
        ))
    if not candidates:
        return {
            "status": "UNAVAILABLE",
            "selection_semantic": "NO_CORE_OR_PERIPHERAL_EVIDENCE_REPRESENTATIVE",
            "reason": "NO_CORE_OR_PERIPHERAL_MEMBER",
        }
    return min(candidates, key=lambda item: item[0])[1]


def build_chain_quality_assessment(
    *,
    alarm_count: int,
    role_counts: dict[str, Any],
    mapped_device_count: int,
    total_device_count: int,
    connected_pair_count: int,
    pair_total: int,
    audit_status: str,
    audit_verdict: str | None,
    over_merge_strength: str | None,
    recommendation_count: int,
    recommendation_status: str,
    recommendation_evaluation_completed: bool = False,
) -> dict[str, Any]:
    """Rate grouping robustness from available evidence, never as probability."""
    method = "HEURISTIC_V1"
    if alarm_count <= 1:
        return {
            "method": method,
            "status": "NOT_APPLICABLE",
            "stars": None,
            "label": "Không áp dụng",
            "reasons": ["Chuỗi chỉ có một cảnh báo."],
            "available_dimension_count": 0,
        }

    normalized_roles = {
        str(getattr(key, "value", key)).upper(): int(value or 0)
        for key, value in (role_counts or {}).items()
    }
    insufficient = normalized_roles.get("INSUFFICIENT_DATA", 0)
    weak = normalized_roles.get("WEAK", 0)
    role_total = sum(max(0, count) for count in normalized_roles.values())
    evaluated_members = max(0, role_total - insufficient)
    role_coverage = evaluated_members / max(1, alarm_count)
    if role_coverage < 0.5:
        return {
            "method": method,
            "status": "UNAVAILABLE",
            "stars": None,
            "label": "Chưa thể chấm",
            "reasons": ["Chưa đủ thành viên có evidence để đánh giá vai trò."],
            "available_dimension_count": 1,
        }

    dimensions: list[tuple[str, float, float]] = [
        ("role_coverage", role_coverage, 0.15),
        ("member_consistency", 1.0 - (weak / max(1, evaluated_members)), 0.20),
    ]
    if total_device_count > 0:
        dimensions.append((
            "device_mapping",
            min(1.0, mapped_device_count / total_device_count),
            0.15,
        ))
    if pair_total > 0:
        dimensions.append((
            "topology_connectivity",
            min(1.0, connected_pair_count / pair_total),
            0.15,
        ))
    verdict = str(audit_verdict or "").upper()
    if str(audit_status).upper() == "EVALUATED":
        dimensions.append((
            "structural_audit",
            1.0 if verdict == "NO_LOW_CONDUCTANCE_CUT" else 0.0,
            0.25,
        ))
    strength = str(over_merge_strength or "").upper()
    if strength in {"NONE", "WEAK", "MODERATE", "STRONG"}:
        dimensions.append((
            "over_merge",
            {"NONE": 1.0, "WEAK": 0.7, "MODERATE": 0.25, "STRONG": 0.0}.get(strength, 0.5),
            0.10,
        ))

    if len(dimensions) < 3:
        return {
            "method": method,
            "status": "UNAVAILABLE",
            "stars": None,
            "label": "Chưa thể chấm",
            "reasons": ["Chưa đủ nguồn evidence độc lập để chấm độ vững."],
            "available_dimension_count": len(dimensions),
        }

    weight_total = sum(weight for _, _, weight in dimensions)
    score = sum(value * weight for _, value, weight in dimensions) / weight_total
    if score >= 0.85:
        stars = 5
    elif score >= 0.70:
        stars = 4
    elif score >= 0.50:
        stars = 3
    elif score >= 0.30:
        stars = 2
    else:
        stars = 1

    strength = str(over_merge_strength or "").upper()
    if verdict == "CANDIDATE_SPLIT" or strength == "MODERATE":
        stars = min(stars, 2)
    if strength == "STRONG":
        stars = 1
    if recommendation_count > 0:
        stars = min(stars, 3)
    review_status = str(recommendation_status or "NOT_EVALUATED").upper()
    if review_status in {"NOT_EVALUATED", "UNAVAILABLE"}:
        stars = min(stars, 4)
    if stars == 5 and not (
        str(audit_status).upper() == "EVALUATED"
        and verdict == "NO_LOW_CONDUCTANCE_CUT"
        and strength not in {"MODERATE", "STRONG"}
        and recommendation_count == 0
    ):
        stars = 4

    labels = {
        5: "Rất vững",
        4: "Khá vững",
        3: "Cần xem thêm",
        2: "Có dấu hiệu nên tách",
        1: "Rủi ro gộp sai cao",
    }
    reasons: list[str] = []
    if total_device_count:
        reasons.append(f"{mapped_device_count}/{total_device_count} thiết bị đã nằm trong topology.")
    if pair_total:
        reasons.append(
            f"{connected_pair_count}/{pair_total} cặp resource có đường kết nối trong giới hạn phân tích."
        )
    if weak:
        reasons.append(f"Có {weak} thành viên yếu trong {evaluated_members} thành viên đã đánh giá.")
    if verdict == "CANDIDATE_SPLIT":
        reasons.append("Audit phát hiện một ranh giới có thể tách chuỗi.")
    elif verdict == "NO_LOW_CONDUCTANCE_CUT":
        reasons.append("Audit chưa tìm thấy ranh giới tách đủ yếu.")
    if recommendation_count:
        reasons.append(f"Counterfactual tìm thấy {recommendation_count} phương án tốt hơn.")
    elif review_status == "UNAVAILABLE":
        reasons.insert(
            0,
            "Counterfactual đã chạy nhưng khuyến nghị chưa đủ điều kiện phát hành."
            if recommendation_evaluation_completed
            else "Counterfactual chưa thể hoàn tất đánh giá phương án.",
        )
    elif review_status == "NOT_EVALUATED":
        reasons.insert(0, "Counterfactual chưa chạy nên chưa thể loại trừ phương án tốt hơn.")

    return {
        "method": method,
        "status": "EVALUATED",
        "stars": stars,
        "label": labels[stars],
        "reasons": reasons[:3],
        "available_dimension_count": len(dimensions),
    }


CHAIN_OVERVIEW_PROJECTION_VERSION = "CHAIN_OVERVIEW_V3"
CHAIN_QUALITY_PIPELINE_VERSION = "DETERMINISTIC_QUALITY_V3"


def build_chain_overview_projection(context: dict[str, Any]) -> dict[str, Any]:
    """Return the small deterministic payload needed by the chain Overview cards.

    This projection is deliberately independent from the narrative prompt and
    excludes the potentially large WHY, path and analytical-findings sections.
    It is safe to persist and serve without invoking a provider.
    """
    representative = context.get("representative_member")
    representative_projection = None
    if isinstance(representative, dict):
        representative_projection = {
            key: representative.get(key)
            for key in (
                "status",
                "alarm_id",
                "alarm_name",
                "device_code",
                "role",
                "membership_support",
                "availability_coverage",
                "computable_groups",
                "representativeness",
                "selection_semantic",
                "reason",
            )
            if key in representative
        }

    topology = context.get("topology")
    topology_projection = {}
    if isinstance(topology, dict):
        topology_projection = {
            key: topology.get(key)
            for key in (
                "mapped",
                "total",
                "mapped_device_count",
                "total_device_count",
                "device_mapping_ratio",
                "resource_types",
                "dependency_verified",
                "connected_pair_count",
                "pair_total",
                "max_path_hops",
                "mapped_resources",
                "display_paths",
                "display_paths_truncated",
            )
            if key in topology
        }

    recommendations = context.get("recommendations")
    recommendations_projection = {}
    if isinstance(recommendations, dict):
        recommendations_projection = {
            key: recommendations.get(key)
            for key in (
                "status",
                "count",
                "evaluation_completed",
                "evaluated_count",
                "rejected_count",
                "reason",
                "calibration_status",
                "split_recommended",
                "best_alternative",
            )
            if key in recommendations
        }

    return {
        "projection_version": CHAIN_OVERVIEW_PROJECTION_VERSION,
        "representative_member": representative_projection,
        "topology": topology_projection,
        "quality_assessment": context.get("quality_assessment"),
        "recommendations": recommendations_projection,
    }


def _build_analytical_findings(
    *,
    alarm_count: int,
    top_alarm_types: list[list[Any]],
    mapped_count: int,
    topology_connectivity: dict[str, Any],
    temporal_progression: dict[str, Any],
    audit_status: str,
    audit_verdict: str | None,
    audit_reason: str | None,
    audit_detail: dict[str, Any],
    dominator_info: dict[str, Any] | None = None,
    propagation_info: dict[str, Any] | None = None,
    over_merge_info: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Derive findings without upgrading correlation into topology or causality."""
    findings: list[dict[str, Any]] = []

    if top_alarm_types and alarm_count:
        dominant_name, dominant_count = top_alarm_types[0]
        dominant_pct = round((int(dominant_count) / alarm_count) * 100, 1)
        findings.append(_finding(
            "ALARM_CONCENTRATION",
            kind="OBSERVED",
            status="AVAILABLE",
            title="Alarm concentration",
            claim=(
                f"Cảnh báo tập trung mạnh vào loại '{dominant_name}' "
                f"({dominant_pct}% tổng số sự kiện)."
            ),
            evidence=[f"{dominant_count}/{alarm_count} cảnh báo có loại '{dominant_name}'."],
            limitations=["ALARM_TYPE_FREQUENCY_DOES_NOT_ESTABLISH_ROOT_CAUSE"],
            confidence_basis="DIRECT_ALARM_COUNTS",
            confidence="HIGH",
        ))

    onsets = temporal_progression.get("device_onsets", [])
    if temporal_progression.get("status") == "AVAILABLE" and onsets:
        first = onsets[0]
        first_later = temporal_progression.get("first_later_offset_seconds")
        later_clause = (
            f"; thiết bị tiếp theo bắt đầu sau {_format_offset(int(first_later))}"
            if first_later is not None else ""
        )
        evidence = [
            f"T0: {first['device']} — '{first['alarm_name']}' lúc {first['start_time']}."
        ]
        for wave in temporal_progression.get("waves", [])[1:6]:
            evidence.append(
                f"+{_format_offset(int(wave['offset_seconds']))}: "
                f"{', '.join(wave['devices'])} — {', '.join(wave['alarm_names'][:2])}."
            )
        findings.append(_finding(
            "TEMPORAL_PROGRESSION",
            kind="DERIVED",
            status="AVAILABLE",
            title="Diễn tiến theo thời gian",
            claim=(
                f"Chuỗi bắt đầu tại {first['device']} rồi mở rộng từ 1 lên "
                f"{len(onsets)} thiết bị{later_clause}."
            ),
            evidence=evidence,
            limitations=["CAUSAL_DIRECTION_UNVERIFIED", "EARLIEST_ALARM_IS_NOT_ROOT_CAUSE"],
            confidence_basis="CANONICAL_DEVICE_ONSET_ORDERING",
            confidence="HIGH",
        ))

    paths = topology_connectivity.get("paths", [])
    pair_total = int(topology_connectivity.get("pair_total", 0) or 0)
    connected_count = int(topology_connectivity.get("connected_pair_count", 0) or 0)
    if mapped_count > 0 and paths:
        evidence = [
            f"{connected_count}/{pair_total} cặp resource có đường transit trong giới hạn 4 hop."
        ]
        for path in topology_connectivity.get("display_paths", [])[:2]:
            source_label = ", ".join(path.get("source_devices") or [path["source"]])
            target_label = ", ".join(path.get("target_devices") or [path["target"]])
            evidence.append(
                f"{source_label} ↔ {target_label}: {' → '.join(path['path'])} "
                f"({path['hop_count']} hop, {path['relation_type']})."
            )
        if topology_connectivity.get("display_paths_truncated"):
            evidence.append(
                f"Chỉ lưu {MAX_OVERVIEW_DISPLAY_PATHS} đường đại diện đầu tiên trong display forest; "
                "các số liệu kết nối vẫn tính trên toàn bộ cặp resource đủ điều kiện."
            )
        shared = topology_connectivity.get("shared_transit_resources", [])
        if shared:
            evidence.append(
                "Transit dùng chung nổi bật: "
                + ", ".join(item["resource_id"] for item in shared[:3])
                + "."
            )
        findings.append(_finding(
            "SHARED_TOPOLOGY_CONTEXT",
            kind="DERIVED",
            status="AVAILABLE",
            title="Ngữ cảnh topology dùng chung",
            claim=(
                f"Có {connected_count}/{pair_total} cặp resource đã ánh xạ có đường transit "
                f"trong giới hạn 4 hop; đường dài nhất quan sát được là "
                f"{topology_connectivity.get('max_path_hops')} hop."
            ),
            evidence=evidence,
            limitations=[
                "TRANSIT_CONNECTIVITY_IS_NOT_CAUSAL_DEPENDENCY",
                "IT_EDGE_DIRECTION_NOT_USED_FOR_PROPAGATION",
            ],
            confidence_basis="MAPPED_RESOURCES_AND_BOUNDED_SAME_RELATION_PATHS",
            confidence="HIGH",
        ))
    else:
        findings.append(_finding(
            "TOPOLOGY_EVIDENCE_GAP",
            kind="LIMITATION",
            status="UNAVAILABLE",
            title="Topology evidence unavailable",
            claim="Không đủ bằng chứng topology để kết luận các thiết bị chia sẻ đường đi hoặc quan hệ phụ thuộc.",
            evidence=[f"Số cảnh báo có ánh xạ topology: {mapped_count}/{alarm_count}."],
            limitations=["SHARED_PATH_UNVERIFIED", "DEPENDENCY_UNVERIFIED"],
            confidence_basis="FAIL_CLOSED_TOPOLOGY_GATE",
            confidence="HIGH",
        ))

    # Tier-2 Dominator Witness
    if dominator_info and dominator_info.get("witness_resource_id") and dominator_info.get("status") == "AVAILABLE":
        wit = dominator_info["witness_resource_id"]
        cov_cnt = len(dominator_info.get("covered_resource_ids", []))
        findings.append(_finding(
            "TOPOLOGY_DOMINATOR_WITNESS",
            kind="DERIVED",
            status="AVAILABLE",
            title="Tài nguyên chi phối Topo (Dominator Witness)",
            claim=f"Phát hiện tài nguyên chi phối '{wit}' bao quát {cov_cnt} tài nguyên trong cụm sự cố.",
            evidence=[
                f"Witness resource: {wit}.",
                f"Phạm vi bao quát: {cov_cnt} tài nguyên chịu ảnh hưởng trực tiếp.",
            ],
            limitations=["CAUSAL_DIRECTION_UNVERIFIED"],
            confidence_basis="TIER2_TOPOLOGY_HYPOTHESIS",
            confidence="HIGH",
        ))

    # Tier-2 Propagation Flow
    if propagation_info and propagation_info.get("hypotheses"):
        hyps = propagation_info["hypotheses"]
        findings.append(_finding(
            "TOPOLOGY_PROPAGATION_FLOW",
            kind="DERIVED",
            status="AVAILABLE",
            title="Luồng lan truyền đồ thị (RWR Flow)",
            claim=f"Mô hình lan truyền xác định luồng chuyển tiếp chính với {len(hyps)} liên kết xác suất cao.",
            evidence=[
                f"Liên kết: {h['source']} → {h['target']} (xác suất {h.get('prob', 0):.2f}, delta={h.get('delta_seconds', 0)}s)."
                for h in hyps[:3]
            ],
            limitations=["PROPAGATION_DIRECTION_UNVERIFIED"],
            confidence_basis="TIER2_PROPAGATION_MODEL",
            confidence="MEDIUM",
        ))

    if onsets and paths:
        first = onsets[0]
        later_devices = [item["device"] for item in onsets[1:]]
        findings.append(_finding(
            "PROPAGATION_COMPATIBLE_PATTERN",
            kind="HYPOTHESIS",
            status="AVAILABLE",
            title="Mẫu hình phù hợp với lan truyền",
            claim=(
                f"Thứ tự quan sát phù hợp với giả thuyết ảnh hưởng bắt đầu ở {first['device']} "
                f"rồi xuất hiện tại {', '.join(later_devices)}, trong cùng ngữ cảnh topology transit."
            ),
            evidence=[
                "Temporal order và topology connectivity cùng hướng tới một common-impact pattern.",
                "Đây là giả thuyết vận hành, không phải kết luận nguyên nhân gốc.",
            ],
            limitations=["ROOT_CAUSE_UNVERIFIED", "PROPAGATION_DIRECTION_UNVERIFIED"],
            confidence_basis="TEMPORAL_ORDER_PLUS_STRUCTURAL_CONNECTIVITY",
            confidence="MEDIUM",
        ))

    if audit_status == "EVALUATED":
        no_low_cut = str(audit_verdict) in (
            "NO_LOW_CONDUCTANCE_CUT",
            AuditVerdict.NO_LOW_CONDUCTANCE_CUT.value,
        )
        audit_claim = (
            "Audit Graph không tìm thấy ranh giới đủ yếu (không có vết cắt độ dẫn thấp trên đồ thị) để biện minh cho việc tách chuỗi."
            if no_low_cut
            else "Audit Graph phát hiện một ranh giới evidence cần được xem xét để tách chuỗi."
        )
        evidence = []
        if audit_detail.get("best_cut_label"):
            evidence.append(f"Phân hoạch được thử tốt nhất: {audit_detail['best_cut_label']}.")
        if audit_detail.get("phi") is not None and audit_detail.get("epsilon") is not None:
            comparator = ">" if no_low_cut else "≤"
            evidence.append(
                f"Phi={audit_detail['phi']:.3f} {comparator} ngưỡng tách epsilon={audit_detail['epsilon']:.3f}."
            )
        evidence.append("Audit Graph đo độ gắn kết evidence giữa alarm; không phải topology vật lý.")
        findings.append(_finding(
            "AUDIT_COHESION",
            kind="DERIVED",
            status="AVAILABLE",
            title="Kết luận gắn kết từ Audit Graph",
            claim=audit_claim,
            evidence=evidence,
            limitations=["AUDIT_GRAPH_IS_NOT_PHYSICAL_TOPOLOGY"],
            confidence_basis="TIER2_AUDIT_ARTIFACT",
            confidence="HIGH",
        ))
    else:
        reason = audit_reason or "Chưa có artifact kiểm định Tier-2 khả dụng."
        findings.append(_finding(
            "AUDIT_EVIDENCE_GAP",
            kind="LIMITATION",
            status="UNAVAILABLE",
            title="Structural audit unavailable",
            claim="Chưa thể kết luận về ranh giới phân tách trên Audit Graph.",
            evidence=[reason],
            limitations=["NO_AUDIT_FINDING_AVAILABLE"],
            confidence_basis="FAIL_CLOSED_AUDIT_GATE",
            confidence="HIGH",
        ))

    # Tier-2 Over-Merge Evaluation
    if over_merge_info and over_merge_info.get("structural_separation"):
        om_strength = over_merge_info.get("strength", "MODERATE")
        om_narrative = over_merge_info.get("narrative", "")
        findings.append(_finding(
            "OVER_MERGE_EVALUATION",
            kind="DERIVED",
            status="AVAILABLE",
            title="Đánh giá gộp chuỗi (Over-Merge Audit)",
            claim=f"Phân tích đa bằng chứng phát hiện dấu hiệu gộp thừa mức độ {om_strength}: {om_narrative or 'chuỗi có phân hoạch độc lập'}.",
            evidence=list(over_merge_info.get("driving_evidence", [])) or ["Ranh giới phân tách được xác nhận qua nhiều kênh evidence."],
            limitations=["REQUIRES_OPERATOR_SPLIT_CONFIRMATION"],
            confidence_basis="TIER2_OVER_MERGE_AUDIT",
            confidence="HIGH",
        ))

    priority = {
        "TEMPORAL_PROGRESSION": 0,
        "SHARED_TOPOLOGY_CONTEXT": 1,
        "TOPOLOGY_DOMINATOR_WITNESS": 2,
        "TOPOLOGY_PROPAGATION_FLOW": 3,
        "AUDIT_COHESION": 4,
        "OVER_MERGE_EVALUATION": 5,
        "PROPAGATION_COMPATIBLE_PATTERN": 6,
        "ALARM_CONCENTRATION": 7,
    }
    return sorted(findings, key=lambda item: priority.get(item["finding_id"], 10))



def extract_cohesion_context(
    service: Any,
    chain_id: str,
    analysis: Any | None = None,
    audit_artifact: Any | None = None,
    review_result: dict[str, Any] | None = None,
    audit_error_reason: str | None = None,
    deep_dive_analysis: Any | None = None,
    quality_assessment_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured facts across the authoritative data sources."""
    package = service.require_package()
    if analysis is None:
        analysis = service.analyze(chain_id)

    # Attempt to resolve deep dive analysis if not passed directly
    if deep_dive_analysis is not None:
        deep_dive_analysis = hydrate_persisted_deep_dive(deep_dive_analysis)

    if deep_dive_analysis is None and hasattr(service, "jobs"):
        try:
            job = service.jobs.latest_succeeded(
                package.snapshot.snapshot_id,
                package.snapshot.snapshot_version,
                chain_id,
            )
            if job is not None and job.result is not None:
                deep_dive_analysis = hydrate_persisted_deep_dive(job.result)
                if audit_artifact is None and getattr(job, "audit_artifact", None) is not None:
                    audit_artifact = job.audit_artifact
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 1. Raw Alarms of the Chain
    # -------------------------------------------------------------------------
    raw_alarms = package.alarms_of(chain_id)
    alarm_count = len(raw_alarms) if raw_alarms else getattr(analysis, "member_count", 1)

    alarm_names: list[str] = []
    network_classes: list[str] = []
    device_types: list[str] = []
    devices: list[str] = []
    start_times: list[str] = []
    severities: list[str] = []
    import datetime
    parsed_times: list[datetime.datetime] = []

    for alarm in raw_alarms:
        raw = alarm.raw if hasattr(alarm, "raw") and isinstance(alarm.raw, dict) else {}
        name = alarm.alarm_name or raw.get("alarm_name") or "Unknown Alarm"
        dev = alarm.device_code or raw.get("device_code") or raw.get("device_name")
        dev_type = raw.get("device_type_name") or raw.get("device_type")
        net_class = raw.get("network_class_name") or raw.get("network_class")
        sev = getattr(alarm, "severity_name", None) or raw.get("severity_name")
        s_time = alarm.canonical_start_time or raw.get("cah.start_time") or raw.get("start_time")

        if name:
            alarm_names.append(name)
        if dev:
            devices.append(dev)
        if dev_type:
            device_types.append(dev_type)
        if net_class:
            network_classes.append(net_class)
        if sev:
            severities.append(sev)
        if s_time:
            start_times.append(s_time)
            try:
                parsed_times.append(datetime.datetime.fromisoformat(s_time.replace("Z", "+00:00")))
            except Exception:
                pass

    parsed_times.sort()
    start_time_str = parsed_times[0].strftime("%H:%M:%S") if parsed_times else ""
    end_time_str = parsed_times[-1].strftime("%H:%M:%S") if parsed_times else ""

    # First observed alarm (T0 trigger)
    t0_alarm_info: dict[str, Any] | None = None
    if raw_alarms:
        def _get_st(a: Any) -> str:
            s = getattr(a, "canonical_start_time", None)
            if not s and hasattr(a, "raw") and isinstance(a.raw, dict):
                s = a.raw.get("cah.start_time") or a.raw.get("start_time")
            return str(s or "9999")
        sorted_by_time = sorted(raw_alarms, key=_get_st)
        first_a = sorted_by_time[0]
        first_raw = first_a.raw if hasattr(first_a, "raw") and isinstance(first_a.raw, dict) else {}
        first_id = getattr(first_a, "alarm_id", None) or first_raw.get("alarm_id") or ""
        first_name = getattr(first_a, "alarm_name", None) or first_raw.get("alarm_name") or "Unknown Alarm"
        first_dev = getattr(first_a, "device_code", None) or first_raw.get("device_code") or first_raw.get("device_name") or ""
        first_time = (
            getattr(first_a, "canonical_start_time", None)
            or first_raw.get("cah.start_time")
            or first_raw.get("start_time")
            or ""
        )
        t0_alarm_info = {
            "alarm_id": str(first_id),
            "alarm_name": first_name,
            "device_code": first_dev,
            "start_time": first_time,
        }

    # Top alarm types by frequency
    name_counts = Counter(alarm_names)
    top_alarm_types = [[name, count] for name, count in name_counts.most_common(3)]

    # Duration calculation
    duration_seconds: int | None = None
    if hasattr(analysis, "duration_seconds") and analysis.duration_seconds is not None:
        duration_seconds = int(analysis.duration_seconds)
    elif len(parsed_times) >= 2:
        duration_seconds = max(0, int((parsed_times[-1] - parsed_times[0]).total_seconds()))
    elif len(parsed_times) == 1:
        duration_seconds = 0

    duration_desc: str | None = None
    if duration_seconds is not None:
        if duration_seconds == 0:
            duration_desc = "đồng thời (0s)"
        elif duration_seconds < 60:
            duration_desc = f"{duration_seconds}s"
        else:
            duration_desc = f"{duration_seconds // 60}m {duration_seconds % 60}s"

    # Device concentration
    dev_counts = Counter(devices)
    distinct_devs = list(dev_counts.keys())
    dominant_device = dev_counts.most_common(1)[0][0] if dev_counts else None
    dominant_count = dev_counts.most_common(1)[0][1] if dev_counts else 0
    dominant_pct = round((dominant_count / max(1, alarm_count)) * 100, 1) if dev_counts else 0.0

    # Severities
    sev_counts = Counter(severities)
    top_severity = sev_counts.most_common(1)[0][0] if sev_counts else None

    # Cohesion factors (Rationale for grouping)
    cohesion_factors: list[str] = []
    if duration_desc and start_time_str and end_time_str and start_time_str != end_time_str:
        cohesion_factors.append(f"toàn bộ cảnh báo xuất hiện đồng bộ trong {duration_desc} (từ {start_time_str} đến {end_time_str})")
    elif duration_desc:
        cohesion_factors.append(f"toàn bộ cảnh báo diễn ra trong {duration_desc}")

    if dominant_pct == 100.0 and dominant_device:
        cohesion_factors.append(f"tập trung 100% trên thiết bị {dominant_device}")
    elif dominant_pct >= 50.0 and dominant_device:
        cohesion_factors.append(f"tập trung {dominant_pct}% trên thiết bị {dominant_device} ({dominant_count}/{alarm_count} sự kiện)")
    elif distinct_devs:
        cohesion_factors.append(f"ghi nhận trên {len(distinct_devs)} thiết bị ({', '.join(distinct_devs[:3])})")

    temporal_progression = _build_temporal_progression(list(raw_alarms))
    alarm_observation_groups = _build_alarm_observation_groups(list(raw_alarms))

    # -------------------------------------------------------------------------
    # 1b. Mapped, bounded topology connectivity discovery
    # -------------------------------------------------------------------------
    topo = getattr(package, "topology", {})
    raw_edges = topo.get("edges") if isinstance(topo, dict) else getattr(topo, "edges", ())
    raw_mappings = topo.get("mappings") if isinstance(topo, dict) else getattr(topo, "mappings", ())
    member_ids = {str(member_id) for member_id in package.members_of(chain_id)}
    alarm_devices = {
        str(getattr(alarm, "alarm_id", "")): str(getattr(alarm, "device_code", "") or "")
        for alarm in raw_alarms
    }
    topology_connectivity = _build_topology_connectivity(
        raw_mappings=raw_mappings,
        raw_edges=raw_edges,
        member_ids=member_ids,
        alarm_devices=alarm_devices,
    )
    connected_pair_count = topology_connectivity["connected_pair_count"]

    structural_insights: list[dict[str, str]] = []
    if connected_pair_count:
        pair_count = connected_pair_count
        pair_total = topology_connectivity["pair_total"]
        max_path_hops = topology_connectivity["max_path_hops"]
        cohesion_factors.append(
            f"{pair_count}/{pair_total} cặp resource có đường topology transit "
            f"trong tối đa {max_path_hops} hop"
        )
        structural_insights.append({
            "type": "TOPOLOGY_TRANSIT_CONNECTIVITY",
            "icon": "hub",
            "label": "Đường topology transit đã quan sát",
            "detail": (
                f"{pair_count}/{pair_total} cặp resource đã ánh xạ kết nối trong tối đa "
                f"{max_path_hops} hop; đây là connectivity, chưa phải dependency nhân quả"
            ),
            "en_detail": (
                f"{pair_count}/{pair_total} mapped resource pairs are connected within "
                f"{max_path_hops} hops; this is connectivity, not causal dependency"
            ),
        })

    # -------------------------------------------------------------------------
    # 1c. Structural Domain Insights (Binding Mechanisms)
    # -------------------------------------------------------------------------
    phy_keywords = ("portfault", "optical", "power", "los", "lof", "trunk", "physical", "interface down", "link down", "transceiver")
    proto_keywords = ("bgp", "vrrp", "ospf", "isis", "bfd", "mpls", "ldp", "routing")

    phy_alarms = [
        a for a in raw_alarms
        if any(k in ((getattr(a, "alarm_name", "") or "").lower()) for k in phy_keywords)
    ]
    proto_alarms = [
        a for a in raw_alarms
        if any(k in ((getattr(a, "alarm_name", "") or "").lower()) for k in proto_keywords)
    ]

    if phy_alarms and proto_alarms:
        phy_names = Counter((getattr(a, "alarm_name", "") or "") for a in phy_alarms).most_common(1)
        proto_names = Counter((getattr(a, "alarm_name", "") or "") for a in proto_alarms).most_common(1)
        phy_devs = sorted(list(set(getattr(a, "device_code", "") for a in phy_alarms if getattr(a, "device_code", ""))))
        proto_devs = sorted(list(set(getattr(a, "device_code", "") for a in proto_alarms if getattr(a, "device_code", ""))))

        phy_desc = f"'{phy_names[0][0]}' trên {', '.join(phy_devs[:2])}" if phy_names else "cảnh báo tầng vật lý/truyền dẫn"
        proto_desc = f"'{proto_names[0][0]}' trên {', '.join(proto_devs[:2])}" if proto_names else "cảnh báo giao thức"
        structural_insights.append({
            "type": "CROSS_LAYER",
            "icon": "cable",
            "label": "Chỉ dấu liên tầng quan sát (Vật lý & Giao thức)",
            "detail": f"ghi nhận đồng thời cảnh báo tầng truyền dẫn ({phy_desc}) và cảnh báo giao thức định tuyến ({proto_desc}) (cần kiểm chứng tô-pô liên kết)",
            "en_detail": f"observed co-occurrence of physical/transmission alarm ({phy_names[0][0] if phy_names else 'physical'}) and routing protocol alarm ({proto_names[0][0] if proto_names else 'protocol'}) (requires topology verification)",
        })

    if proto_alarms:
        proto_by_dev = Counter(getattr(a, "device_code", "") for a in proto_alarms if getattr(a, "device_code", ""))
        common_proto_devs = proto_by_dev.most_common(2)
        if len(common_proto_devs) == 2 and common_proto_devs[0][1] == common_proto_devs[1][1] and common_proto_devs[0][1] > 1:
            dev1, cnt1 = common_proto_devs[0]
            dev2, cnt2 = common_proto_devs[1]
            structural_insights.append({
                "type": "PEERING_SYMMETRY",
                "icon": "sync_alt",
                "label": "Mẫu hình phân bố đối xứng (Observed Symmetry)",
                "detail": f"ghi nhận {cnt1 * 2} cảnh báo giao thức phân bổ đều trên 2 thiết bị ({cnt1} sự kiện mỗi bên {dev1} ↔ {dev2}) (cần kiểm chứng phiên peering)",
                "en_detail": f"observed symmetrical alarm distribution: {cnt1 * 2} protocol alarms split evenly ({cnt1} each on {dev1} ↔ {dev2}) (requires peering topology verification)",
            })

    if top_alarm_types:
        prim_name, prim_cnt = top_alarm_types[0]
        prim_pct = round((prim_cnt / max(1, alarm_count)) * 100, 1)
        if prim_pct == 100.0:
            cohesion_factors.append(f"100% cảnh báo cùng chia sẻ loại lỗi '{prim_name}'")
        elif len(top_alarm_types) > 1 and (top_alarm_types[1][1] / max(1, alarm_count)) >= 0.15:
            sec_name, sec_cnt = top_alarm_types[1]
            sec_pct = round((sec_cnt / max(1, alarm_count)) * 100, 1)
            cohesion_factors.append(f"{prim_pct}% cảnh báo là loại lỗi '{prim_name}' kết hợp {sec_pct}% lỗi '{sec_name}'")
        else:
            cohesion_factors.append(f"{prim_pct}% cảnh báo là loại lỗi '{prim_name}'")

    for ins in structural_insights:
        cohesion_factors.append(ins["detail"])

    # -------------------------------------------------------------------------
    # 2. Chain WHY / Descriptors
    # -------------------------------------------------------------------------
    strong_views: list[str] = []
    partial_views: list[str] = []

    # Dynamic thresholds from service.config with safe calibrated fallbacks
    burst_gap = 488
    s_min = 0.60
    if hasattr(service, "config") and service.config is not None:
        try:
            burst_gap = int(service.config.value("temporal.burst.gap_seconds"))
        except Exception:
            pass
        try:
            s_min = float(service.config.value("role.s_min"))
        except Exception:
            pass

    # Check temporal burst: only valid when duration_seconds is known and <= burst_gap
    if duration_seconds is not None:
        if duration_seconds <= burst_gap and alarm_count > 1:
            strong_views.append("TEMPORAL_BURST")
        elif alarm_count > 1:
            partial_views.append("T_DELAY")

    # Check device concentration
    if dev_counts:
        top_dev_share = dominant_count / max(1, alarm_count)
        if top_dev_share >= s_min:
            strong_views.append("ENTITY_REFERENCE")
        else:
            partial_views.append("ENTITY_REFERENCE")

    descriptors = getattr(analysis, "descriptors", None)
    raw_desc: list[Any] = []
    if descriptors is not None:
        if hasattr(descriptors, "identity") and hasattr(descriptors, "contrastive"):
            raw_desc = [*getattr(descriptors, "identity", ()), *getattr(descriptors, "contrastive", ())]
        elif isinstance(descriptors, (list, tuple)):
            raw_desc = list(descriptors)

    top_descriptors: list[str] = []
    for d in raw_desc[:3]:
        lbl = getattr(d, "label", None) or (d.get("label") if isinstance(d, dict) else None)
        if lbl:
            top_descriptors.append(str(lbl))

    # -------------------------------------------------------------------------
    # 3. Topology Mapping
    # -------------------------------------------------------------------------
    mapped_count = len(topology_connectivity["mapped_alarm_ids"])
    resource_types = set(topology_connectivity["resource_types"])

    if mapped_count > 0:
        strong_views.append("TOPOLOGY")
    elif alarm_count > 1:
        partial_views.append("TOPOLOGY")

    # -------------------------------------------------------------------------
    # 4. Audit Artifacts
    # -------------------------------------------------------------------------
    candidate_cut = False
    conductance: float | None = None
    audit_status = "NOT_EVALUATED"
    audit_verdict: str | None = None
    audit_reason: str | None = None
    audit_detail: dict[str, Any] = {
        "phi": None,
        "epsilon": None,
        "best_cut_label": None,
        "partition_summary": None,
    }

    if audit_error_reason:
        audit_status = "UNAVAILABLE"
        audit_reason = audit_error_reason
    elif audit_artifact is not None:
        artifact_status = getattr(audit_artifact, "status", "")
        raw_verdict = getattr(audit_artifact, "verdict", None)
        audit_verdict = getattr(raw_verdict, "value", str(raw_verdict)) if raw_verdict is not None else None
        audit_reason = getattr(audit_artifact, "reason", None)
        audit_detail["epsilon"] = getattr(audit_artifact, "epsilon", None)
        best_cut_index = getattr(audit_artifact, "best_cut_index", None)
        scored_cuts = getattr(audit_artifact, "scored_cuts", ())

        if scored_cuts and best_cut_index is not None and 0 <= best_cut_index < len(scored_cuts):
            best_cut = scored_cuts[best_cut_index]
            audit_detail["phi"] = getattr(
                best_cut, "phi", getattr(best_cut, "conductance", None)
            )
            audit_detail["best_cut_label"] = getattr(best_cut, "label", None)
            audit_detail["partition_summary"] = _build_audit_partition_summary(
                raw_alarms=list(raw_alarms),
                best_cut=best_cut,
                visualization=getattr(audit_artifact, "visualization", None),
                topology_connectivity=topology_connectivity,
            )

        # Artifact status for valid computed review audit artifacts is "AVAILABLE"
        if artifact_status in ("AVAILABLE", "SUCCEEDED", "COMPLETE", "VALID"):
            if audit_verdict == AuditVerdict.CANDIDATE_SPLIT.value:
                audit_status = "EVALUATED"
                candidate_cut = True
                if audit_detail["phi"] is not None:
                    conductance = audit_detail["phi"]
                elif scored_cuts:
                    conductance = getattr(scored_cuts[0], "phi", getattr(scored_cuts[0], "conductance", None))
            elif audit_verdict == AuditVerdict.NO_LOW_CONDUCTANCE_CUT.value:
                audit_status = "EVALUATED"
                candidate_cut = False
                conductance = audit_detail["phi"]
            elif audit_verdict == AuditVerdict.SKIPPED_SMALL_CHAIN.value:
                audit_status = "NOT_APPLICABLE"
                candidate_cut = False
            elif audit_verdict == AuditVerdict.UNAVAILABLE.value:
                audit_status = "UNAVAILABLE"
                candidate_cut = False
            else:
                audit_status = "EVALUATED"
        elif artifact_status in ("FAILED", "UNAVAILABLE"):
            audit_status = "UNAVAILABLE"
        else:
            audit_status = "UNAVAILABLE"

    # -------------------------------------------------------------------------
    # 5. Counterfactual Recommendations
    # -------------------------------------------------------------------------
    recommendation_summary = _resolve_recommendations(review_result)
    split_recommended = recommendation_summary["split_recommended"]

    # -------------------------------------------------------------------------
    # 1b. Role breakdown from Tier-1B Analysis
    # -------------------------------------------------------------------------
    roles_raw = getattr(analysis, "role_counts", None)
    role_counts = roles_raw() if callable(roles_raw) else (roles_raw if isinstance(roles_raw, dict) else {})
    members_map = getattr(analysis, "members", {}) or {}
    weak_members: list[str] = []
    insufficient_members: list[str] = []
    core_members: list[str] = []
    for a_id, m in members_map.items():
        v = getattr(getattr(m, "role", None), "verdict", None)
        v_str = getattr(v, "value", str(v)) if v is not None else ""
        if v_str == "WEAK":
            weak_members.append(str(a_id))
        elif v_str == "INSUFFICIENT_DATA":
            insufficient_members.append(str(a_id))
        elif v_str == "CORE":
            core_members.append(str(a_id))

    representative_member = select_representative_member(
        members_map,
        {
            str(getattr(alarm, "alarm_id", "")): alarm
            for alarm in raw_alarms
        },
    )

    # -------------------------------------------------------------------------
    # 4b. Tier-2 Deep Dive Capabilities (Dominator, Propagation, OverMerge, Attribution)
    # -------------------------------------------------------------------------
    dominator_info: dict[str, Any] | None = None
    propagation_info: dict[str, Any] | None = None
    over_merge_info: dict[str, Any] | None = None
    evidence_attribution_info: dict[str, Any] | None = None

    if deep_dive_analysis is not None:
        top_hyp = getattr(deep_dive_analysis, "topology_hypotheses", None)
        if top_hyp is not None:
            dom = getattr(top_hyp, "dominator", None)
            if dom is not None:
                dom_st = getattr(getattr(dom, "status", None), "value", str(getattr(dom, "status", "")))
                dominator_info = {
                    "status": dom_st,
                    "witness_resource_id": getattr(dom, "witness_resource_id", None),
                    "covered_resource_ids": list(getattr(dom, "covered_resource_ids", ())),
                    "semantic": getattr(dom, "semantic", None),
                    "relation_type": getattr(dom, "relation_type", None),
                }

            prop = getattr(top_hyp, "propagation", None)
            if prop is not None:
                prop_st = getattr(getattr(prop, "status", None), "value", str(getattr(prop, "status", "")))
                prop_scores = getattr(prop, "node_scores", ())
                prop_hyps = getattr(prop, "hypotheses", ())
                propagation_info = {
                    "status": prop_st,
                    "candidate_node_count": getattr(prop, "candidate_node_count", 0),
                    "candidate_edge_count": getattr(prop, "candidate_edge_count", 0),
                    "top_node_scores": [
                        {"alarm_id": n.alarm_id, "score": round(float(n.score), 4)}
                        for n in list(prop_scores)[:5]
                    ],
                    "hypotheses": [
                        {
                            "source": h.source_alarm_id,
                            "target": h.target_alarm_id,
                            "score": round(float(h.score), 3),
                            "prob": round(float(h.transition_probability), 3),
                            "delta_seconds": round(float(h.temporal_delta_seconds), 1),
                        }
                        for h in list(prop_hyps)[:5]
                    ],
                }

        ev_attr = getattr(deep_dive_analysis, "evidence_attribution", None)
        if ev_attr is not None:
            ev_st = getattr(getattr(ev_attr, "status", None), "value", str(getattr(ev_attr, "status", "")))
            conts = getattr(ev_attr, "contributions", ())
            evidence_attribution_info = {
                "status": ev_st,
                "total_coverage": getattr(ev_attr, "total_coverage", None),
                "contributions": [
                    {
                        "group_id": c.group_id,
                        "derivation_tag": getattr(c, "derivation_tag", ""),
                        "attribution": round(float(c.attribution), 3),
                        "supported_pairs": getattr(c, "supported_pair_count", 0),
                    }
                    for c in list(conts)[:5]
                ],
            }

        om = getattr(deep_dive_analysis, "over_merge", None)
        if om is not None:
            om_str = getattr(getattr(om, "strength", None), "value", str(getattr(om, "strength", "")))
            over_merge_info = {
                "structural_separation": bool(getattr(om, "structural_separation", False)),
                "cross_evidence_agreement": bool(getattr(om, "cross_evidence_agreement", False)),
                "strength": om_str,
                "narrative": getattr(om, "narrative", ""),
                "driving_evidence": list(getattr(om, "driving_evidence", ())),
            }

    analytical_findings = _build_analytical_findings(
        alarm_count=alarm_count,
        top_alarm_types=top_alarm_types,
        mapped_count=mapped_count,
        topology_connectivity=topology_connectivity,
        temporal_progression=temporal_progression,
        audit_status=audit_status,
        audit_verdict=audit_verdict,
        audit_reason=audit_reason,
        audit_detail=audit_detail,
        dominator_info=dominator_info,
        propagation_info=propagation_info,
        over_merge_info=over_merge_info,
    )

    actionable_takeaway = (
        "Đề xuất tách chuỗi (SPLIT) để phân lập các luồng sự cố độc lập cho các nhóm xử lý song song."
        if split_recommended
        else (
            "Audit Graph phát hiện ranh giới phân tách có độ dẫn thấp; kỹ sư trực NOC nên đối soát cấu hình phân đoạn trước khi xử lý gộp."
            if candidate_cut
            else (
                "Chuỗi có độ gắn kết cao và thuần nhất; khuyến nghị kỹ sư NOC tập trung xử lý tại thiết bị khởi phát và rà soát các liên kết downstream theo đường transit."
                if audit_status == "EVALUATED"
                else (
                    "Counterfactual đã hoàn tất nhưng Audit Graph P2 chưa chạy; "
                    "khuyến nghị theo dõi thiết bị khởi phát và chờ kiểm định cấu trúc."
                    if recommendation_summary["evaluation_completed"]
                    else "Đang ở giai đoạn phân tích sơ bộ; khuyến nghị theo dõi thiết bị khởi phát và chờ kết quả kiểm định chuyên sâu P2."
                )
            )
        )
    )
    operational_insights = {
        "primary_focus": dominant_device or (t0_alarm_info.get("device_code") if t0_alarm_info and t0_alarm_info.get("device_code") else "Core Device"),
        "t0_trigger": t0_alarm_info,
        "cohesion_verdict": "STRONG" if audit_status == "EVALUATED" and str(audit_verdict) in ("NO_LOW_CONDUCTANCE_CUT", AuditVerdict.NO_LOW_CONDUCTANCE_CUT.value) else ("SEPARABLE" if candidate_cut else "PRELIMINARY"),
        "over_merge_alert": bool(over_merge_info and over_merge_info.get("structural_separation") and str(over_merge_info.get("strength", "")).upper() in ("STRONG", "MODERATE")),
        "actionable_takeaway": actionable_takeaway,
    }

    mapped_device_count = len(topology_connectivity["mapped_device_ids"])
    total_device_count = len(distinct_devs)
    device_mapping_ratio = (
        mapped_device_count / total_device_count if total_device_count else None
    )
    quality_assessment = (
        quality_assessment_override
        if isinstance(quality_assessment_override, dict)
        else build_chain_quality_assessment(
            alarm_count=alarm_count,
            role_counts=role_counts,
            mapped_device_count=mapped_device_count,
            total_device_count=total_device_count,
            connected_pair_count=topology_connectivity["connected_pair_count"],
            pair_total=topology_connectivity["pair_total"],
            audit_status=audit_status,
            audit_verdict=audit_verdict,
            over_merge_strength=(over_merge_info or {}).get("strength"),
            recommendation_count=recommendation_summary["count"],
            recommendation_status=recommendation_summary["status"],
            recommendation_evaluation_completed=recommendation_summary["evaluation_completed"],
        )
    )

    return {
        "chain": {
            "chain_id": chain_id,
            "alarm_count": alarm_count,
            "duration_seconds": duration_seconds,
            "duration_desc": duration_desc,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "is_singleton": alarm_count == 1,
        },
        "alarm_summary": {
            "top_alarm_types": top_alarm_types,
            "network_classes": sorted(list(set(network_classes)))[:3],
            "device_types": sorted(list(set(device_types)))[:3],
            "devices": sorted(list(set(devices))),
            "dominant_device": dominant_device,
            "dominant_count": dominant_count,
            "dominant_pct": dominant_pct,
            "top_severity": top_severity,
            "severity_counts": dict(sev_counts),
            "t0_alarm": t0_alarm_info,
        },
        "roles": {
            "counts": role_counts,
            "core_count": len(core_members),
            "weak_count": len(weak_members),
            "weak_members": weak_members[:4],
            "insufficient_count": len(insufficient_members),
            "insufficient_members": insufficient_members[:4],
        },
        "representative_member": representative_member,
        "alarm_observation_groups": alarm_observation_groups,
        "cohesion_factors": cohesion_factors,
        "structural_insights": structural_insights,
        "temporal_progression": temporal_progression,
        "analytical_findings": analytical_findings,
        "why": {
            "strong_views": strong_views,
            "partial_views": partial_views,
            "top_descriptors": top_descriptors,
        },
        "topology": {
            "mapped": mapped_count,
            "total": alarm_count,
            "mapped_device_count": mapped_device_count,
            "total_device_count": total_device_count,
            "device_mapping_ratio": (
                round(device_mapping_ratio, 4)
                if device_mapping_ratio is not None else None
            ),
            "resource_types": sorted(list(resource_types))[:4],
            "mapped_resources": topology_connectivity["mapped_resources"],
            "display_paths": topology_connectivity["display_paths"],
            "display_paths_truncated": topology_connectivity["display_paths_truncated"],
            "connected_pair_count": topology_connectivity["connected_pair_count"],
            "pair_total": topology_connectivity["pair_total"],
            "max_path_hops": topology_connectivity["max_path_hops"],
            "shared_transit_resources": topology_connectivity["shared_transit_resources"],
            "dependency_verified": False,
        },
        "audit": {
            "status": audit_status,
            "verdict": audit_verdict,
            "reason": audit_reason,
            "candidate_cut": candidate_cut,
            "conductance": round(conductance, 3) if conductance is not None else None,
            "epsilon": audit_detail["epsilon"],
            "best_cut_label": audit_detail["best_cut_label"],
            "partition_summary": audit_detail["partition_summary"],
        },
        "recommendations": recommendation_summary,
        "quality_assessment": quality_assessment,
        "tier2_p2": {
            "dominator": dominator_info,
            "propagation": propagation_info,
            "evidence_attribution": evidence_attribution_info,
            "over_merge": over_merge_info,
        },
        "operational_insights": operational_insights,
    }


def build_deterministic_cohesion_narrative(context: dict[str, Any], language: str = "en") -> str:
    """Compose a fluent, natural domain-expert narrative from structured facts."""
    chain = context.get("chain", {})
    alarm_summary = context.get("alarm_summary", {})
    topology = context.get("topology", {})
    audit = context.get("audit", {})
    chain_id = chain.get("chain_id", "Unknown")
    alarm_count = chain.get("alarm_count", 1)
    is_singleton = chain.get("is_singleton", False)
    top_alarms = alarm_summary.get("top_alarm_types", [])
    network_classes = alarm_summary.get("network_classes", [])
    devices = alarm_summary.get("devices", [])
    res_types = topology.get("resource_types", [])
    candidate_cut = audit.get("candidate_cut", False)
    conductance = audit.get("conductance")
    audit_status = audit.get("status", "NOT_EVALUATED")
    audit_verdict = audit.get("verdict")
    audit_reason = audit.get("reason")

    if language == "vi":
        if is_singleton:
            return (
                "Chuỗi này chỉ chứa 1 cảnh báo được ghi nhận. "
                "Phân tích độ gắn kết và lan truyền đa thành viên không áp dụng."
            )
        partition = audit.get("partition_summary") or {}
        if candidate_cut and partition.get("status") == "AVAILABLE":
            side_a = partition.get("side_a") or {}
            side_b = partition.get("side_b") or {}

            def side_phrase(side: dict[str, Any]) -> str:
                side_devices = side.get("devices") or []
                side_types = side.get("alarm_types") or []
                device_text = ", ".join(str(item.get("device")) for item in side_devices[:3])
                type_text = ", ".join(
                    f"'{item.get('alarm_name')}'"
                    for item in side_types[:2]
                    if item.get("alarm_name")
                )
                phrase = f"{int(side.get('alarm_count', 0) or 0)} cảnh báo"
                if device_text:
                    phrase += f" quanh {device_text}"
                if type_text:
                    phrase += f", chủ yếu là {type_text}"
                return phrase

            first = (
                "Audit nhận diện một ranh giới giữa hai cụm quan sát: "
                f"một cụm gồm {side_phrase(side_a)}; cụm còn lại gồm {side_phrase(side_b)}."
            )

            linkage = partition.get("linkage") or {}
            linkage_parts: list[str] = []
            onset_gap = linkage.get("onset_gap_seconds")
            if onset_gap is not None:
                linkage_parts.append(f"hai cụm bắt đầu cách nhau {_format_offset(int(onset_gap))}")
            paths = linkage.get("topology_paths") or []
            if paths:
                path = paths[0]
                path_text = " → ".join(str(node) for node in path.get("path") or [])
                hop_count = int(path.get("hop_count") or 0)
                if hop_count == 1:
                    topology_text = "hai phía nối trực tiếp trong topology"
                else:
                    topology_text = f"hai phía nối nhau qua {hop_count} hop topology"
                if path_text:
                    topology_text += f" ({path_text})"
                linkage_parts.append(topology_text)
            evidence_groups = linkage.get("supporting_groups") or []
            if evidence_groups:
                group_text = ", ".join(
                    str(item.get("label_vi")) for item in evidence_groups[:3]
                )
                linkage_parts.append(f"cạnh nối giữa hai cụm dựa trên {group_text}")
            second = (
                "Hai cụm được đặt trong cùng chain vì " + "; ".join(linkage_parts) + "."
                if linkage_parts
                else "Hai cụm đang nằm trong cùng chain, nhưng chưa có đủ chi tiết để giải thích cơ chế liên kết giữa chúng."
            )

            separation = partition.get("separation") or {}
            cross_edges = int(separation.get("cross_edge_count", 0) or 0)
            internal_edges = int(separation.get("internal_edge_count", 0) or 0)
            complete = bool(separation.get("edge_counts_are_complete"))
            if complete and internal_edges > 0:
                weakness = (
                    f"chỉ {cross_edges} cạnh evidence đi xuyên giữa hai cụm, trong khi "
                    f"{internal_edges} cạnh còn lại giữ các cảnh báo trong từng cụm"
                )
            elif cross_edges > 0:
                weakness = (
                    f"phần graph quan sát được chỉ có {cross_edges} cạnh evidence đi xuyên giữa hai cụm"
                )
            else:
                weakness = "evidence đi xuyên giữa hai cụm không đủ mạnh so với liên kết bên trong từng cụm"
            third = (
                f"Điểm yếu nằm ở ranh giới này: {weakness}; cần đối chiếu phiên, cổng hoặc đối tượng mạng tương ứng "
                "trước khi xử lý toàn bộ như một sự cố duy nhất."
            )
            return f"{first} {second} {third}"

        temporal = context.get("temporal_progression") or {}
        waves = temporal.get("waves") or []
        cross_layer = any(
            insight.get("type") == "CROSS_LAYER"
            for insight in context.get("structural_insights", [])
            if isinstance(insight, dict)
        )
        pattern_parts: list[str] = []
        if top_alarms:
            pattern_parts.append(
                f"{top_alarms[0][1]}/{alarm_count} cảnh báo thuộc nhóm '{top_alarms[0][0]}'"
            )
        if waves:
            first_wave_devices = ", ".join(waves[0].get("devices") or [])
            if first_wave_devices:
                pattern_parts.append(f"đợt đầu xuất hiện đồng thời trên {first_wave_devices}")
        if len(waves) > 1:
            later_wave = waves[1]
            offset_seconds = int(later_wave.get("offset_seconds") or 0)
            offset_text = (
                f"{offset_seconds // 60}m {offset_seconds % 60}s"
                if offset_seconds >= 60
                else f"{offset_seconds}s"
            )
            later_devices = ", ".join(later_wave.get("devices") or [])
            later_names = ", ".join(later_wave.get("alarm_names") or [])
            if later_devices:
                later_detail = f"sau {offset_text}, {later_devices} mới xuất hiện"
                if later_names:
                    later_detail += f" cảnh báo '{later_names}'"
                pattern_parts.append(later_detail)

        pattern_label = "mẫu liên tầng" if cross_layer else "mẫu đồng diễn"
        if pattern_parts:
            first = f"Dữ liệu cho thấy một {pattern_label}: {'; '.join(pattern_parts[:3])}."
        else:
            first = "Chưa có đủ diễn tiến chi tiết để rút ra mẫu sự cố rõ ràng."

        structural_parts: list[str] = []
        max_hops = topology.get("max_path_hops")
        connected_pair_count = int(topology.get("connected_pair_count", 0) or 0)
        pair_total = int(topology.get("pair_total", 0) or 0)
        if connected_pair_count and max_hops is not None:
            structural_parts.append(
                f"Có {connected_pair_count}/{pair_total} cặp resource đã ánh xạ có đường transit "
                f"topology trong giới hạn {max_hops} hop"
            )
        if audit_status == "EVALUATED" and audit_verdict == AuditVerdict.NO_LOW_CONDUCTANCE_CUT.value:
            structural_parts.append("Audit chưa tìm thấy ranh giới đủ yếu để tách nhóm evidence")
        elif audit_status == "EVALUATED" and audit_verdict == AuditVerdict.CANDIDATE_SPLIT.value:
            structural_parts.append("Audit phát hiện ranh giới có thể tách chuỗi")

        second_parts = [part for part in structural_parts[:2] if part]
        return first if not second_parts else f"{first} {'; '.join(second_parts)}."

    # 1. Singleton narrative (Strict adherence to data truth: no speculative isolation or propagation claims)
    if is_singleton:
        return (
            "This chain contains one observed alarm. "
            "Multi-member cohesion and propagation analysis are not applicable."
        )

    # 2. Multi-alarm composition sentence
    net_str = f"{', '.join(network_classes)} " if network_classes else ""
    if top_alarms:
        primary_name = top_alarms[0][0]
        primary_count = top_alarms[0][1]
        secondary_name = top_alarms[1][0] if len(top_alarms) > 1 else None

        if primary_count == alarm_count:
            composition_clause = f"dominated entirely by {alarm_count} '{primary_name}' events"
        elif secondary_name:
            composition_clause = (
                f"predominantly composed of {primary_count} '{primary_name}' events "
                f"alongside '{secondary_name}'"
            )
        else:
            composition_clause = f"primarily composed of {primary_count} '{primary_name}' events"
    else:
        composition_clause = f"composed of {alarm_count} correlated alarms"

    dev_clause = f" across {len(devices)} device(s) ({', '.join(devices[:2])})" if devices else ""
    res_clause = f" covering {', '.join(res_types[:2])} infrastructure" if res_types else ""

    sentence_1 = f"Chain {chain_id} is a {net_str}cluster {composition_clause}{dev_clause}{res_clause}."

    # 3. Structural audit & recommendation sentence
    if candidate_cut or audit_verdict == AuditVerdict.CANDIDATE_SPLIT.value:
        cond_str = f" (conductance {conductance:.2f})" if conductance is not None else ""
        sentence_2 = (
            f"Structural audit detected a low-conductance separation boundary between member groups{cond_str}, "
            "meaning the observed evidence is stronger within the groups than across their boundary."
        )
    elif audit_status == "EVALUATED" and audit_verdict == AuditVerdict.NO_LOW_CONDUCTANCE_CUT.value:
        sentence_2 = "Structural audit evaluated candidate partitions and detected no low-conductance partition boundaries."
    elif audit_status == "NOT_APPLICABLE" or audit_verdict == AuditVerdict.SKIPPED_SMALL_CHAIN.value:
        sentence_2 = "Structural audit balance constraints are not applicable for this small chain structure."
    elif audit_status == "UNAVAILABLE" or audit_verdict == AuditVerdict.UNAVAILABLE.value:
        reason_clause = f" ({audit_reason})" if audit_reason else ""
        sentence_2 = f"Structural audit is currently unavailable for this chain{reason_clause}."
    else:
        # NOT_EVALUATED
        sentence_2 = "Tier-2 structural audit has not been performed for this chain."

    return f"{sentence_1} {sentence_2}"


def _build_investigation_evidence(context: dict[str, Any]) -> dict[str, Any]:
    """Select bounded, high-value evidence for LLM investigation synthesis."""
    topology = context.get("topology") or {}
    p2 = context.get("tier2_p2") or {}
    binding_observations = [
        {
            "type": item.get("type"),
            "label": item.get("label"),
            "detail": item.get("detail"),
        }
        for item in (context.get("structural_insights") or [])[:8]
        if isinstance(item, dict)
    ]
    findings = [
        {
            "finding_id": item.get("finding_id"),
            "kind": item.get("kind"),
            "status": item.get("status"),
            "claim": item.get("claim"),
            "limitations": (item.get("limitations") or [])[:4],
        }
        for item in (context.get("analytical_findings") or [])[:6]
        if isinstance(item, dict)
    ]
    return {
        "observation_window": context.get("chain") or {},
        "alarm_groups": (context.get("alarm_observation_groups") or [])[:8],
        "device_onsets": (context.get("temporal_progression") or {}).get("device_onsets", [])[:12],
        "grouping_dimensions": context.get("why") or {},
        "binding_observations": binding_observations,
        "topology": {
            "paths": (topology.get("display_paths") or [])[:2],
            "connected_pair_count": topology.get("connected_pair_count", 0),
            "pair_total": topology.get("pair_total", 0),
            "max_path_hops": topology.get("max_path_hops"),
            "display_paths_truncated": topology.get("display_paths_truncated", False),
            "shared_transit_resources": (topology.get("shared_transit_resources") or [])[:5],
            "dependency_verified": topology.get("dependency_verified", False),
        },
        "audit": context.get("audit") or {},
        "member_roles": context.get("roles") or {},
        "representative_member": context.get("representative_member"),
        "tier2": {
            "dominator": p2.get("dominator"),
            "propagation": p2.get("propagation"),
            "evidence_attribution": p2.get("evidence_attribution"),
            "over_merge": p2.get("over_merge"),
        },
        "findings": findings,
        "interpretation_rules": {
            "topology_path": "structural connectivity only, not causal direction",
            "temporal_order": "observation order only, not propagation proof",
            "representative_member": "strong evidence representative, not root cause",
            "audit_cut": "possible over-merge boundary, not an automatic split decision",
        },
    }


def _deterministic_investigation_message(
    context: dict[str, Any], *, language: str
) -> str:
    """Build optional context for the provider without creating a user fallback.

    This text is only sent as bounded grounding context.  If the provider is
    unavailable or its prose is rejected, the caller returns an empty
    narrative and a diagnostic status instead of exposing this draft as if it
    were AI output.
    """
    is_singleton = bool(context.get("chain", {}).get("is_singleton"))
    if is_singleton:
        return ""

    progression = context.get("temporal_progression") or {}
    t0 = progression.get("t0") or {}
    later = next(
        (
            wave for wave in progression.get("waves", [])
            if isinstance(wave, dict) and float(wave.get("offset_seconds") or 0) > 0
        ),
        None,
    )
    topology = context.get("topology") or {}
    path = next(iter(topology.get("display_paths") or []), None)
    audit = context.get("audit") or {}
    sentences: list[str] = []

    if language == "vi":
        if t0 and later:
            later_devices = ", ".join(later.get("devices") or []) or "thiết bị kế tiếp"
            later_alarms = ", ".join(later.get("alarm_names") or []) or "cảnh báo kế tiếp"
            seconds = int(float(later.get("offset_seconds") or 0))
            sentences.append(
                f"Điểm cần kiểm tra là '{t0.get('alarm_name')}' được ghi nhận trước trên "
                f"{t0.get('device')}, còn '{later_alarms}' xuất hiện trên {later_devices} sau "
                f"{seconds} giây; đây là thứ tự quan sát, chưa phải bằng chứng về hướng lan truyền."
            )
        if isinstance(path, dict):
            source_devices = ", ".join(path.get("source_devices") or []) or str(path.get("source"))
            target_devices = ", ".join(path.get("target_devices") or []) or str(path.get("target"))
            sentences.append(
                f"Hai phía {source_devices} và {target_devices} có đường cấu trúc {path.get('relation_type')} "
                f"dài {path.get('hop_count')} hop; đường này giải thích vì sao chúng được đặt trong cùng phạm vi kiểm tra, "
                "nhưng không xác nhận quan hệ phụ thuộc có hướng."
            )
        if audit.get("candidate_cut"):
            partition = audit.get("partition_summary") or {}
            side_a = partition.get("side_a") or {}
            side_b = partition.get("side_b") or {}
            devices_a = ", ".join(str(item.get("device")) for item in side_a.get("devices", [])[:3])
            devices_b = ", ".join(str(item.get("device")) for item in side_b.get("devices", [])[:3])
            if devices_a and devices_b:
                sentences.append(
                    f"Điểm yếu của chain nằm giữa nhóm {devices_a} và nhóm {devices_b}: Audit tìm thấy ranh giới cấu trúc, "
                    "nên cần đối chiếu phiên, cổng hoặc component chung trước khi xử lý như một sự cố duy nhất."
                )
        elif str(audit.get("verdict") or "").upper() == "NO_LOW_CONDUCTANCE_CUT":
            sentences.append(
                "Các cạnh evidence hiện chưa tạo thành hai cụm tách biệt đủ rõ; nên đối chiếu đối tượng chung trên đường topology "
                "thay vì suy ra nguyên nhân chỉ từ thứ tự thời gian."
            )
        return " ".join(sentences[:3])

    if t0 and later:
        sentences.append(
            f"The first observed alarm was {t0.get('alarm_name')} on {t0.get('device')}; "
            f"the next wave appeared {int(float(later.get('offset_seconds') or 0))} seconds later, "
            "which establishes observed order but not propagation."
        )
    if isinstance(path, dict):
        sentences.append(
            f"A bounded {path.get('relation_type')} path of {path.get('hop_count')} hops links the observed resources; "
            "this supports shared structural scope, not causal direction."
        )
    return " ".join(sentences)


def _briefing_avoids_card_metadata(message: str, *, language: str) -> bool:
    if not message.strip():
        return False
    if language != "vi":
        return True
    forbidden_card_terms = (
        "counterfactual",
        "hard gate",
        "policy chưa",
        "mức sao",
        "/5 sao",
    )
    lowered = message.lower()
    return (
        "Các 7 " not in message
        and not any(term in lowered for term in forbidden_card_terms)
    )


def generate_cohesion_narrative(
    service: Any,
    chain_id: str,
    audit_artifact: Any | None = None,
    review_result: dict[str, Any] | None = None,
    audit_error_reason: str | None = None,
    deep_dive_analysis: Any | None = None,
    persisted_quality_assessment: dict[str, Any] | None = None,
    language: str = "vi",
) -> CohesionNarrativeResult:
    """Generate a grounded narrative, optionally polished by an LLM."""
    service.require_package()
    analysis = service.analyze(chain_id)

    # Extract sources context
    context = extract_cohesion_context(
        service=service,
        chain_id=chain_id,
        analysis=analysis,
        audit_artifact=audit_artifact,
        review_result=review_result,
        audit_error_reason=audit_error_reason,
        deep_dive_analysis=hydrate_persisted_deep_dive(deep_dive_analysis),
        quality_assessment_override=persisted_quality_assessment,
    )

    # This deterministic text is supplied to the model as grounding context;
    # it is not used as a replacement for the provider's answer.
    deterministic_draft = _deterministic_investigation_message(context, language=language)

    # Prepare grounding claims
    claims: list[str] = [
        f"Chain ID: {chain_id}",
        f"Alarm count: {context['chain']['alarm_count']}",
    ]
    if context["chain"].get("duration_desc"):
        claims.append(f"Duration: {context['chain']['duration_desc']}")
    if context["chain"]["duration_seconds"] is not None:
        claims.append(f"Duration seconds: {context['chain']['duration_seconds']}")
    if context["chain"].get("start_time"):
        claims.append(f"Start time: {context['chain']['start_time']}")
    if context["chain"].get("end_time"):
        claims.append(f"End time: {context['chain']['end_time']}")

    # T0 Onset Trigger
    t0 = context.get("alarm_summary", {}).get("t0_alarm")
    if t0:
        claims.append(f"Onset T0 alarm: '{t0.get('alarm_name')}' on device {t0.get('device_code')} at {t0.get('start_time')}")
        if t0.get("device_code"):
            claims.append(f"Initial onset device: {t0.get('device_code')}")

    # Temporal waves
    waves = context.get("temporal_progression", {}).get("waves", [])
    for idx, wave in enumerate(waves[:5]):
        claims.append(f"Temporal Wave {idx}: offset +{wave.get('offset_seconds', 0)}s on devices {', '.join(wave.get('devices', []))}")

    if context["alarm_summary"].get("dominant_device"):
        claims.append(f"Dominant device: {context['alarm_summary']['dominant_device']} ({context['alarm_summary']['dominant_count']} alarms, {context['alarm_summary']['dominant_pct']}%)")
    if context["alarm_summary"].get("top_severity"):
        claims.append(f"Severity: {context['alarm_summary']['top_severity']}")
    for factor in context.get("cohesion_factors", []):
        claims.append(f"Cohesion factor: {factor}")
    if context["alarm_summary"]["top_alarm_types"]:
        for name, cnt in context["alarm_summary"]["top_alarm_types"]:
            pct = round((cnt / max(1, context['chain']['alarm_count'])) * 100, 1)
            claims.append(f"Alarm type: {name} (count: {cnt}, {pct}%)")
    if context["alarm_summary"]["network_classes"]:
        claims.append(f"Network classes: {', '.join(context['alarm_summary']['network_classes'])}")
    if context["alarm_summary"]["devices"]:
        claims.append(f"Devices ({len(context['alarm_summary']['devices'])}): {', '.join(context['alarm_summary']['devices'])}")
    representative = context.get("representative_member") or {}
    if representative.get("status") == "AVAILABLE":
        claims.append(
            "Evidence representative (not root cause): "
            f"{representative.get('alarm_name') or representative.get('alarm_id')} on "
            f"{representative.get('device_code') or 'unknown device'}; "
            f"role={representative.get('role')}; "
            f"support={representative.get('membership_support')}"
        )
    if context["topology"]["resource_types"]:
        claims.append(f"Topology resources: {', '.join(context['topology']['resource_types'])}")
    claims.append(f"Mapped alarms: {context['topology']['mapped']} of {context['topology']['total']}")
    for pair in (context.get("topology", {}).get("display_paths") or [])[:2]:
        claims.append(
            f"Bounded topology path: {pair['source']} reaches {pair['target']} in "
            f"{pair['hop_count']} hops via {pair['relation_type']}; traversal semantic is "
            f"{pair['traversal_semantic']}"
        )
    claims.append(f"Candidate cut detected: {context['audit']['candidate_cut']}")
    if context["audit"]["conductance"] is not None:
        claims.append(f"Conductance: {context['audit']['conductance']}")
    if context["audit"].get("epsilon") is not None:
        claims.append(f"Cut threshold epsilon: {context['audit']['epsilon']}")
    if context["audit"].get("verdict"):
        claims.append(f"Audit verdict: {context['audit']['verdict']}")
    partition = context["audit"].get("partition_summary") or {}
    if partition.get("status") == "AVAILABLE":
        for side_name in ("side_a", "side_b"):
            side = partition.get(side_name) or {}
            devices = ", ".join(
                f"{item.get('device')} ({item.get('alarm_count')} alarms)"
                for item in side.get("devices", [])
            )
            alarm_types = ", ".join(
                f"{item.get('alarm_name')} ({item.get('alarm_count')})"
                for item in side.get("alarm_types", [])
            )
            claims.append(
                f"Audit partition {side_name}: {side.get('alarm_count')} alarms; "
                f"devices={devices or 'unknown'}; alarm types={alarm_types or 'unknown'}"
            )
        linkage = partition.get("linkage") or {}
        if linkage.get("onset_gap_seconds") is not None:
            claims.append(f"Audit partition onset gap seconds: {linkage['onset_gap_seconds']}")
        for group in linkage.get("supporting_groups", []):
            claims.append(
                f"Cross-partition evidence: {group.get('label_vi')} "
                f"on {group.get('edge_count')} displayed edges"
            )
        separation = partition.get("separation") or {}
        claims.append(
            "Audit partition edge balance: "
            f"cross={separation.get('cross_edge_count')}, "
            f"internal={separation.get('internal_edge_count')}, "
            f"complete={separation.get('edge_counts_are_complete')}"
        )

    # Tier-2 P2 facts
    p2 = context.get("tier2_p2", {})
    if p2:
        dom = p2.get("dominator") or {}
        if dom.get("witness_resource_id"):
            claims.append(f"Dominator witness resource: {dom['witness_resource_id']} covering {len(dom.get('covered_resource_ids', []))} resources")
        prop = p2.get("propagation") or {}
        for h in prop.get("hypotheses", [])[:4]:
            claims.append(f"Propagation hypothesis: {h['source']} -> {h['target']} transition prob {h['prob']} delta {h['delta_seconds']}s")
        om = p2.get("over_merge") or {}
        if om.get("structural_separation"):
            claims.append(f"Over-merge warning: strength {om.get('strength')}, separation={om.get('structural_separation')}, {om.get('narrative')}")
        attr = p2.get("evidence_attribution") or {}
        for c in attr.get("contributions", [])[:4]:
            claims.append(f"Evidence attribution {c['group_id']}: {c['attribution']}% support across {c['supported_pairs']} pairs")

    core_cnt = context.get("roles", {}).get("core_count", 0)
    weak_list = context.get("roles", {}).get("weak_members", [])
    if weak_list:
        claims.append(f"Weak members: {', '.join(weak_list[:4])}")
    else:
        claims.append("Weak members: 0 (this does not establish that all members are cohesive)")
    if core_cnt > 0:
        claims.append(f"Core members: {core_cnt} of {context['chain']['alarm_count']}")
    for ins in context.get("structural_insights", []):
        claims.append(f"Binding mechanism ({ins['type']}): {ins['detail']}")
    for finding in context.get("analytical_findings", []):
        claims.append(
            f"Finding {finding['finding_id']} [{finding['kind']}/{finding['status']}]: "
            f"{finding['claim']}"
        )
    connected_pair_count = int(context.get("topology", {}).get("connected_pair_count", 0) or 0)
    if connected_pair_count:
        pair_total = int(context.get("topology", {}).get("pair_total", 0) or 0)
        claims.append(
            f"Observed bounded structural topology paths for {connected_pair_count}/"
            f"{pair_total} eligible mapped resource pairs"
        )
    op = context.get("operational_insights", {})
    if op.get("actionable_takeaway"):
        claims.append(f"Operational recommendation: {op['actionable_takeaway']}")
    if op.get("primary_focus"):
        claims.append(f"Remediation priority: {op['primary_focus']}")

    # System instruction tailored for Senior NOC Incident Commander
    if language == "vi":
        instruction = (
            "Viết một nhận định điều tra tập trung vào insight quan trọng nhất. Ưu tiên một đoạn văn gọn, bỏ thông tin lặp lại từ các card; "
            "nếu quan hệ phức tạp, dùng đủ câu để giải thích evidence, điểm yếu và bước kiểm tra tiếp theo. "
            "Không bỏ dữ kiện thiết yếu chỉ để rút ngắn và không mở đầu bằng tỷ lệ cảnh báo. "
            "Trước hết chọn insight kỹ thuật mạnh nhất nhưng chưa hiển nhiên từ alarm_groups, diễn tiến thời gian, WHY, topology, Audit và Tier-2. "
            "Giải thích cơ sở liên hệ các alarm bằng các loại evidence độc lập khi có sẵn; đồng thời nêu evidence phản biện "
            "hoặc điểm yếu khiến chưa thể coi đó là quan hệ nhân quả. Nếu có partition, mô tả cụ thể mỗi phía và chính xác evidence nào nối qua ranh giới. "
            "Kết thúc bằng một kiểm tra vận hành cụ thể gắn với thiết bị, đường topology, phiên, cổng hoặc component đã có trong facts. "
            "Nếu evidence không đủ để tạo insight mới, hãy nói thẳng điều còn thiếu thay vì kể lại số liệu. Không nhắc Counterfactual, mức sao, hard gate "
            "hay trạng thái hiệu chuẩn. Không gọi thành viên đại diện là nguyên nhân gốc. Chỉ nói chung cluster, phụ thuộc có hướng "
            "hoặc đường lan truyền đã được xác nhận khi facts thực sự xác nhận; nếu mới hợp lý về mặt kỹ thuật thì gọi là giả thuyết "
            "và nêu bằng chứng còn thiếu. Không khẳng định hướng lan truyền từ thứ tự thời gian."
        )
    else:
        instruction = (
            "Act as a Senior NOC Incident Commander. "
            "Synthesize the provided facts, topology paths, and audit verification into a focused operational briefing. "
            "Omit repeated dashboard facts, but use enough prose to explain complex evidence and its limitations. "
            "Cover 4 key pillars: "
            "(1) Incident onset T0 and temporal progression across devices; "
            "(2) Network correlation and topology transit (cross-layer signals, dominator witness, or shared transit); "
            "(3) Audit Graph cohesion (Conductance Phi vs Epsilon, assessing whether this is a single cohesive incident or an over-merged cluster); "
            "(4) Actionable operational recommendation for remediation (target device priority or partition split). "
            "Follow ADR-0024 strictly using only provided grounding facts without unverified root-cause claims."
        )

    prompt_facts = {
        "investigation_evidence": _build_investigation_evidence(context),
        "instruction": instruction,
    }

    try:
        rendered = render_grounded(
            draft=deterministic_draft,
            facts=prompt_facts,
            fact_refs=claims,
            purpose="COHESION",
            timeout_seconds=_cohesion_ai_timeout_seconds(),
            requested_language=language,
            preserve_provider_output=True,
        )
        return CohesionNarrativeResult(
            chain_id=chain_id,
            narrative=rendered.message,
            model=rendered.model,
            provider_status=rendered.provider_status,
            context=context,
        )
    except Exception as exc:
        logger.warning("LLM investigation synthesis failed: %s", exc)
        return CohesionNarrativeResult(
            chain_id=chain_id,
            narrative="",
            model="",
            provider_status="UNAVAILABLE",
            context=context,
        )
