"""Evidence-bound narrative for a chain analysis.

ADR-0024 allows a language model to render structured evidence, but the
operator-facing response itself must never acquire facts that the analysis did
not produce. The deterministic projection remains authoritative and is also
the exact fallback whenever the optional renderer is unavailable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import re
from typing import Any

from .grounded_llm import render_grounded


def _clean_location(loc: Any) -> str | None:
    if not loc or not isinstance(loc, str):
        return None
    s = loc.strip()
    for prefix in ("SITE: ", "SITE:", "LOCATION: ", "LOCATION:", "LOC: ", "LOC:"):
        if s.upper().startswith(prefix):
            s = s[len(prefix):].strip()
    return s or None


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    cleaned = ts.strip().replace("Z", "").replace("+00:00", "")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _operational_facts(
    chain_id: str,
    analysis: Any,
    package: Any | None = None,
) -> dict[str, Any]:
    members = getattr(analysis, "members", {})
    member_ids = {str(k) for k in members.keys()} if isinstance(members, dict) else set()
    raw_alarms = getattr(package, "alarms", None) if package else None
    if isinstance(raw_alarms, dict):
        chain_alarms = [raw_alarms[k] for k in member_ids if k in raw_alarms]
    elif isinstance(raw_alarms, (list, tuple)) and member_ids:
        chain_alarms = [a for a in raw_alarms if str(getattr(a, "alarm_id", "")) in member_ids]
    else:
        chain_alarms = []

    if not chain_alarms:
        return {
            "has_package_data": False,
            "device_names": [],
            "locations": [],
            "alarm_types": {},
            "severities": {},
            "services": [],
            "earliest_time": None,
            "latest_time": None,
            "duration_seconds": None,
            "delayed_alarms": [],
            "core_devices": [],
            "isolated_devices": [],
            "burst_time": None,
            "burst_count": 0,
            "core_services": [],
            "isolated_services": [],
            "why_related": None,
            "why_unrelated": None,
            "operational_conclusion": None,
        }

    device_counter: dict[str, int] = {}
    location_set: set[str] = set()
    alarm_types: dict[str, int] = {}
    severities: dict[str, int] = {}
    service_set: set[str] = set()

    service_pattern = re.compile(
        r"\b([a-zA-Z0-9_\-]+(?:server|agent|api|compute|volume|scheduler|conductor|placement|dashboard|etcd|ovs|ovn|keystone|glance|cinder|neutron|nova|heat|swift|rabbitmq|mariadb|mysql|exporter|vswitchd))\b",
        re.IGNORECASE,
    )

    timestamps: list[tuple[datetime, Any]] = []

    for a in chain_alarms:
        dev = getattr(a, "device_code", None) or getattr(a, "node_reference", None)
        if dev:
            dev_str = str(dev).strip()
            device_counter[dev_str] = device_counter.get(dev_str, 0) + 1

        raw_dict = getattr(a, "raw", None)
        if isinstance(raw_dict, dict):
            loc = (
                raw_dict.get("location_code")
                or raw_dict.get("site")
                or raw_dict.get("location")
            )
            cleaned_loc = _clean_location(loc)
            if cleaned_loc:
                location_set.add(cleaned_loc)

            content = (
                raw_dict.get("content")
                or raw_dict.get("cah.alarm_text")
                or raw_dict.get("alarm_text")
                or ""
            )
            if content:
                for match in service_pattern.findall(str(content)):
                    service_set.add(match)

        name = getattr(a, "alarm_name", None)
        if name:
            name_str = str(name).strip()
            alarm_types[name_str] = alarm_types.get(name_str, 0) + 1
            for match in service_pattern.findall(name_str):
                service_set.add(match)

        sev = getattr(a, "severity_name", None)
        if sev:
            sev_str = str(sev).strip()
            severities[sev_str] = severities.get(sev_str, 0) + 1

        ts_str = getattr(a, "canonical_start_time", None) or getattr(
            a, "raw_start_time", None
        )
        if isinstance(raw_dict, dict) and not ts_str:
            ts_str = raw_dict.get("cah.start_time")
        dt = _parse_ts(ts_str)
        if dt is not None:
            timestamps.append((dt, a))

    earliest_time_str: str | None = None
    latest_time_str: str | None = None
    duration_seconds: int | None = None
    delayed_alarms: list[dict[str, Any]] = []

    timestamps.sort(key=lambda item: item[0])
    earliest_dt = timestamps[0][0] if timestamps else None
    latest_dt = timestamps[-1][0] if timestamps else None
    if earliest_dt and latest_dt:
        earliest_time_str = earliest_dt.strftime("%Y-%m-%d %H:%M:%S")
        latest_time_str = latest_dt.strftime("%Y-%m-%d %H:%M:%S")
        duration_seconds = int((latest_dt - earliest_dt).total_seconds())

    # Detect primary burst cluster and isolated devices
    time_counter: dict[str, int] = {}
    for dt, _ in timestamps:
        t_key = dt.strftime("%H:%M:%S")
        time_counter[t_key] = time_counter.get(t_key, 0) + 1

    burst_time: str | None = None
    burst_count = 0
    if time_counter:
        sorted_times = sorted(time_counter.items(), key=lambda x: -x[1])
        burst_time, burst_count = sorted_times[0]

    core_devices = [dev for dev, count in device_counter.items() if count >= 2]
    isolated_devices = [dev for dev, count in device_counter.items() if count == 1]
    if not core_devices:
        core_devices = list(device_counter.keys())

    core_services: set[str] = set()
    isolated_services: set[str] = set()

    for dt, a in timestamps:
        diff_s = int((dt - earliest_dt).total_seconds()) if earliest_dt else 0
        raw_dict = getattr(a, "raw", None) or {}
        content_str = str(raw_dict.get("content") or raw_dict.get("cah.alarm_text") or a.alarm_name or "")
        svcs = service_pattern.findall(content_str)
        dev = str(getattr(a, "device_code", "") or getattr(a, "node_reference", "") or "")
        is_delayed = diff_s >= 60
        is_isolated = dev in isolated_devices

        if is_delayed or is_isolated:
            for s in svcs:
                isolated_services.add(s)
            if is_delayed:
                delayed_alarms.append(
                    {
                        "alarm_id": str(getattr(a, "alarm_id", "")),
                        "device": dev,
                        "alarm_name": str(getattr(a, "alarm_name", "") or ""),
                        "delay_seconds": diff_s,
                        "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "service": svcs[0] if svcs else "",
                    }
                )
        else:
            for s in svcs:
                core_services.add(s)

    total_alarms = len(chain_alarms)
    why_related: str | None = None
    why_unrelated: str | None = None
    operational_conclusion: str | None = None

    if burst_count >= 2 and earliest_time_str:
        dev_sample = ", ".join(core_devices[:4])
        svc_sample = f" ({', '.join(sorted(core_services)[:3])})" if core_services else ""
        why_related = (
            f"Phần lớn cảnh báo ({burst_count}/{total_alarms}) bùng phát đồng thời tại mốc {burst_time or earliest_time_str} "
            f"trên cụm thiết bị hạ tầng ({dev_sample}), cùng chịu sự cố gián đoạn dịch vụ{svc_sample}."
        )

    if delayed_alarms:
        da = delayed_alarms[0]
        svc_desc = f" ({da['service']})" if da.get("service") else ""
        why_unrelated = (
            f"Cảnh báo {da['alarm_id']} nổ trễ {da['delay_seconds']} giây (lúc {da['time']}) "
            f"trên thiết bị riêng biệt {da['device']}{svc_desc}, không chia sẻ nhịp bùng phát đồng thời "
            f"hay bản chất sự cố với cụm cảnh báo chính."
        )
        operational_conclusion = (
            f"Đề xuất loại bỏ cảnh báo {da['alarm_id']} là chính xác để chuẩn hóa chuỗi và loại trừ nhiễu thời gian. "
            f"Kỹ sư NOC nên tập trung xử lý cụm thiết bị chính ({', '.join(core_devices[:3])}) tại thời điểm khởi phát {burst_time or earliest_time_str}."
        )

    return {
        "has_package_data": True,
        "device_names": sorted(device_counter.keys()),
        "locations": sorted(location_set),
        "alarm_types": dict(sorted(alarm_types.items(), key=lambda x: -x[1])),
        "severities": dict(sorted(severities.items(), key=lambda x: -x[1])),
        "services": sorted(service_set),
        "earliest_time": earliest_time_str,
        "latest_time": latest_time_str,
        "duration_seconds": duration_seconds,
        "delayed_alarms": delayed_alarms,
        "core_devices": core_devices,
        "isolated_devices": isolated_devices,
        "burst_time": burst_time,
        "burst_count": burst_count,
        "core_services": sorted(core_services),
        "isolated_services": sorted(isolated_services),
        "why_related": why_related,
        "why_unrelated": why_unrelated,
        "operational_conclusion": operational_conclusion,
    }


def _weak_member_details(
    weak_members: list[str],
    analysis: Any,
    package: Any | None = None,
) -> list[dict[str, Any]]:
    if not weak_members:
        return []
    members = getattr(analysis, "members", {})
    raw_alarms = getattr(package, "alarms", None) if package else None
    if isinstance(raw_alarms, dict):
        alarm_map = {str(k): v for k, v in raw_alarms.items()}
    elif isinstance(raw_alarms, (list, tuple)):
        alarm_map = {str(getattr(a, "alarm_id", "")): a for a in raw_alarms}
    else:
        alarm_map = {}

    details: list[dict[str, Any]] = []
    for wm_id in weak_members:
        member_obj = members.get(wm_id) if isinstance(members, dict) else None
        role_obj = getattr(member_obj, "role", None)
        support = getattr(role_obj, "support", None)
        alarm = alarm_map.get(str(wm_id))
        dev = (
            str(getattr(alarm, "device_code", "") or getattr(alarm, "node_reference", "") or "")
            if alarm
            else ""
        )
        name = str(getattr(alarm, "alarm_name", "") or "") if alarm else ""
        sev = str(getattr(alarm, "severity_name", "") or "") if alarm else ""
        raw_dict = getattr(alarm, "raw", None)
        content = ""
        if isinstance(raw_dict, dict):
            content = str(
                raw_dict.get("content")
                or raw_dict.get("cah.alarm_text")
                or raw_dict.get("alarm_text")
                or ""
            ).strip()

        details.append(
            {
                "alarm_id": str(wm_id),
                "device": dev,
                "alarm_name": name,
                "severity": sev,
                "support": support,
                "content": content,
            }
        )
    return details


@dataclass(frozen=True)
class AISuggestionResult:
    chain_id: str
    status: str
    model: str
    narrative: str
    grounded_claims: list[str]
    disclaimer: str
    provider_status: str | None = None
    review_status: str = "NOT_AVAILABLE"
    review_reason: str | None = None
    recommendation_status: str = "UNAVAILABLE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _value(value: Any) -> str:
    """Return an enum/value object's stable public representation."""
    return str(getattr(value, "value", value))


