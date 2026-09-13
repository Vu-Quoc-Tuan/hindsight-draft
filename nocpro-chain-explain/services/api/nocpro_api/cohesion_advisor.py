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
from collections import Counter
from dataclasses import asdict, dataclass
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


def extract_cohesion_context(
    service: Any,
    chain_id: str,
    analysis: Any | None = None,
    audit_artifact: Any | None = None,
    review_result: dict[str, Any] | None = None,
    audit_error_reason: str | None = None,
) -> dict[str, Any]:
    """Extract structured facts across the 5 authoritative data sources."""
    package = service.require_package()
    if analysis is None:
        analysis = service.analyze(chain_id)

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
        cohesion_factors.append(f"phân bố trên cụm {len(distinct_devs)} thiết bị liên đới ({', '.join(distinct_devs[:3])})")

    if top_alarm_types:
        prim_name, prim_cnt = top_alarm_types[0]
        prim_pct = round((prim_cnt / max(1, alarm_count)) * 100, 1)
        if prim_pct == 100.0:
            cohesion_factors.append(f"100% cảnh báo cùng chia sẻ loại lỗi '{prim_name}'")
        else:
            cohesion_factors.append(f"{prim_pct}% cảnh báo là loại lỗi '{prim_name}'")

    # -------------------------------------------------------------------------
    # 2. Chain WHY / Descriptors
    # -------------------------------------------------------------------------
    strong_views: list[str] = []
    partial_views: list[str] = []

    # Check temporal burst: only valid when duration_seconds is known and <= 481s
    if duration_seconds is not None:
        if duration_seconds <= 481 and alarm_count > 1:
            strong_views.append("TEMPORAL_BURST")
        elif alarm_count > 1:
            partial_views.append("T_DELAY")

    # Check device concentration
    if dev_counts:
        top_dev_share = dominant_count / max(1, alarm_count)
        if top_dev_share >= 0.6:
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
    member_ids = set(package.members_of(chain_id))
    mapped_count = 0
    resource_types: set[str] = set()

    topo = getattr(package, "topology", {})
    raw_mappings = topo.get("mappings") if isinstance(topo, dict) else getattr(topo, "mappings", ())

    for raw_mapping in raw_mappings or ():
        if isinstance(raw_mapping, dict):
            alarm_id = raw_mapping.get("alarm_id")
            res_type = raw_mapping.get("resource_type") or raw_mapping.get("type")
        else:
            alarm_id = getattr(raw_mapping, "alarm_id", None)
            res_type = getattr(raw_mapping, "topology_layer", None) or getattr(raw_mapping, "resource_id", None)
        if alarm_id in member_ids:
            mapped_count += 1
            if res_type:
                resource_types.add(str(res_type))

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

    if audit_error_reason:
        audit_status = "UNAVAILABLE"
        audit_reason = audit_error_reason
    elif audit_artifact is not None:
        artifact_status = getattr(audit_artifact, "status", "")
        raw_verdict = getattr(audit_artifact, "verdict", None)
        audit_verdict = getattr(raw_verdict, "value", str(raw_verdict)) if raw_verdict is not None else None
        audit_reason = getattr(audit_artifact, "reason", None)
        best_cut_index = getattr(audit_artifact, "best_cut_index", None)
        scored_cuts = getattr(audit_artifact, "scored_cuts", ())

        # Artifact status for valid computed review audit artifacts is "AVAILABLE"
        if artifact_status in ("AVAILABLE", "SUCCEEDED", "COMPLETE", "VALID"):
            if audit_verdict == AuditVerdict.CANDIDATE_SPLIT.value:
                audit_status = "EVALUATED"
                candidate_cut = True
                if scored_cuts and best_cut_index is not None and 0 <= best_cut_index < len(scored_cuts):
                    best_cut = scored_cuts[best_cut_index]
                    conductance = getattr(best_cut, "conductance", getattr(best_cut, "phi", None))
                elif scored_cuts:
                    conductance = getattr(scored_cuts[0], "conductance", getattr(scored_cuts[0], "phi", None))
            elif audit_verdict == AuditVerdict.NO_LOW_CONDUCTANCE_CUT.value:
                audit_status = "EVALUATED"
                candidate_cut = False
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
            if isinstance(rec, dict) and rec.get("operation") == "SPLIT_CHAIN":
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
            "devices": sorted(list(set(devices)))[:4],
            "dominant_device": dominant_device,
            "dominant_count": dominant_count,
            "dominant_pct": dominant_pct,
            "top_severity": top_severity,
            "severity_counts": dict(sev_counts),
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
        "why": {
            "strong_views": strong_views,
            "partial_views": partial_views,
            "top_descriptors": top_descriptors,
        },
        "topology": {
            "mapped": mapped_count,
            "total": alarm_count,
            "resource_types": sorted(list(resource_types))[:4],
            "dependency_verified": False,
        },
        "audit": {
            "status": audit_status,
            "verdict": audit_verdict,
            "reason": audit_reason,
            "candidate_cut": candidate_cut,
            "conductance": round(conductance, 3) if conductance is not None else None,
        },
        "recommendations": {
            "split_recommended": split_recommended,
        },
    }


