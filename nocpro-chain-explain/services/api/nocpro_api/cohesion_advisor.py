"""Cohesion narrative generator grounded on 5 authoritative data sources (ADR-0024).

Produces a natural, expert-toned operational narrative summarizing:
1. Raw alarm composition (alarm types, devices, network classes).
2. Chain WHY / descriptors (strong dimensions, dominant descriptors).
3. Topology mapping (mapped resources, verified resource types).
4. Structural audit findings (conductance, candidate cuts, partition status).
5. Counterfactual recommendations (split alternatives).
"""

from __future__ import annotations

import logging
import re
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import combinations
from typing import Any

from audit import AuditVerdict
from .grounded_llm import render_grounded

logger = logging.getLogger(__name__)


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


def _shortest_undirected_path(
    adjacency: dict[str, set[str]],
    source: str,
    target: str,
    *,
    max_hops: int,
) -> list[str] | None:
    if source == target:
        return [source]
    queue: deque[list[str]] = deque([[source]])
    seen = {source}
    while queue:
        path = queue.popleft()
        if len(path) - 1 >= max_hops:
            continue
        for neighbour in sorted(adjacency.get(path[-1], ())):
            if neighbour == target:
                return [*path, neighbour]
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append([*path, neighbour])
    return None


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
    for mapping in raw_mappings or ():
        alarm_id = str(_record_value(mapping, "alarm_id", ""))
        resource_id = _record_value(mapping, "resource_id")
        if alarm_id not in member_ids or not resource_id:
            continue
        resource_id = str(resource_id)
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
    for source, target in combinations(resources, 2):
        best_path: list[str] | None = None
        best_relation: str | None = None
        for relation, adjacency in adjacency_by_relation.items():
            candidate = _shortest_undirected_path(
                adjacency, source, target, max_hops=max_hops
            )
            if candidate is not None and (
                best_path is None or len(candidate) < len(best_path)
            ):
                best_path = candidate
                best_relation = relation
        if best_path is None:
            continue
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
    return {
        "mapped_alarm_ids": mapped_alarm_ids,
        "resource_by_alarm": resource_by_alarm,
        "resource_types": sorted(resource_types),
        "mapped_resources": resources,
        "paths": paths,
        "pair_total": pair_total,
        "connected_pair_count": len(paths),
        "max_path_hops": max((path["hop_count"] for path in paths), default=None),
        "shared_transit_resources": [
            {"resource_id": resource_id, "path_count": count}
            for resource_id, count in transit_counter.most_common(5)
        ],
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
        for path in paths[:2]:
            source_label = ", ".join(path.get("source_devices") or [path["source"]])
            target_label = ", ".join(path.get("target_devices") or [path["target"]])
            evidence.append(
                f"{source_label} ↔ {target_label}: {' → '.join(path['path'])} "
                f"({path['hop_count']} hop, {path['relation_type']})."
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
                f"{len(topology_connectivity.get('mapped_resources', []))} resource đã ánh xạ "
                f"nằm trong cùng vùng kết nối transit; đường dài nhất quan sát được là "
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
) -> dict[str, Any]:
    """Extract structured facts across the authoritative data sources."""
    package = service.require_package()
    if analysis is None:
        analysis = service.analyze(chain_id)

    # Attempt to resolve deep dive analysis if not passed directly
    if deep_dive_analysis is None and hasattr(service, "jobs"):
        try:
            job = service.jobs.latest_succeeded(
                package.snapshot.snapshot_id,
                package.snapshot.snapshot_version,
                chain_id,
            )
            if job is not None and job.result is not None:
                deep_dive_analysis = job.result
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
    connected_pairs = topology_connectivity["paths"]

    structural_insights: list[dict[str, str]] = []
    if connected_pairs:
        pair_count = topology_connectivity["connected_pair_count"]
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
    split_recommended = False
    if isinstance(review_result, dict):
        for rec in review_result.get("recommendations", []):
            if isinstance(rec, dict) and rec.get("operation") in ("SPLIT_CHAIN", "REMOVE_MEMBER", "MOVE_MEMBER"):
                split_recommended = True
                break

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
                else "Đang ở giai đoạn phân tích sơ bộ; khuyến nghị theo dõi thiết bị khởi phát và chờ kết quả kiểm định chuyên sâu P2."
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
            "resource_types": sorted(list(resource_types))[:4],
            "connected_pairs": connected_pairs,
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
        },
        "recommendations": {
            "split_recommended": split_recommended,
        },
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
    recs = context.get("recommendations", {})

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
    split_recommended = recs.get("split_recommended", False)

    if language == "vi":
        if is_singleton:
            return (
                "Chuỗi này chỉ chứa 1 cảnh báo được ghi nhận. "
                "Phân tích độ gắn kết và lan truyền đa thành viên không áp dụng."
            )
        findings = context.get("analytical_findings", [])
        findings_by_id = {
            str(item.get("finding_id")): item
            for item in findings
            if item.get("status") == "AVAILABLE" and item.get("claim")
        }
        temporal_claim = findings_by_id.get("TEMPORAL_PROGRESSION", {}).get("claim")
        topology_claim = findings_by_id.get("SHARED_TOPOLOGY_CONTEXT", {}).get("claim")
        audit_claim = findings_by_id.get("AUDIT_COHESION", {}).get("claim")
        dom_claim = findings_by_id.get("TOPOLOGY_DOMINATOR_WITNESS", {}).get("claim")
        prop_claim = findings_by_id.get("TOPOLOGY_PROPAGATION_FLOW", {}).get("claim")
        om_claim = findings_by_id.get("OVER_MERGE_EVALUATION", {}).get("claim")

        if temporal_claim or topology_claim or audit_claim:
            sentences: list[str] = []
            # Câu 1: Bối cảnh sự cố & dòng thời gian
            first = f"Chuỗi {chain_id} gồm {alarm_count} cảnh báo"
            if chain.get("duration_desc"):
                first += f" trong {chain['duration_desc']}"
            if temporal_claim:
                first += f"; {str(temporal_claim).rstrip('.').lower()}"
            sentences.append(first + ".")

            # Câu 2: Quan hệ topo & Dominator witness / Luồng lan truyền
            topo_parts: list[str] = []
            if topology_claim:
                topo_parts.append(str(topology_claim).rstrip("."))
            if dom_claim:
                topo_parts.append(str(dom_claim).rstrip("."))
            elif prop_claim:
                topo_parts.append(str(prop_claim).rstrip("."))
            if topo_parts:
                sentences.append("; ".join(topo_parts) + ".")

            # Câu 3: Đánh giá gắn kết Audit & Over-merge
            conclusion_parts: list[str] = []
            if audit_claim:
                conclusion_parts.append(str(audit_claim).rstrip("."))
            if om_claim:
                conclusion_parts.append(str(om_claim).rstrip("."))
            if "PROPAGATION_COMPATIBLE_PATTERN" in findings_by_id and not dom_claim:
                conclusion_parts.append(
                    "Mẫu hình phù hợp với lan truyền, nhưng chưa xác nhận thiết bị khởi phát là nguyên nhân gốc"
                )
            if conclusion_parts:
                sentences.append(" ".join(conclusion_parts) + ".")

            # Câu 4: Khuyến nghị hành động NOC
            action = context.get("operational_insights", {}).get("actionable_takeaway")
            if action:
                sentences.append(action)

            return " ".join(sentences[:4])
        else:
            fallback_facts: list[str] = []
            if top_alarms:
                fallback_facts.append(
                    f"Ghi nhận {top_alarms[0][1]} sự kiện '{top_alarms[0][0]}'."
                )
            if devices:
                fallback_facts.append(f"Phạm vi quan sát gồm {len(devices)} thiết bị.")
            weak_count = int(context.get("roles", {}).get("weak_count", 0) or 0)
            if weak_count:
                fallback_facts.append(f"Tier-1B phân loại {weak_count} thành viên WEAK.")
            if split_recommended:
                fallback_facts.append(
                    "Một phương án tách chuỗi (SPLIT) được ghi nhận để người vận hành xem xét."
                )
            observed = " ".join(fallback_facts) or f"Chuỗi {chain_id} gồm {alarm_count} cảnh báo được ghi nhận."
            return f"Chuỗi {chain_id} gồm {alarm_count} cảnh báo. {observed}".strip()

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
    if split_recommended:
        sentence_2 = (
            "A structural partition boundary was identified, and a split alternative "
            "has been recommended for review."
        )
    elif candidate_cut or audit_verdict == AuditVerdict.CANDIDATE_SPLIT.value:
        cond_str = f" (conductance {conductance:.2f})" if conductance is not None else ""
        sentence_2 = (
            f"Structural audit detected a low-conductance separation boundary between member groups{cond_str}, "
            "though no split alternative is currently recommended."
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


def _briefing_is_concise(message: str, *, language: str) -> bool:
    if not message.strip():
        return False
    if language != "vi":
        return True
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", message.strip()) if part]
    return len(sentences) <= 5 and len(message) <= 1800 and "Các 7 " not in message


def generate_cohesion_narrative(
    service: Any,
    chain_id: str,
    audit_artifact: Any | None = None,
    review_result: dict[str, Any] | None = None,
    audit_error_reason: str | None = None,
    deep_dive_analysis: Any | None = None,
    language: str = "en",
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
        deep_dive_analysis=deep_dive_analysis,
    )

    deterministic_draft = build_deterministic_cohesion_narrative(context, language=language)

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
    if context["topology"]["resource_types"]:
        claims.append(f"Topology resources: {', '.join(context['topology']['resource_types'])}")
    claims.append(f"Mapped alarms: {context['topology']['mapped']} of {context['topology']['total']}")
    for pair in context.get("topology", {}).get("connected_pairs", []):
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
    claims.append(f"Split recommended: {context['recommendations']['split_recommended']}")

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
    if context.get("topology", {}).get("connected_pairs"):
        claims.append(
            f"Observed bounded structural topology paths across "
            f"{len(context['topology']['connected_pairs'])} resource pairs"
        )
    op = context.get("operational_insights", {})
    if op.get("actionable_takeaway"):
        claims.append(f"Operational recommendation: {op['actionable_takeaway']}")
    if op.get("primary_focus"):
        claims.append(f"Remediation priority: {op['primary_focus']}")

    # System instruction tailored for Senior NOC Incident Commander
    if language == "vi":
        instruction = (
            "Đóng vai trò Chỉ huy Sự cố NOC cấp cao (Senior NOC Incident Commander). "
            "Tổng hợp các sự kiện, cấu trúc topo và kiểm định audit đã cung cấp thành một bản tin nhận định vận hành súc tích từ 3 đến 4 câu mạch lạc. "
            "Bản tin phải làm rõ 4 điểm then chốt: "
            "(1) Diễn tiến sự cố & thiết bị khởi phát T0 cùng dòng thời gian lan truyền; "
            "(2) Tương quan mạng và kết nối topo (liên tầng vật lý/giao thức, dominator witness, hoặc đường transit); "
            "(3) Độ gắn kết Audit Graph (Conductance Phi so với Epsilon, nhận định sự cố đơn lẻ hay có dấu hiệu gộp thừa over-merge); "
            "(4) Khuyến nghị hành động kỹ thuật cụ thể cho kỹ sư trực ca (thiết bị ưu tiên xử lý, hoặc đề xuất tách chuỗi nếu có ranh giới cắt). "
            "Không đọc lại danh sách số liệu thô; diễn đạt tự nhiên, chuyên sâu về vận hành viễn thông/mạng. "
            "Tuyệt đối tuân thủ ADR-0024: chỉ sử dụng các tên thiết bị, số liệu và sự kiện có trong grounding data; không suy diễn nguyên nhân gốc khi chưa kiểm định."
        )
    else:
        instruction = (
            "Act as a Senior NOC Incident Commander. "
            "Synthesize the provided facts, topology paths, and audit verification into a concise 3-4 sentence operational briefing. "
            "Cover 4 key pillars: "
            "(1) Incident onset T0 and temporal progression across devices; "
            "(2) Network correlation and topology transit (cross-layer signals, dominator witness, or shared transit); "
            "(3) Audit Graph cohesion (Conductance Phi vs Epsilon, assessing whether this is a single cohesive incident or an over-merged cluster); "
            "(4) Actionable operational recommendation for remediation (target device priority or partition split). "
            "Follow ADR-0024 strictly using only provided grounding facts without unverified root-cause claims."
        )

    prompt_facts = {
        "context": context,
        "instruction": instruction,
    }

    try:
        rendered = render_grounded(
            draft=deterministic_draft,
            facts=prompt_facts,
            fact_refs=claims,
            purpose="ADVISOR",
        )
        if not _briefing_is_concise(rendered.message, language=language):
            return CohesionNarrativeResult(
                chain_id=chain_id,
                narrative=deterministic_draft,
                model="DETERMINISTIC_EVIDENCE",
                provider_status="OUTPUT_REJECTED",
                context=context,
            )
        return CohesionNarrativeResult(
            chain_id=chain_id,
            narrative=rendered.message,
            model=rendered.model,
            provider_status=rendered.provider_status,
            context=context,
        )
    except Exception as exc:
        logger.warning("LLM render failed, falling back to deterministic narrative: %s", exc)
        return CohesionNarrativeResult(
            chain_id=chain_id,
            narrative=deterministic_draft,
            model="DETERMINISTIC_EVIDENCE",
            provider_status="UNAVAILABLE",
            context=context,
        )