def _member_facts(analysis: Any) -> list[dict[str, Any]]:
    members = getattr(analysis, "members", {})
    if not isinstance(members, dict):
        return []

    result: list[dict[str, Any]] = []
    for alarm_id, member in sorted(members.items(), key=lambda item: str(item[0])):
        role = getattr(member, "role", None)
        verdict = _value(getattr(role, "verdict", "INSUFFICIENT_DATA"))
        support = getattr(role, "support", None)
        result.append(
            {
                "alarm_id": str(alarm_id),
                "role": verdict,
                "membership_support": support,
                "representativeness": getattr(member, "representativeness", None),
            }
        )
    return result


def _descriptor_facts(analysis: Any) -> list[str]:
    descriptors = getattr(analysis, "descriptors", None)
    if descriptors is None:
        return []
    if hasattr(descriptors, "identity") and hasattr(descriptors, "contrastive"):
        raw = [*descriptors.identity, *descriptors.contrastive]
    elif isinstance(descriptors, (list, tuple)):
        raw = list(descriptors)
    else:
        return []

    labels: list[str] = []
    for descriptor in raw[:3]:
        label = getattr(descriptor, "label", None)
        coverage = getattr(descriptor, "coverage", None)
        if not label:
            continue
        if isinstance(coverage, (int, float)):
            labels.append(f"{label} (coverage {coverage:.0%})")
        else:
            labels.append(str(label))
    return labels