def build_deterministic_cohesion_narrative(context: dict[str, Any], language: str = "en") -> str:
    """Compose a fluent, natural domain-expert narrative from structured facts."""
    chain = context.get("chain", {})
    alarm_summary = context.get("alarm_summary", {})
    topology = context.get("topology", {})
    audit = context.get("audit", {})
    recs = context.get("recommendations", {})
    roles = context.get("roles", {})

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
    weak_members = roles.get("weak_members", [])

    if language == "vi":
        # 1. Singleton narrative in Vietnamese
        if is_singleton:
            return (
                "Chuỗi này chỉ chứa 1 cảnh báo được ghi nhận. "
                "Phân tích độ gắn kết và lan truyền đa thành viên không áp dụng."
            )

        # 2. Multi-alarm composition sentence in Vietnamese with time & scope
        net_str = f"thuộc lớp mạng {', '.join(network_classes)} " if network_classes else ""
        top_sev = alarm_summary.get("top_severity")
        sev_str = f"mức {top_sev} " if top_sev else ""
        time_desc = chain.get("duration_desc")
        start_t = chain.get("start_time")
        end_t = chain.get("end_time")
        time_clause = ""
        if time_desc:
            if start_t and end_t and start_t != end_t:
                time_clause = f"diễn ra trong {time_desc} (từ {start_t} đến {end_t})"
            else:
                time_clause = f"diễn ra trong {time_desc}"

        time_seg = f", {time_clause}" if time_clause else ""
        sentence_1 = f"Chuỗi {chain_id} gồm {alarm_count} cảnh báo {sev_str}{net_str}{time_seg}."

        # Rationale: Explain WHY the alarms belong together
        cohesion_factors = context.get("cohesion_factors", [])
        rationale_sentence = ""
        if cohesion_factors:
            rationale_sentence = f" Chuỗi có độ gắn kết cao nhờ: {'; '.join(cohesion_factors)}."
        elif top_alarms:
            primary_name = top_alarms[0][0]
            primary_count = top_alarms[0][1]
            secondary_name = top_alarms[1][0] if len(top_alarms) > 1 else None

            if primary_count == alarm_count:
                comp = f"bao gồm toàn bộ {alarm_count} sự kiện '{primary_name}'"
            elif secondary_name:
                comp = (
                    f"chủ yếu gồm {primary_count} sự kiện '{primary_name}' "
                    f"kèm theo '{secondary_name}'"
                )
            else:
                comp = f"chủ yếu gồm {primary_count} sự kiện '{primary_name}'"
            dev_clause = f" trên {len(devices)} thiết bị ({', '.join(devices[:2])})" if devices else ""
            rationale_sentence = f" Chuỗi {comp}{dev_clause}."

        # Role observation
        role_sentence = ""
        if weak_members:
            role_sentence = f" Phát hiện {len(weak_members)} cảnh báo có liên kết yếu (WEAK): {', '.join(weak_members[:3])}."
        elif alarm_count > 1:
            core_cnt = roles.get("core_count", 0)
            if core_cnt > 0:
                role_sentence = f" Toàn bộ {core_cnt}/{alarm_count} cảnh báo nòng cốt đều đạt độ gắn kết tốt, không phát hiện phần tử lạc quẻ (WEAK)."
            else:
                role_sentence = " Các cảnh báo thành viên có độ gắn kết tốt, không phát hiện phần tử lạc quẻ (WEAK)."

        # 3. Structural audit & recommendation sentence in Vietnamese
        if split_recommended:
            sentence_2 = (
                "Kiểm định cấu trúc phát hiện ranh giới phân tách rõ rệt, "
                "và phương án tách chuỗi (SPLIT) đã được đề xuất để xem xét."
            )
        elif candidate_cut or audit_verdict == AuditVerdict.CANDIDATE_SPLIT.value:
            cond_str = f" (độ dẫn conductance {conductance:.2f})" if conductance is not None else ""
            sentence_2 = (
                f"Kiểm định cấu trúc phát hiện ranh giới phân tách có độ dẫn thấp giữa các nhóm thành viên{cond_str}, "
                "cảnh báo nguy cơ gộp nhầm."
            )
        elif audit_status == "EVALUATED" and audit_verdict == AuditVerdict.NO_LOW_CONDUCTANCE_CUT.value:
            sentence_2 = "Kiểm định cấu trúc xác nhận các phân vùng thành viên có độ gắn kết cao, không có vết cắt độ dẫn thấp."
        elif audit_status == "NOT_APPLICABLE" or audit_verdict == AuditVerdict.SKIPPED_SMALL_CHAIN.value:
            sentence_2 = "Ràng buộc kiểm định cấu trúc không áp dụng cho cấu trúc chuỗi quy mô nhỏ này."
        elif audit_status == "UNAVAILABLE" or audit_verdict == AuditVerdict.UNAVAILABLE.value:
            reason_clause = f" ({audit_reason})" if audit_reason else ""
            sentence_2 = f"Kiểm định cấu trúc hiện chưa khả dụng cho chuỗi này{reason_clause}."
        else:
            # NOT_EVALUATED
            sentence_2 = "Chưa thực hiện kiểm định cấu trúc Tier-2 cho chuỗi này."

        return f"{sentence_1}{rationale_sentence}{role_sentence} {sentence_2}".strip()

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


