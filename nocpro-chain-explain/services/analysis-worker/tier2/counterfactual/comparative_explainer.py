"""Comparative Explainer Engine for Counterfactual Candidates (Phase 2).

Generates grounded, deterministic Before vs After comparative metrics and
domain-specific rationale for why each candidate mutation improves chain explainability,
with optional ADR-0024 grounded LLM narrative polish.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


from libs.contracts import IngestedPackage

logger = logging.getLogger(__name__)


def _clean_location(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, list) and val:
        return str(val[-1]).strip()
    s = str(val).strip()
    if s.startswith("[") and s.endswith("]"):
        parts = [p.strip(" '\"") for p in s[1:-1].split(",") if p.strip(" '\"")]
        if parts:
            return parts[-1]
    if s in ("", "[]", "None", "null"):
        return None
    return s


def _parse_alarm_timestamp(alm: Any) -> float | None:
    if not alm:
        return None
    ts_str = getattr(alm, "canonical_start_time", None) or getattr(alm, "raw_start_time", None)
    if not ts_str and isinstance(getattr(alm, "raw", None), dict):
        ts_str = (
            alm.raw.get("canonical_start_time")
            or alm.raw.get("start_time")
            or alm.raw.get("alarm_time")
            or alm.raw.get("occur_time")
        )
    if not ts_str:
        return None
    try:
        clean = str(ts_str).replace("Z", "+00:00")
        return datetime.fromisoformat(clean).timestamp()
    except Exception:
        return None


@dataclass(frozen=True)
class DeltaHighlight:
    metric_name: str
    label: str
    before: str
    after: str
    delta: str
    direction: str  # "better" | "worse" | "neutral"


@dataclass(frozen=True)
class ComparativeExplanation:
    operation: str
    summary_action: str
    why_better: str
    comparison_points: list[str]
    delta_highlights: list[dict[str, Any]]
    ai_narrative: str | None = None
    language: str = "vi"
    context_facts: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "operation": self.operation,
            "summary_action": self.summary_action,
            "why_better": self.why_better,
            "comparison_points": list(self.comparison_points),
            "delta_highlights": list(self.delta_highlights),
            "ai_narrative": self.ai_narrative,
            "language": self.language,
        }
        if self.context_facts is not None:
            data["context_facts"] = dict(self.context_facts)
        return data


def _format_val(val: float | int | None, is_pct: bool = False) -> str:
    if val is None:
        return "UNAVAILABLE"
    if is_pct:
        return f"{float(val) * 100:.1f}%"
    if isinstance(val, int) or float(val).is_integer():
        return str(int(val))
    return f"{float(val):.3f}"


def _extract_metric(metric_obj: Any) -> float | None:
    if metric_obj is None:
        return None
    if isinstance(metric_obj, dict):
        if metric_obj.get("availability") in {"AVAILABLE", "SUPPORT"}:
            val = metric_obj.get("value")
            return float(val) if val is not None else None
        return None
    avail = getattr(metric_obj, "availability", None)
    avail_str = getattr(avail, "value", str(avail))
    if avail_str in {"AVAILABLE", "SUPPORT", "MetricAvailability.AVAILABLE"}:
        val = getattr(metric_obj, "value", None)
        return float(val) if val is not None else None
    return None


def build_deterministic_comparative_explanation(
    *,
    operation: str,
    candidate_id: str,
    partition_delta: Any,
    before_metrics: Any,
    after_metrics: Any,
    metric_deltas: Mapping[str, float] | None = None,
    package: IngestedPackage | None = None,
    member_ids: tuple[str, ...] | list[str] = (),
    source_chain_id: str | None = None,
    target_chain_id: str | None = None,
    merged_chain_ids: tuple[str, str] | list[str] | None = None,
    operation_evidence: dict[str, Any] | None = None,
    semantic_effects: Sequence[str] | None = None,
    structural_facts: Mapping[str, Any] | None = None,
    language: str = "vi",
) -> ComparativeExplanation:
    """Build exact, deterministic comparative rationale for a counterfactual candidate."""
    is_vi = language.lower().startswith("vi")
    op_ev = dict(operation_evidence or {})

    # Extract numeric before & after
    def b_val(name: str) -> float | None:
        if before_metrics is None:
            return None
        item = before_metrics.get(name) if isinstance(before_metrics, dict) else getattr(before_metrics, name, None)
        return _extract_metric(item)

    def a_val(name: str) -> float | None:
        if after_metrics is None:
            return None
        item = after_metrics.get(name) if isinstance(after_metrics, dict) else getattr(after_metrics, name, None)
        return _extract_metric(item)

    # 1. Delta Highlights
    highlights: list[DeltaHighlight] = []

    # Weak member count
    w_b, w_a = b_val("weak_member_count"), a_val("weak_member_count")
    if w_b is not None and w_a is not None:
        diff = int(w_a - w_b)
        lbl = "Cảnh báo lạc quẻ (WEAK)" if is_vi else "Weak members"
        sign = f"+{diff}" if diff > 0 else str(diff)
        direction = "better" if diff < 0 else ("worse" if diff > 0 else "neutral")
        highlights.append(DeltaHighlight("weak_member_count", lbl, str(int(w_b)), str(int(w_a)), sign, direction))

    # Min support
    s_b, s_a = b_val("minimum_membership_support"), a_val("minimum_membership_support")
    if s_b is not None and s_a is not None:
        diff_pct = (s_a - s_b) * 100
        lbl = "Độ hỗ trợ tối thiểu (Min Support)" if is_vi else "Min membership support"
        sign = f"+{diff_pct:.1f}%" if diff_pct > 0 else f"{diff_pct:.1f}%"
        direction = "better" if diff_pct > 0 else ("worse" if diff_pct < 0 else "neutral")
        highlights.append(DeltaHighlight("minimum_membership_support", lbl, _format_val(s_b, True), _format_val(s_a, True), sign, direction))

    # Conductance
    c_b, c_a = b_val("audit_conductance"), a_val("audit_conductance")
    if c_b is not None and c_a is not None:
        diff_c = c_a - c_b
        lbl = "Độ cô lập vết cắt (Conductance Phi)" if is_vi else "Cut conductance Phi"
        sign = f"+{diff_c:.3f}" if diff_c > 0 else f"{diff_c:.3f}"
        direction = "better" if diff_c > 0 else ("worse" if diff_c < 0 else "neutral")
        highlights.append(DeltaHighlight("audit_conductance", lbl, _format_val(c_b), _format_val(c_a), sign, direction))

    # Component count
    cp_b, cp_a = b_val("component_count"), a_val("component_count")
    if cp_b is not None and cp_a is not None:
        diff_cp = int(cp_a - cp_b)
        lbl = "Số cụm rời rạc (Components)" if is_vi else "Connected components"
        sign = f"+{diff_cp}" if diff_cp > 0 else str(diff_cp)
        direction = "better" if diff_cp < 0 else ("worse" if diff_cp > 0 else "neutral")
        highlights.append(DeltaHighlight("component_count", lbl, str(int(cp_b)), str(int(cp_a)), sign, direction))

    # Coverage
    cov_b, cov_a = b_val("evidence_union_coverage"), a_val("evidence_union_coverage")
    if cov_b is not None and cov_a is not None:
        diff_cov = (cov_a - cov_b) * 100
        lbl = "Bao phủ bằng chứng (Evidence Coverage)" if is_vi else "Evidence coverage"
        sign = f"+{diff_cov:.1f}%" if diff_cov > 0 else f"{diff_cov:.1f}%"
        direction = "better" if diff_cov > 0 else ("worse" if diff_cov < 0 else "neutral")
        highlights.append(DeltaHighlight("evidence_union_coverage", lbl, _format_val(cov_b, True), _format_val(cov_a, True), sign, direction))

    # Resolve member_ids if not explicitly passed
    if not member_ids:
        if op_ev.get("alarm_id"):
            member_ids = (str(op_ev["alarm_id"]),)
        elif partition_delta:
            b_list = partition_delta.get("before") if isinstance(partition_delta, dict) else getattr(partition_delta, "before", None)
            a_list = partition_delta.get("after") if isinstance(partition_delta, dict) else getattr(partition_delta, "after", None)
            if b_list and a_list:
                b_m = set(b_list[0][1]) if len(b_list) > 0 and len(b_list[0]) > 1 else set()
                a_m = set(a_list[0][1]) if len(a_list) > 0 and len(a_list[0]) > 1 else set()
                diff = b_m - a_m
                if diff:
                    member_ids = tuple(sorted(diff))

    # Gather info on affected alarms from package
    affected_details: list[str] = []
    source_timestamps: list[float] = []
    source_locs: list[str] = []
    source_dev_names: list[str] = []
    if package and member_ids:
        for m_id in list(member_ids)[:3]:
            alm = package.alarms.get(m_id)
            if alm:
                alm_name = alm.alarm_name or "Unknown Alarm"
                dev = alm.device_code or "Unknown Device"
                if dev and dev != "Unknown Device" and dev not in source_dev_names:
                    source_dev_names.append(dev)
                extra: list[str] = []
                if isinstance(alm.raw, dict):
                    raw_loc = alm.raw.get("location_code")
                    clean_l = _clean_location(raw_loc)
                    if clean_l:
                        extra.append(f"trạm {clean_l}")
                        if clean_l not in source_locs:
                            source_locs.append(clean_l)
                    raw_port = alm.raw.get("port") or alm.raw.get("component")
                    if raw_port and str(raw_port).strip() not in ("", "[]", "None", "null") and str(raw_port).strip() != str(dev).strip():
                        extra.append(f"cổng {raw_port}")
                    raw_link = alm.raw.get("link_name")
                    if raw_link and str(raw_link).strip() not in ("", "[]", "None", "null"):
                        extra.append(f"link {raw_link}")
                extra_str = f" - {', '.join(extra)}" if extra else ""
                affected_details.append(
                    f"{m_id} ({alm_name} trên {dev}{extra_str})"
                    if is_vi
                    else f"{m_id} ({alm_name} on {dev}{extra_str})"
                )
                ts = _parse_alarm_timestamp(alm)
                if ts is not None:
                    source_timestamps.append(ts)
            else:
                affected_details.append(m_id)

    # Gather target chain device, location, and temporal context if available
    target_dev_names: list[str] = []
    target_alms: list[str] = []
    target_locs: list[str] = []
    target_timestamps: list[float] = []
    if package and target_chain_id and target_chain_id in package.chains:
        for tm_id in package.members_of(target_chain_id):
            talm = package.alarms.get(tm_id)
            if talm:
                if talm.device_code and talm.device_code not in target_dev_names:
                    target_dev_names.append(talm.device_code)
                if talm.alarm_name and talm.alarm_name not in target_alms:
                    target_alms.append(talm.alarm_name)
                if isinstance(talm.raw, dict):
                    clean_tl = _clean_location(talm.raw.get("location_code"))
                    if clean_tl and clean_tl not in target_locs:
                        target_locs.append(clean_tl)
                tts = _parse_alarm_timestamp(talm)
                if tts is not None:
                    target_timestamps.append(tts)

    time_delta_seconds: int | None = None
    if source_timestamps and target_timestamps:
        time_delta_seconds = int(round(min(abs(st - tt) for st in source_timestamps for tt in target_timestamps)))

    shared_locs: list[str] = []
    shared_devs: list[str] = []
    merge_time_delta_seconds: int | None = None
    if operation == "MERGE_CHAINS" and package and merged_chain_ids and len(merged_chain_ids) >= 2:
        c1_id, c2_id = merged_chain_ids[0], merged_chain_ids[1]
        if c1_id in package.chains and c2_id in package.chains:
            c1_locs, c1_devs, c1_ts = set(), set(), []
            for mid in package.members_of(c1_id):
                a = package.alarms.get(mid)
                if a:
                    if a.device_code:
                        c1_devs.add(a.device_code)
                    if isinstance(a.raw, dict):
                        cl = _clean_location(a.raw.get("location_code"))
                        if cl:
                            c1_locs.add(cl)
                    ts = _parse_alarm_timestamp(a)
                    if ts is not None:
                        c1_ts.append(ts)
            c2_locs, c2_devs, c2_ts = set(), set(), []
            for mid in package.members_of(c2_id):
                a = package.alarms.get(mid)
                if a:
                    if a.device_code:
                        c2_devs.add(a.device_code)
                    if isinstance(a.raw, dict):
                        cl = _clean_location(a.raw.get("location_code"))
                        if cl:
                            c2_locs.add(cl)
                    ts = _parse_alarm_timestamp(a)
                    if ts is not None:
                        c2_ts.append(ts)
            shared_locs = sorted(c1_locs & c2_locs)
            shared_devs = sorted(c1_devs & c2_devs)
            if c1_ts and c2_ts:
                merge_time_delta_seconds = int(round(min(abs(t1 - t2) for t1 in c1_ts for t2 in c2_ts)))

    context_facts: dict[str, Any] = {}
    if target_locs:
        context_facts["target_locs"] = target_locs
    if target_dev_names:
        context_facts["target_dev_names"] = target_dev_names
    if time_delta_seconds is not None:
        context_facts["time_delta_seconds"] = time_delta_seconds
    if shared_locs:
        context_facts["shared_locs"] = shared_locs
    if shared_devs:
        context_facts["shared_devs"] = shared_devs
    if merge_time_delta_seconds is not None:
        context_facts["merge_time_delta_seconds"] = merge_time_delta_seconds
    if structural_facts:
        context_facts["structural_facts"] = structural_facts

    points: list[str] = []
    action_summary = ""
    why_better = ""
    m_str = ", ".join(affected_details) if affected_details else ", ".join(member_ids)
    improved = [h for h in highlights if h.direction == "better"]

    if operation == "REMOVE_MEMBER":
        count = len(member_ids)
        if count:
            action_summary = (
                f"Đề xuất loại bỏ {count} cảnh báo ({m_str}) ra khỏi chuỗi {source_chain_id or ''}".strip()
                if is_vi
                else f"Proposal to remove {count} alarm(s) ({m_str}) from chain {source_chain_id or ''}".strip()
            )
        if w_b is not None and w_a is not None and w_a < w_b:
            points.append(
                f"Giảm số thành viên WEAK từ {int(w_b)} xuống {int(w_a)}."
                if is_vi else
                f"Reduced weak member count from {int(w_b)} to {int(w_a)}."
            )
        if s_b is not None and s_a is not None and s_a > s_b:
            points.append(
                f"Độ hỗ trợ thành viên tối thiểu tăng từ {s_b*100:.1f}% lên {s_a*100:.1f}%."
                if is_vi else
                f"Minimum membership support increased from {s_b*100:.1f}% to {s_a*100:.1f}%."
            )
        if not points:
            points.append(
                "Không có chiều metric khả dụng để diễn giải cải thiện."
                if is_vi else
                "No metric dimension is available to explain an improvement."
            )
        why_better = (
            "Loại bỏ thành viên có độ hỗ trợ yếu giúp tăng mật độ gắn kết và độ đặc trưng của chuỗi; "
            "không có bằng chứng để gán vai trò nhân quả hoặc phân loại phần tử là nhiễu."
            if is_vi else
            "Removing low-support members increases cohesion density and chain representativeness; "
            "there is no evidence that the member is noise, a root cause, or a separate fault domain."
        )

    elif operation == "SPLIT_CHAIN":
        cut_info = op_ev.get("audit_cut", {})
        phi_val = cut_info.get("conductance")
        label = cut_info.get("label", "cut")
        after_parts = None
        if partition_delta:
            after_parts = (
                partition_delta.get("after")
                if isinstance(partition_delta, dict)
                else getattr(partition_delta, "after", None)
            )
        part_sizes = [len(part[1]) for part in (after_parts or []) if len(part) >= 2]
        action_summary = (
            f"Đề xuất phân tách chuỗi {source_chain_id or ''} theo vết cắt Audit Graph {label}".strip()
            if is_vi else
            f"Proposal to split chain {source_chain_id or ''} along Audit Graph cut {label}".strip()
        )
        if part_sizes:
            points.append(
                f"Kích thước các phân vùng đề xuất: {', '.join(str(size) for size in part_sizes)} cảnh báo."
                if is_vi else
                f"Proposed partition sizes: {', '.join(str(size) for size in part_sizes)} alarms."
            )
        if phi_val is not None:
            points.append(
                f"Audit Graph ghi nhận weak separation tại vết cắt (Phi = {float(phi_val):.3f})."
                if is_vi else
                f"The Audit Graph records weak separation at the cut (Phi = {float(phi_val):.3f})."
            )
        if not points:
            points.append(
                "Chi tiết phân vùng và conductance không khả dụng."
                if is_vi else
                "Partition membership and conductance are unavailable."
            )
        why_better = (
            f"Phân tách chuỗi theo ranh giới Audit Graph (Phi = {float(phi_val):.3f}) giúp cô lập các cụm cảnh báo tách rời; kết quả không khẳng định thiếu liên kết topology vật lý hay hai nguyên nhân độc lập."
            if is_vi else
            f"Splitting along the Audit Graph boundary (Phi = {float(phi_val):.3f}) isolates loosely bound clusters; it does not establish missing physical topology links or independent causes."
        ) if phi_val is not None else (
            "Đây là phương án phân hoạch có ranh giới yếu trên Audit Graph; kết quả không khẳng định thiếu liên kết topology vật lý hay hai nguyên nhân độc lập."
            if is_vi else
            "This partition follows a weak boundary in the Audit Graph; it does not establish missing physical topology links or independent causes."
        )

    elif operation == "MOVE_MEMBER":
        valid_target = target_chain_id and str(target_chain_id).strip() not in ("", "None", "null")
        target = str(target_chain_id) if valid_target else "UNAVAILABLE"
        action_summary = (
            f"Đề xuất di chuyển cảnh báo {m_str} từ chuỗi {source_chain_id or ''} sang chuỗi {target}".strip()
            if is_vi else
            f"Proposal to move alarm {m_str} from chain {source_chain_id or ''} to chain {target}".strip()
        )
        effects = set(semantic_effects or ())
        connector_verified = (
            "BECOMES_CONNECTOR" in effects
            and structural_facts is not None
            and structural_facts.get("after_structural_role") == "CONNECTOR"
        )
        if connector_verified:
            blocks = structural_facts.get("after_blocks_supported")
            blocks_clause = f", hỗ trợ {blocks} block" if blocks is not None else ""
            points.append(
                f"Sau mutation, structural role là CONNECTOR{blocks_clause}."
                if is_vi else
                f"After the mutation, the structural role is CONNECTOR{blocks_clause}."
            )
        if s_b is not None and s_a is not None:
            points.append(
                f"Độ hỗ trợ tối thiểu: {s_b*100:.1f}% → {s_a*100:.1f}%."
                if is_vi else
                f"Minimum support: {s_b*100:.1f}% -> {s_a*100:.1f}%."
            )
        if target_locs:
            points.append(
                f"Trạm của chuỗi đích: {', '.join(target_locs)}."
                if is_vi else
                f"Target chain station: {', '.join(target_locs)}."
            )
        if target_dev_names:
            points.append(
                f"Thiết bị trong chuỗi đích: {', '.join(target_dev_names[:3])}."
                if is_vi else
                f"Target chain devices: {', '.join(target_dev_names[:3])}."
            )
        if time_delta_seconds is not None:
            points.append(
                f"Khoảng cách thời gian tới chuỗi đích: ~{time_delta_seconds}s."
                if is_vi else
                f"Time delta to target chain: ~{time_delta_seconds}s."
            )
        if not points:
            points.append(
                "Không có structural fact hoặc metric delta khả dụng cho đích."
                if is_vi else
                "No target structural fact or metric delta is available."
            )
        if connector_verified:
            why_better = (
                "Cảnh báo đóng vai trò cầu nối (CONNECTOR) liên kết các block cảnh báo và cải thiện độ gắn kết của chuỗi đích; structural fact CONNECTOR đã được cung cấp."
                if is_vi else
                "The alarm acts as a CONNECTOR bridging alarm blocks and improving cohesion in the target chain; structural fact CONNECTOR is verified."
            )
        else:
            ctx_items = []
            if target_locs:
                ctx_items.append(f"cùng trạm {', '.join(target_locs)}")
            if time_delta_seconds is not None:
                ctx_items.append(f"thời gian lân cận (~{time_delta_seconds}s)")
            ctx_clause = f" ({', '.join(ctx_items)})" if ctx_items else ""
            why_better = (
                f"Di chuyển giúp nâng cao độ hỗ trợ thành viên và tính gắn kết với chuỗi đích{ctx_clause}; quan hệ topology, fault domain và nhân quả chưa được xác minh."
                if is_vi else
                f"Moving the alarm improves membership support and cohesion with target chain{ctx_clause}; topology, fault-domain, and causal relationships remain unverified."
            )

    elif operation == "ADD_MEMBER":
        action_summary = (
            f"Đề xuất bổ sung cảnh báo {m_str} vào chuỗi {target_chain_id or 'UNAVAILABLE'}".strip()
            if is_vi else
            f"Proposal to add alarm {m_str} to chain {target_chain_id or 'UNAVAILABLE'}".strip()
        )
        effects = set(semantic_effects or ())
        connector_verified = (
            "BECOMES_CONNECTOR" in effects
            and structural_facts is not None
            and structural_facts.get("after_structural_role") == "CONNECTOR"
        )
        if connector_verified:
            points.append(
                "Structural fact sau mutation xác định thành viên là CONNECTOR."
                if is_vi else
                "The post-mutation structural fact identifies the member as a CONNECTOR."
            )
        else:
            points.append(
                "Vai trò connector và topology adjacency chưa khả dụng."
                if is_vi else
                "Connector role and topology adjacency are unavailable."
            )
        why_better = (
            "Chỉ các metric và structural fact sau mutation được dùng; không suy diễn đường lan truyền."
            if is_vi else
            "Only post-mutation metrics and structural facts are used; no propagation path is inferred."
        )

    elif operation == "MERGE_CHAINS":
        pair_str = " + ".join(merged_chain_ids) if merged_chain_ids else f"{source_chain_id} + candidate"
        cross_ev = op_ev.get("cross_chain_evidence", {})
        edges = cross_ev.get("cross_audit_edge_count")
        action_summary = (
            f"Đề xuất hợp nhất các chuỗi {pair_str}".strip()
            if is_vi else
            f"Proposal to merge chains {pair_str}".strip()
        )
        if edges is not None:
            points.append(
                f"Cross-audit edge count: {int(edges)}."
            )
        if improved:
            points.append(
                ("Metric cải thiện: " if is_vi else "Improved metrics: ")
                + ", ".join(h.label for h in improved)
                + "."
            )
        if shared_locs:
            points.append(
                f"Trùng khớp trạm phát sinh: {', '.join(shared_locs)}."
                if is_vi else
                f"Shared station locations: {', '.join(shared_locs)}."
            )
        if shared_devs:
            points.append(
                f"Thiết bị chung: {', '.join(shared_devs[:3])}."
                if is_vi else
                f"Shared devices: {', '.join(shared_devs[:3])}."
            )
        if merge_time_delta_seconds is not None:
            points.append(
                f"Khoảng cách thời gian giữa 2 chuỗi: ~{merge_time_delta_seconds}s."
                if is_vi else
                f"Time delta between chains: ~{merge_time_delta_seconds}s."
            )
        if not points:
            points.append(
                "Không có cross-audit edge hoặc metric cải thiện khả dụng."
                if is_vi else
                "No cross-audit edge count or improved metric is available."
            )
        ctx_merge = []
        if shared_locs:
            ctx_merge.append(f"cùng trạm {', '.join(shared_locs)}")
        if merge_time_delta_seconds is not None:
            ctx_merge.append(f"chênh lệch thời gian ~{merge_time_delta_seconds}s")
        ctx_merge_str = f" ({', '.join(ctx_merge)})" if ctx_merge else ""
        why_better = (
            f"Đề xuất dựa trên cross-audit evidence và tương quan cụm cảnh báo{ctx_merge_str}; không khẳng định hai chuỗi thuộc cùng một sự cố."
            if is_vi else
            f"The proposal relies on cross-audit evidence and alarm cluster correlation{ctx_merge_str}; it does not assert that both chains share one incident."
        )

    else:
        action_summary = f"Đề xuất thao tác {operation}" if is_vi else f"Proposal {operation}"
        why_better = (
            "Không có rationale theo operation; chỉ các metric delta hiển thị là khả dụng."
            if is_vi else
            "No operation-specific rationale is available; only displayed metric deltas are supported."
        )

    return ComparativeExplanation(
        operation=operation,
        summary_action=action_summary,
        why_better=why_better,
        comparison_points=points,
        delta_highlights=[asdict(h) for h in highlights],
        language=language,
        context_facts=context_facts if context_facts else None,
    )


async def enrich_comparative_explanation_with_ai(
    explanation: ComparativeExplanation,
    *,
    candidate_id: str,
    operation: str,
    before_metrics: Any,
    after_metrics: Any,
    package: IngestedPackage | None = None,
    language: str = "vi",
    target_locs: list[str] | None = None,
    target_dev_names: list[str] | None = None,
    time_delta_seconds: int | None = None,
    target_chain_id: str | None = None,
    source_chain_id: str | None = None,
    member_ids: Sequence[str] | None = None,
    structural_facts: dict[str, Any] | None = None,
) -> ComparativeExplanation:
    """Optionally polish the comparative rationale using live Ollama LLM under ADR-0024."""
    draft = (
        f"{explanation.summary_action}\n\n"
        "So sánh trước và sau:\n"
        + "\n".join(f"- {p}" for p in explanation.comparison_points)
        + f"\n\nVì sao tốt hơn:\n{explanation.why_better}"
    )

    c_facts = explanation.context_facts or {}
    t_locs = target_locs or c_facts.get("target_locs") or c_facts.get("shared_locs")
    t_devs = target_dev_names or c_facts.get("target_dev_names") or c_facts.get("shared_devs")
    t_delta = (
        time_delta_seconds
        if time_delta_seconds is not None
        else (c_facts.get("time_delta_seconds") or c_facts.get("merge_time_delta_seconds"))
    )
    s_facts = structural_facts or c_facts.get("structural_facts")

    fact_refs = [
        candidate_id,
        operation,
        f"highlights_count:{len(explanation.delta_highlights)}",
    ]
    if target_chain_id:
        fact_refs.append(f"target_chain:{target_chain_id}")
    if source_chain_id:
        fact_refs.append(f"source_chain:{source_chain_id}")
    if t_locs:
        for loc in t_locs:
            fact_refs.append(f"location:{loc}")
    if t_devs:
        for dev in t_devs:
            fact_refs.append(f"device:{dev}")
    if t_delta is not None:
        fact_refs.append(f"time_delta:{t_delta}s")
    if member_ids:
        for m in member_ids:
            fact_refs.append(f"alarm:{m}")

    facts: dict[str, Any] = {
        "candidate_id": candidate_id,
        "operation": operation,
        "summary_action": explanation.summary_action,
        "why_better": explanation.why_better,
        "comparison_points": explanation.comparison_points,
        "delta_highlights": explanation.delta_highlights,
    }
    if t_locs:
        facts["target_locs"] = t_locs
        facts["target_locations"] = t_locs
    if t_devs:
        facts["target_dev_names"] = t_devs
        facts["target_devices"] = t_devs
    if t_delta is not None:
        facts["time_delta_seconds"] = t_delta
    if target_chain_id:
        facts["target_chain_id"] = target_chain_id
    if source_chain_id:
        facts["source_chain_id"] = source_chain_id
    if member_ids:
        facts["member_ids"] = list(member_ids)
    if s_facts:
        facts["structural_facts"] = s_facts
        if s_facts.get("after_structural_role"):
            fact_refs.append(f"role:{s_facts['after_structural_role']}")

    try:
        from nocpro_api.grounded_llm import is_provider_configured, render_grounded

        # Keep the deterministic no-provider path synchronous and avoid
        # needless executor work when no provider can be contacted.
        if not is_provider_configured():
            return explanation

        # render_grounded uses urllib synchronously.  This async wrapper is
        # invoked from API routes, so provider I/O must not occupy their event
        # loop thread.
        result = await asyncio.to_thread(
            render_grounded,
            draft=draft,
            facts=facts,
            fact_refs=fact_refs,
            purpose="ADVISOR",
            requested_language=language,
            preserve_provider_output=True,
        )
        if result and result.used_provider and result.message:
            return ComparativeExplanation(
                operation=explanation.operation,
                summary_action=explanation.summary_action,
                why_better=explanation.why_better,
                comparison_points=explanation.comparison_points,
                delta_highlights=explanation.delta_highlights,
                ai_narrative=result.message.strip(),
                language=language,
                context_facts=explanation.context_facts,
            )
    except Exception as exc:
        logger.debug("Ollama LLM polish skipped for candidate %s: %s", candidate_id, exc)

    return explanation