def _recommendation_facts(review_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(review_result, dict):
        return []
    evaluated = {
        str(candidate.get("candidate_id")): candidate
        for candidate in review_result.get("evaluated_candidates", [])
        if isinstance(candidate, dict) and candidate.get("candidate_id")
    }
    facts: list[dict[str, Any]] = []
    for reference in review_result.get("recommendations", []):
        if not isinstance(reference, dict):
            continue
        candidate_id = reference.get("candidate_id")
        candidate = evaluated.get(str(candidate_id))
        operation = candidate.get("operation") if candidate else reference.get("operation")
        if not (candidate_id and operation):
            continue

        fact: dict[str, Any] = {
            "candidate_id": str(candidate_id),
            "operation": str(operation),
        }
        comp = candidate.get("comparative_explanation") if isinstance(candidate, dict) else None
        if isinstance(comp, dict):
            if comp.get("summary_action"):
                fact["summary_action"] = str(comp["summary_action"])
            if comp.get("why_better"):
                fact["why_better"] = str(comp["why_better"])
            if isinstance(comp.get("delta_highlights"), list) and comp["delta_highlights"]:
                fact["delta_highlights"] = comp["delta_highlights"]
            if isinstance(comp.get("comparison_points"), list) and comp["comparison_points"]:
                fact["comparison_points"] = comp["comparison_points"]
            if comp.get("ai_narrative"):
                fact["ai_narrative"] = str(comp["ai_narrative"])
            if isinstance(comp.get("context_facts"), dict):
                fact["context_facts"] = comp["context_facts"]
                for k, v in comp["context_facts"].items():
                    fact[k] = v
        facts.append(fact)
    return facts


def _evaluated_improvement_facts(review_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(review_result, dict):
        return []
    recommendation_ids = {
        str(r.get("candidate_id"))
        for r in review_result.get("recommendations", [])
        if isinstance(r, dict) and r.get("candidate_id")
    }
    improvements: list[dict[str, Any]] = []
    for candidate in review_result.get("evaluated_candidates", []):
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id or candidate_id in recommendation_ids:
            continue
        eval_status = str(candidate.get("evaluation_status") or candidate.get("status") or "")
        if eval_status in ("HARD_GATE_REJECTED", "EXTERNALLY_CONTRADICTED"):
            continue
        comp = candidate.get("comparative_explanation")
        if not isinstance(comp, dict):
            continue
        summary_act = str(comp.get("summary_action") or "").strip()
        why_b = str(comp.get("why_better") or "").strip()
        if not summary_act or "0 cảnh báo" in summary_act or "0 alarm" in summary_act:
            continue
        fact: dict[str, Any] = {
            "candidate_id": candidate_id,
            "operation": str(candidate.get("operation") or ""),
            "summary_action": summary_act,
            "why_better": why_b,
            "delta_highlights": comp.get("delta_highlights") or [],
            "comparison_points": comp.get("comparison_points") or [],
        }
        if isinstance(comp.get("context_facts"), dict):
            fact["context_facts"] = comp["context_facts"]
            for k, v in comp["context_facts"].items():
                fact[k] = v
        improvements.append(fact)
    return improvements


def extract_grounded_claims(
    chain_id: str,
    analysis: Any,
    review_result: dict[str, Any] | None = None,
    package: Any | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Project only facts directly produced by Tier-1B, Review v1, and IngestedPackage."""
    members = _member_facts(analysis)
    descriptors = _descriptor_facts(analysis)
    proposals = _recommendation_facts(review_result)
    evaluated_improvements = _evaluated_improvement_facts(review_result)
    review_reason = review_result.get("reason") if isinstance(review_result, dict) else None
    recommendation_status = review_result.get("recommendation_status") if isinstance(review_result, dict) else None

    role_counts: dict[str, int] = {}
    for member in members:
        role_counts[member["role"]] = role_counts.get(member["role"], 0) + 1
    weak_members = [member["alarm_id"] for member in members if member["role"] == "WEAK"]
    insufficient_members = [
        member["alarm_id"] for member in members
        if member["role"] == "INSUFFICIENT_DATA"
    ]

    claims = [f"Chain {chain_id} contains {len(members)} analyzed members."]
    if weak_members:
        claims.append(
            f"{len(weak_members)} member(s) are classified WEAK: "
            f"{', '.join(weak_members[:3])}."
        )
    else:
        claims.append("No analyzed member is classified WEAK.")
    if insufficient_members:
        claims.append(
            f"{len(insufficient_members)} member(s) have INSUFFICIENT_DATA: "
            f"{', '.join(insufficient_members[:3])}."
        )
    if descriptors:
        claims.append(f"Top descriptors: {', '.join(descriptors)}.")
    for proposal in proposals:
        claims.append(
            "Operator-facing counterfactual recommendation: "
            f"{proposal['operation']} ({proposal['candidate_id']})."
        )
        if proposal.get("summary_action"):
            claims.append(f"Proposal action: {proposal['summary_action']}.")
        if proposal.get("why_better"):
            claims.append(f"Proposal rationale: {proposal['why_better']}.")
        for delta in proposal.get("delta_highlights", []):
            if isinstance(delta, dict) and delta.get("label") and delta.get("delta"):
                claims.append(
                    f"Proposal metric {delta['label']}: {delta.get('before', '')} -> {delta.get('after', '')} ({delta['delta']})."
                )
        c_facts = proposal.get("context_facts")
        if isinstance(c_facts, dict):
            if c_facts.get("target_locs"):
                claims.append(f"Proposal target locations: {', '.join(c_facts['target_locs'])}.")
            if c_facts.get("target_dev_names"):
                claims.append(f"Proposal target devices: {', '.join(c_facts['target_dev_names'])}.")
            if c_facts.get("time_delta_seconds") is not None:
                claims.append(f"Proposal time delta: {c_facts['time_delta_seconds']}s.")
            if c_facts.get("shared_locs"):
                claims.append(f"Proposal shared locations: {', '.join(c_facts['shared_locs'])}.")
            if c_facts.get("shared_devs"):
                claims.append(f"Proposal shared devices: {', '.join(c_facts['shared_devs'])}.")
            if c_facts.get("merge_time_delta_seconds") is not None:
                claims.append(f"Proposal merge time delta: {c_facts['merge_time_delta_seconds']}s.")

    op_facts = _operational_facts(chain_id, analysis, package=package)
    weak_details = _weak_member_details(weak_members, analysis, package=package)

    if op_facts.get("has_package_data"):
        devs = op_facts.get("device_names", [])
        if devs:
            claims.append(f"Chain involves {len(devs)} device(s): {', '.join(devs[:5])}.")
        locs = op_facts.get("locations", [])
        if locs:
            claims.append(f"Incident location(s): {', '.join(locs[:3])}.")
        atypes = op_facts.get("alarm_types", {})
        if atypes:
            atypes_str = ", ".join(f"{k} ({v})" for k, v in list(atypes.items())[:3])
            claims.append(f"Main alarm types: {atypes_str}.")
        svcs = op_facts.get("services", [])
        if svcs:
            claims.append(f"Affected services: {', '.join(svcs[:5])}.")
        if op_facts.get("earliest_time") and op_facts.get("latest_time"):
            dur = op_facts.get("duration_seconds")
            dur_str = f" (duration {dur}s)" if dur is not None else ""
            claims.append(f"Event span: {op_facts['earliest_time']} to {op_facts['latest_time']}{dur_str}.")
        for da in op_facts.get("delayed_alarms", [])[:3]:
            claims.append(
                f"Delayed alarm {da['alarm_id']} on {da['device']} triggered {da['delay_seconds']}s after initial wave."
            )
        for wd in weak_details:
            dev_str = f" on {wd['device']}" if wd.get("device") else ""
            supp_str = f" with support {wd['support']:.2f}" if wd.get("support") is not None else ""
            claims.append(f"Weak member detail: {wd['alarm_id']}{dev_str}{supp_str}.")
        if op_facts.get("why_related"):
            claims.append(f"Correlation insight: {op_facts['why_related']}.")
        if op_facts.get("why_unrelated"):
            claims.append(f"Separation insight: {op_facts['why_unrelated']}.")
        if op_facts.get("operational_conclusion"):
            claims.append(f"Operational conclusion: {op_facts['operational_conclusion']}.")

    structured = {
        "chain_id": chain_id,
        "member_count": len(members),
        "role_counts": role_counts,
        "weak_members": weak_members,
        "insufficient_members": insufficient_members,
        "descriptors": descriptors,
        "proposals": proposals,
        "evaluated_improvements": evaluated_improvements,
        "review_reason": review_reason,
        "recommendation_status": recommendation_status,
        "operational_facts": op_facts,
        "weak_member_details": weak_details,
    }
    return structured, claims


def build_deterministic_narrative(
    chain_id: str,
    structured_data: dict[str, Any],
    review_status: str = "NOT_AVAILABLE",
    review_reason: str | None = None,
    language: str = "en",
) -> str:
    """Render the grounded projection without causal or topology claims."""
    op = structured_data.get("operational_facts", {})
    has_op = isinstance(op, dict) and op.get("has_package_data", False)

    if language == "vi":
        lines = [
            f"### Tóm tắt bằng chứng cho chuỗi {chain_id}",
        ]
        devs = op.get("device_names", []) if has_op else []
        locs = op.get("locations", []) if has_op else []
        scope_line = f"- **Quy mô phân tích**: **{structured_data['member_count']}** cảnh báo"
        if devs:
            scope_line += f" trên **{len(devs)}** thiết bị ({', '.join(devs[:4])}{'...' if len(devs) > 4 else ''})"
        if locs:
            scope_line += f" tại khu vực: **{', '.join(locs[:2])}**"
        scope_line += "."
        lines.append(scope_line)

        if has_op and op.get("earliest_time") and op.get("latest_time"):
            dur = op.get("duration_seconds")
            dur_str = f" (tổng thời lượng: **{dur} giây**)" if dur is not None else ""
            lines.append(f"- **Khung thời gian sự cố**: từ `{op['earliest_time']}` đến `{op['latest_time']}`{dur_str}.")

        if has_op:
            atypes = op.get("alarm_types", {})
            if atypes:
                types_str = ", ".join(f"{k} ({v})" for k, v in list(atypes.items())[:3])
                lines.append(f"- **Loại cảnh báo chính**: {types_str}.")
            svcs = op.get("services", [])
            if svcs:
                lines.append(f"- **Dịch vụ/thành phần bị ảnh hưởng**: {', '.join(svcs[:4])}.")

        # Insights: Vì sao liên quan & Vì sao không liên quan
        if has_op:
            if op.get("why_related"):
                lines.append(f"- **Bản chất tương quan (Vì sao liên quan)**: {op['why_related']}")
            if op.get("why_unrelated"):
                lines.append(f"- **Dấu hiệu phân tách (Vì sao không liên quan)**: {op['why_unrelated']}")
            if op.get("operational_conclusion"):
                lines.append(f"- **Khuyến nghị & Kết luận vận hành**: {op['operational_conclusion']}")

        delayed = op.get("delayed_alarms", []) if has_op else []
        if delayed:
            da_samples = [f"cảnh báo `{d['alarm_id']}` trên `{d['device']}` (nổ trễ {d['delay_seconds']}s)" for d in delayed[:2]]
            lines.append(f"- **Đợt bùng phát trễ**: Ghi nhận {len(delayed)} cảnh báo xuất hiện cách biệt đáng kể so với cụm ban đầu: {'; '.join(da_samples)}.")

        weak_members = structured_data["weak_members"]
        weak_details = structured_data.get("weak_member_details", [])
        insufficient_members = structured_data["insufficient_members"]
        descriptors = structured_data["descriptors"]
        proposals = structured_data["proposals"]

        if weak_details:
            wd_strs = []
            for wd in weak_details[:3]:
                txt = f"`{wd['alarm_id']}`"
                if wd.get("device"):
                    txt += f" ({wd['device']})"
                if wd.get("support") is not None:
                    txt += f" [support: {wd['support']:.2f}]"
                wd_strs.append(txt)
            lines.append(f"- Cảnh báo có độ gắn kết **YẾU (WEAK)**: {', '.join(wd_strs)}.")
        elif weak_members:
            lines.append(f"- Cảnh báo có độ gắn kết **YẾU (WEAK)**: {', '.join(weak_members[:3])}.")
        else:
            lines.append("- Không có thành viên nào được phân loại WEAK; dữ kiện này không tự chứng minh toàn chuỗi gắn kết tốt.")

        if insufficient_members:
            lines.append(
                "- Dữ liệu chưa đầy đủ cho các cảnh báo: "
                f"{', '.join(insufficient_members[:3])}."
            )
        if descriptors:
            lines.append(f"- Thuộc tính đặc trưng: {', '.join(descriptors)}.")

        lines.append("\n### Kết quả Counterfactual Review")
        effective_reason = review_reason or structured_data.get("review_reason")
        rec_status = structured_data.get("recommendation_status")
        if review_status == "NOT_AVAILABLE":
            lines.append(
                "- Counterfactual Review chưa được thực hiện hoặc chưa có artifact khả dụng."
            )
        elif review_status == "UNAVAILABLE":
            lines.append(
                "- Chưa tải được kết quả Counterfactual Review; điều này không có nghĩa là không có đề xuất."
            )
        elif rec_status == "UNAVAILABLE":
            reason_text = effective_reason or "COUNTERFACTUAL_RESULT_UNAVAILABLE"
            if reason_text == "COUNTERFACTUAL_POLICY_NOT_CALIBRATED":
                lines.append(
                    "- **Chế độ an toàn mặc định**: chính sách Counterfactual chưa được hiệu chuẩn; "
                    "các candidate đã đánh giá không phải recommendation vận hành."
                )
                evaluated = structured_data.get("evaluated_improvements", [])
                if evaluated:
                    candidate = evaluated[0]
                    if candidate.get("summary_action"):
                        lines.append(f"  - *Candidate đã đánh giá*: {candidate['summary_action']}")
                    if candidate.get("why_better"):
                        lines.append(f"  - *Rationale metric*: {candidate['why_better']}")
                    deltas = [
                        f"{item.get('label')}: {item.get('delta')}"
                        for item in candidate.get("delta_highlights", [])
                        if isinstance(item, dict) and item.get("label") and item.get("delta")
                    ]
                    if deltas:
                        lines.append(f"  - *Metric delta quan sát*: {'; '.join(deltas)}.")
            else:
                lines.append(f"- Counterfactual Review chưa khả dụng ({reason_text}); không có kết luận âm được suy ra.")
        elif rec_status == "NO_CLEAR_ALTERNATIVE":
            lines.append(
                "- Không tìm thấy phương án vượt trội rõ ràng trong không gian tìm kiếm hữu hạn đã đánh giá."
            )
        elif rec_status == "AVAILABLE" and proposals:
            for proposal in proposals:
                action = proposal.get("summary_action")
                if action:
                    lines.append(
                        f"- **Đề xuất ({proposal['operation']} - {proposal['candidate_id']})**: {action}"
                    )
                else:
                    lines.append(
                        f"- Phương án {proposal['operation']} ({proposal['candidate_id']}) "
                        "được đề xuất để người vận hành xem xét."
                    )
                if proposal.get("why_better"):
                    lines.append(f"  - *Vì sao đề xuất này tốt hơn*: {proposal['why_better']}")
                deltas = proposal.get("delta_highlights", [])
                if deltas:
                    delta_strs = [
                        f"{d.get('label', d.get('metric_name'))}: {d.get('before', '')} → {d.get('after', '')} ({d.get('delta', '')})"
                        for d in deltas
                        if isinstance(d, dict)
                        and d.get("label")
                        and str(d.get("delta", "")).strip() not in ("0", "+0%", "-0%", "0.0", "+0.0%", "")
                    ]
                    if delta_strs:
                        lines.append(f"  - *Chỉ số cải thiện*: {'; '.join(delta_strs)}.")
                for pt in proposal.get("comparison_points", [])[:2]:
                    lines.append(f"  - *Chi tiết*: {pt}")
        elif rec_status == "AVAILABLE":
            lines.append(
                "- Kết quả Counterfactual không nhất quán: trạng thái AVAILABLE nhưng không có recommendation; "
                "không thể kết luận tối ưu."
            )
        else:
            lines.append("- Trạng thái recommendation chưa được cung cấp; chưa thể diễn giải kết quả Counterfactual.")

        lines.append(
            "\n> Bản tóm tắt này được sinh xác định từ các dữ kiện đã phân tích. "
            "Hệ thống không suy diễn nguyên nhân gốc, hướng nhân quả hay thay đổi nhóm của NocPro khi chưa có kiểm chứng."
        )
        return "\n".join(lines)

    lines = [
        f"### Evidence summary for chain {chain_id}",
    ]
    devs = op.get("device_names", []) if has_op else []
    locs = op.get("locations", []) if has_op else []
    scope_line = f"- **Analyzed scope**: **{structured_data['member_count']}** alarms"
    if devs:
        scope_line += f" across **{len(devs)}** device(s) ({', '.join(devs[:4])}{'...' if len(devs) > 4 else ''})"
    if locs:
        scope_line += f" at location(s): **{', '.join(locs[:2])}**"
    scope_line += "."
    lines.append(scope_line)

    if has_op and op.get("earliest_time") and op.get("latest_time"):
        dur = op.get("duration_seconds")
        dur_str = f" (duration: **{dur}s**)" if dur is not None else ""
        lines.append(f"- **Event timeframe**: `{op['earliest_time']}` to `{op['latest_time']}`{dur_str}.")

    if has_op:
        atypes = op.get("alarm_types", {})
        if atypes:
            types_str = ", ".join(f"{k} ({v})" for k, v in list(atypes.items())[:3])
            lines.append(f"- **Main alarm types**: {types_str}.")
        svcs = op.get("services", [])
        if svcs:
            lines.append(f"- **Affected services**: {', '.join(svcs[:4])}.")
        if op.get("why_related"):
            lines.append(f"- **Correlation analysis (Why related)**: {op['why_related']}")
        if op.get("why_unrelated"):
            lines.append(f"- **Separation analysis (Why unrelated)**: {op['why_unrelated']}")
        if op.get("operational_conclusion"):
            lines.append(f"- **Operational recommendation**: {op['operational_conclusion']}")

    delayed = op.get("delayed_alarms", []) if has_op else []
    if delayed:
        da_samples = [f"alarm `{d['alarm_id']}` on `{d['device']}` (delayed {d['delay_seconds']}s)" for d in delayed[:2]]
        lines.append(f"- **Delayed outbreak**: {len(delayed)} alarm(s) triggered significantly later than initial wave: {'; '.join(da_samples)}.")

    weak_members = structured_data["weak_members"]
    weak_details = structured_data.get("weak_member_details", [])
    insufficient_members = structured_data["insufficient_members"]
    descriptors = structured_data["descriptors"]
    proposals = structured_data["proposals"]
    effective_reason = review_reason or structured_data.get("review_reason")
    rec_status = structured_data.get("recommendation_status")

    if weak_details:
        wd_strs = []
        for wd in weak_details[:3]:
            txt = f"`{wd['alarm_id']}`"
            if wd.get("device"):
                txt += f" ({wd['device']})"
            if wd.get("support") is not None:
                txt += f" [support: {wd['support']:.2f}]"
            wd_strs.append(txt)
        lines.append(f"- Members classified **WEAK**: {', '.join(wd_strs)}.")
    elif weak_members:
        lines.append(f"- Members classified **WEAK**: {', '.join(weak_members[:3])}.")
    else:
        lines.append("- No analyzed member is classified **WEAK**.")

    if insufficient_members:
        lines.append(
            "- Evidence is incomplete for: "
            f"{', '.join(insufficient_members[:3])}."
        )
    if descriptors:
        lines.append(f"- Descriptor facts: {', '.join(descriptors)}.")

    lines.append("\n### Counterfactual review")
    if review_status == "NOT_AVAILABLE":
        lines.append("- Counterfactual Review has not been run or no artifact is available.")
    elif review_status == "UNAVAILABLE":
        lines.append(
            "- Counterfactual Review could not be read; this is not equivalent "
            "to having no recommendation."
        )
    elif rec_status == "UNAVAILABLE":
        reason_text = effective_reason or "COUNTERFACTUAL_RESULT_UNAVAILABLE"
        if reason_text == "COUNTERFACTUAL_POLICY_NOT_CALIBRATED":
            lines.append(
                "- **Default safety mode**: counterfactual policy is not calibrated; "
                "evaluated candidates are not operational recommendations."
            )
            evaluated = structured_data.get("evaluated_improvements", [])
            if evaluated:
                candidate = evaluated[0]
                if candidate.get("summary_action"):
                    lines.append(f"  - *Evaluated candidate*: {candidate['summary_action']}")
                if candidate.get("why_better"):
                    lines.append(f"  - *Metric rationale*: {candidate['why_better']}")
                deltas = [
                    f"{item.get('label')}: {item.get('delta')}"
                    for item in candidate.get("delta_highlights", [])
                    if isinstance(item, dict) and item.get("label") and item.get("delta")
                ]
                if deltas:
                    lines.append(f"  - *Observed metric deltas*: {'; '.join(deltas)}.")
        else:
            lines.append(
                f"- Counterfactual Review is unavailable ({reason_text}); no negative finding is inferred."
            )
    elif rec_status == "NO_CLEAR_ALTERNATIVE":
        lines.append(
            "- No clear superior alternative was found within the finite evaluated search space."
        )
    elif rec_status == "AVAILABLE" and proposals:
        for proposal in proposals:
            lines.append(
                f"- {proposal['operation']} ({proposal['candidate_id']}) "
                "is an operator-facing bounded recommendation."
            )
            if proposal.get("summary_action"):
                lines.append(f"  - Action: {proposal['summary_action']}")
            if proposal.get("why_better"):
                lines.append(f"  - Rationale: {proposal['why_better']}")
            deltas = proposal.get("delta_highlights", [])
            if deltas:
                delta_strs = [
                    f"{d.get('label', d.get('metric_name'))}: {d.get('before', '')} -> {d.get('after', '')} ({d.get('delta', '')})"
                    for d in deltas
                    if isinstance(d, dict)
                    and d.get("label")
                    and str(d.get("delta", "")).strip() not in ("0", "+0%", "-0%", "0.0", "+0.0%", "")
                ]
                if delta_strs:
                    lines.append(f"  - Metric deltas: {'; '.join(delta_strs)}")
    elif rec_status == "AVAILABLE":
        lines.append(
            "- Counterfactual contract inconsistency: AVAILABLE has no recommendation items; optimality cannot be inferred."
        )
    else:
        lines.append("- Recommendation status is missing; the Counterfactual result cannot be interpreted.")

    lines.append(
        "\n> This is a deterministic rendering of persisted analysis facts. "
        "It does not infer root cause, causal direction, topology dependency, "
        "or change NocPro grouping."
    )
    return "\n".join(lines)


def generate_ai_suggestion(
    chain_id: str,
    analysis: Any,
    review_result: dict[str, Any] | None = None,
    review_status: str = "NOT_AVAILABLE",
    review_reason: str | None = None,
    package: Any | None = None,
    language: str = "en",
) -> AISuggestionResult:
    """Render the evidence projection without granting the model authority."""
    structured, claims = extract_grounded_claims(
        chain_id, analysis, review_result, package=package
    )
    deterministic = build_deterministic_narrative(
        chain_id, structured, review_status, review_reason, language=language
    )
    fact_refs = list(claims)
    if language == "vi":
        fact_refs.extend([
            f"Chuỗi: {chain_id}",
            f"Số cảnh báo: {structured['member_count']}",
        ])
        if structured["weak_members"]:
            fact_refs.append(f"Cảnh báo yếu: {', '.join(structured['weak_members'][:3])}")
        op = structured.get("operational_facts", {})
        if isinstance(op, dict):
            if op.get("duration_seconds") is not None:
                fact_refs.append(f"{op['duration_seconds']} giây")
                fact_refs.append(f"{op['duration_seconds']}s")
            for loc in op.get("locations", []):
                fact_refs.append(f"khu vực {loc}")
            if op.get("delayed_alarms"):
                fact_refs.append("bùng phát trễ")
                fact_refs.append("nổ trễ")

    rendered = render_grounded(
        draft=deterministic,
        facts={
            "structured_analysis": structured,
            "review_status": review_status,
            "review_reason": review_reason,
        },
        fact_refs=fact_refs,
        purpose="ADVISOR",
    )
    disclaimer = (
        "ADR-0024: phản hồi này có thể sử dụng AI để diễn giải bằng chứng xác định; "
        "AI không tạo ra bằng chứng mới, không suy diễn nguyên nhân gốc hay thay đổi NocPro."
        if language == "vi"
        else "ADR-0024: this response may use AI to render deterministic evidence; "
        "it does not create evidence, infer causality, or change NocPro."
    )
    return AISuggestionResult(
        chain_id=chain_id,
        status="AVAILABLE",
        model=rendered.model,
        narrative=rendered.message,
        grounded_claims=claims,
        disclaimer=disclaimer,
        provider_status=rendered.provider_status,
        review_status=review_status,
        review_reason=review_reason,
        recommendation_status=str(structured.get("recommendation_status") or "UNAVAILABLE"),
    )