def generate_cohesion_narrative(
    service: Any,
    chain_id: str,
    audit_artifact: Any | None = None,
    review_result: dict[str, Any] | None = None,
    audit_error_reason: str | None = None,
    language: str = "en",
) -> CohesionNarrativeResult:
    """Generate a grounded narrative, optionally polished by an LLM."""
    package = service.require_package()
    analysis = service.analyze(chain_id)

    # Extract 5 sources context
    context = extract_cohesion_context(
        service=service,
        chain_id=chain_id,
        analysis=analysis,
        audit_artifact=audit_artifact,
        review_result=review_result,
        audit_error_reason=audit_error_reason,
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
    claims.append(f"Candidate cut detected: {context['audit']['candidate_cut']}")
    if context["audit"]["conductance"] is not None:
        claims.append(f"Conductance: {context['audit']['conductance']}")
    claims.append(f"Split recommended: {context['recommendations']['split_recommended']}")
    core_cnt = context.get("roles", {}).get("core_count", 0)
    claims.append(f"Core members: {core_cnt} of {context['chain']['alarm_count']}")
    weak_list = context.get("roles", {}).get("weak_members", [])
    if weak_list:
        claims.append(f"Weak members: {', '.join(weak_list[:4])}")

    # System instruction tailored for natural, non-stiff tone
    if language == "vi":
        instruction = (
            "Viết 2-3 câu diễn giải vận hành mạch lạc, tự nhiên, chuyên nghiệp bằng tiếng Việt "
            "giải thích RÕ RÀNG TẠI SAO các cảnh báo này gom vào cùng một chuỗi: nêu quy mô số lượng, "
            "thời gian diễn ra và độ đồng bộ (bao nhiêu giây/phút, từ mấy giờ đến mấy giờ), mức độ tập trung thiết bị (cùng thiết bị hay cụm máy chủ nào), "
            "dạng lỗi nghiệp vụ, và xác nhận độ gắn kết của các thành viên (toàn bộ CORE hay có WEAK). "
            "Tuân thủ nghiêm ngặt ADR-0024: CHỈ sử dụng các dữ kiện được cung cấp. Tuyệt đối "
            "không bịa đặt đứt cáp quang thụ động, DWDM, hay nguyên nhân gốc chưa xác minh."
        )
    else:
        instruction = (
            "Write 1-2 fluent, concise, natural sentences summarizing the alarm composition, "
            "domain context, and boundary audit for this alarm chain. Follow ADR-0024: use ONLY "
            "the provided structured facts. Never fabricate unverified DWDM, passive fiber breaks, "
            "or root cause. The tone must be natural and professional, not stiff database listings."
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
