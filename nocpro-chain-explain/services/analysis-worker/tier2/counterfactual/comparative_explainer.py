"""Comparative Explainer Engine for Counterfactual Candidates (Phase 2).

Generates grounded, deterministic Before vs After comparative metrics and
domain-specific rationale for why each candidate mutation improves chain explainability,
with optional ADR-0024 grounded LLM narrative polish.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from libs.contracts import IngestedPackage

logger = logging.getLogger(__name__)


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "summary_action": self.summary_action,
            "why_better": self.why_better,
            "comparison_points": list(self.comparison_points),
            "delta_highlights": list(self.delta_highlights),
            "ai_narrative": self.ai_narrative,
            "language": self.language,
        }


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
    deltas = dict(metric_deltas or {})
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

    # Gather info on affected alarms from package
    affected_details: list[str] = []
    if package and member_ids:
        for m_id in list(member_ids)[:3]:
            alm = package.alarms.get(m_id)
            if alm:
                alm_name = alm.alarm_name or "Unknown Alarm"
                dev = alm.device_code or "Unknown Device"
                affected_details.append(f"{m_id} ({alm_name} trên {dev})" if is_vi else f"{m_id} ({alm_name} on {dev})")
            else:
                affected_details.append(m_id)

    points: list[str] = []
    action_summary = ""
    why_better = ""

    # Generate operation-specific comparative rationale
    if operation == "REMOVE_MEMBER":
        count = len(member_ids)
        m_str = ", ".join(affected_details) if affected_details else ", ".join(member_ids)
        if is_vi:
            action_summary = f"Đề xuất loại bỏ {count} cảnh báo ({m_str}) ra khỏi chuỗi {source_chain_id or ''}".strip()
            if w_b and w_a is not None and w_a < w_b:
                points.append(f"Giảm số lượng cảnh báo lạc quẻ (WEAK) từ {int(w_b)} xuống {int(w_a)} (giảm {int(w_b - w_a)} cảnh báo gây nhiễu).")
            if s_b is not None and s_a is not None and s_a > s_b:
                points.append(f"Tăng độ hỗ trợ liên kết thành viên tối thiểu từ {s_b*100:.1f}% lên {s_a*100:.1f}% (+{(s_a - s_b)*100:.1f}%).")
            points.append("Loại bỏ phần tử không tương đồng giúp nâng cao độ gắn kết nội tại của chuỗi sự cố.")
            why_better = (
                f"Cảnh báo {m_str} có mức độ gắn kết yếu với các thành viên còn lại. "
                "Việc loại bỏ giúp chuỗi thuần nhất hơn về đặc trưng sự cố, ngăn ngừa tình trạng một cảnh báo ngoại lai làm loãng bức tranh phân tích nguyên nhân gốc."
            )
        else:
            action_summary = f"Proposal to remove {count} alarm(s) ({m_str}) from chain {source_chain_id or ''}".strip()
            if w_b and w_a is not None and w_a < w_b:
                points.append(f"Reduced weak member count from {int(w_b)} to {int(w_a)} (-{int(w_b - w_a)} noisy alarms).")
            if s_b is not None and s_a is not None and s_a > s_b:
                points.append(f"Increased minimum membership support from {s_b*100:.1f}% to {s_a*100:.1f}% (+{(s_a - s_b)*100:.1f}%).")
            points.append("Purging weak components improves the internal cohesion of the incident chain.")
            why_better = (
                f"The alarm(s) {m_str} exhibit weak evidence correlation with the core incident. "
                "Removing them produces a cleaner incident boundary without peripheral noise."
            )

    elif operation == "SPLIT_CHAIN":
        cut_info = op_ev.get("audit_cut", {})
        phi_val = cut_info.get("conductance")
        label = cut_info.get("label", "cut")
        if is_vi:
            action_summary = f"Đề xuất phân tách chuỗi {source_chain_id or ''} thành 2 chuỗi con độc lập theo vết cắt {label}".strip()
            if phi_val is not None:
                points.append(f"Phát hiện vết cắt đồ thị có độ dẫn nạp Conductance thấp (Phi = {phi_val:.3f}), chứng tỏ 2 nhóm thành viên ít liên quan.")
            points.append("Chia tách chuỗi lớn thành 2 sự cố độc lập có tính cục bộ cao hơn.")
            why_better = (
                "Chuỗi hiện tại đang ghép lỏng lẻo 2 phân cụm cảnh báo riêng biệt. "
                "Phân tách giúp mỗi chuỗi con có trọng tâm rõ ràng theo phân vùng thiết bị hoặc thời gian, giúp phân công kỹ sư xử lý chính xác hơn."
            )
        else:
            action_summary = f"Proposal to split chain {source_chain_id or ''} into 2 independent sub-chains along {label}".strip()
            if phi_val is not None:
                points.append(f"Detected low-conductance cut (Phi = {phi_val:.3f}), indicating weak inter-cluster connectivity.")
            points.append("Separates a compound chain into distinct, focused incidents.")
            why_better = (
                "The current chain bundles two loosely coupled alarm clusters. "
                "Splitting establishes well-bounded incidents aligned with actual network fault domains."
            )

    elif operation == "MOVE_MEMBER":
        m_str = ", ".join(affected_details) if affected_details else ", ".join(member_ids)
        effects = set(semantic_effects or ())
        is_connector = (
            "BECOMES_CONNECTOR" in effects
            or (structural_facts is not None and structural_facts.get("after_structural_role") == "CONNECTOR")
        )
        blocks = structural_facts.get("after_blocks_supported") if structural_facts else None
        blocks_text_vi = f"{blocks} phân đoạn mạng" if blocks else "các phân đoạn mạng"
        blocks_text_en = f"{blocks} network blocks" if blocks else "network blocks"

        if is_connector:
            if is_vi:
                action_summary = f"Đề xuất di chuyển cảnh báo {m_str} sang chuỗi {target_chain_id or ''} để làm CẦU NỐI (CONNECTOR) liên kết".strip()
                points.append(f"Cảnh báo sau khi di chuyển đóng vai trò là CẦU NỐI (Articulation Point) liên kết trực tiếp giữa {blocks_text_vi} trong chuỗi đích.")
                points.append("Khắc phục phân mảnh tô-pô, giúp chuỗi sự cố đạt tính liên thông cấu trúc toàn diện.")
                if s_a is not None and s_b is not None and s_a >= s_b:
                    points.append(f"Duy trì hoặc cải thiện độ hỗ trợ thành viên ({s_b*100:.1f}% → {s_a*100:.1f}%).")
                why_better = (
                    f"Cảnh báo {m_str} đóng vai trò là CẦU NỐI (CONNECTOR) then chốt: trong chuỗi hiện tại nó không phát huy tác dụng liên kết, "
                    f"nhưng khi đưa sang chuỗi {target_chain_id}, nó bắc cầu kết nối trực tiếp giữa {blocks_text_vi} bị tách rời thành một sự cố mạng thống nhất, "
                    "giúp kỹ sư NOC nhìn rõ đường truyền lỗi và xử lý triệt để nguyên nhân gốc rễ."
                )
            else:
                action_summary = f"Proposal to move alarm {m_str} to target chain {target_chain_id or ''} as a structural CONNECTOR".strip()
                points.append(f"Member becomes a CONNECTOR (articulation point) bridging {blocks_text_en} in target chain {target_chain_id}.")
                points.append("Eliminates topological fragmentation and restores end-to-end incident continuity.")
                if s_a is not None and s_b is not None and s_a >= s_b:
                    points.append(f"Maintains or improves membership support ({s_b*100:.1f}% → {s_a*100:.1f}%).")
                why_better = (
                    f"Alarm {m_str} serves as an indispensable structural CONNECTOR: transferring it bridges {blocks_text_en} "
                    f"in chain {target_chain_id} into a single cohesive fault domain, enabling operators to trace the root-cause propagation path."
                )
        else:
            if is_vi:
                action_summary = f"Đề xuất di chuyển cảnh báo {m_str} từ chuỗi {source_chain_id or ''} sang chuỗi đích {target_chain_id or ''}".strip()
                points.append(f"Cảnh báo có biên độ liên kết (Margin) ưu tiên nghiêng về chuỗi đích {target_chain_id}.")
                if s_a is not None and s_b is not None and s_a >= s_b:
                    points.append(f"Duy trì hoặc cải thiện độ hỗ trợ thành viên tối thiểu ({s_b*100:.1f}% → {s_a*100:.1f}%).")
                why_better = (
                    f"Cảnh báo {m_str} có mức độ tương đồng bằng chứng và vị trí topo gần gũi với chuỗi {target_chain_id} hơn so với chuỗi hiện tại. "
                    "Việc chuyển giao giúp cảnh báo nằm đúng vào chuỗi sự cố gốc của nó."
                )
            else:
                action_summary = f"Proposal to move alarm {m_str} from chain {source_chain_id or ''} to chain {target_chain_id or ''}".strip()
                points.append(f"Member exhibits a target-favored margin towards destination chain {target_chain_id}.")
                if s_a is not None and s_b is not None and s_a >= s_b:
                    points.append(f"Maintains or improves minimum membership support ({s_b*100:.1f}% → {s_a*100:.1f}%).")
                why_better = (
                    f"The alarm {m_str} shares stronger topological and temporal affinity with {target_chain_id} than its current chain. "
                    "Reassigning places the alarm in its authentic incident context."
                )

    elif operation == "ADD_MEMBER":
        m_str = ", ".join(affected_details) if affected_details else ", ".join(member_ids)
        if is_vi:
            action_summary = f"Đề xuất bổ sung cảnh báo {m_str} vào chuỗi {target_chain_id or ''} làm CẦU NỐI liên kết".strip()
            points.append("Bổ sung phần tử liên kết tô-pô giúp nối liền các phân đoạn cảnh báo rời rạc.")
            why_better = (
                f"Cảnh báo {m_str} đóng vai trò là CẦU NỐI (CONNECTOR) còn thiếu: việc bổ sung cảnh báo này vào chuỗi "
                "giúp hàn gắn vết đứt gãy giữa các cụm sự cố, khôi phục bức tranh toàn cảnh về sự cố mạng lan truyền."
            )
        else:
            action_summary = f"Proposal to add alarm {m_str} to chain {target_chain_id or ''} as a linking connector".strip()
            points.append("Adds a topological connector that bridges previously disjoint alarm segments.")
            why_better = (
                f"Alarm {m_str} acts as a missing structural CONNECTOR: adding it resolves the topological gap "
                "between incident clusters and restores the complete cascading incident chain."
            )

    elif operation == "MERGE_CHAINS":
        pair_str = " + ".join(merged_chain_ids) if merged_chain_ids else f"{source_chain_id} + candidate"
        cross_ev = op_ev.get("cross_chain_evidence", {})
        edges = cross_ev.get("cross_audit_edge_count", 0)
        if is_vi:
            action_summary = f"Đề xuất hợp nhất 2 chuỗi sự cố {pair_str} thành 1 chuỗi tổng thể".strip()
            if edges:
                points.append(f"Xác nhận {edges} liên kết kề topo và thời gian đồng bộ trực tiếp giữa 2 chuỗi.")
            points.append("Hợp nhất 2 chuỗi bị phân mảnh thuộc về cùng một sự cố lan truyền mạng.")
            why_better = (
                f"Hai chuỗi {pair_str} có bằng chứng kết nối mạnh mẽ qua các liên kết mạng và xảy ra cùng thời điểm. "
                "Hợp nhất giúp kỹ sư NOC có cái nhìn toàn cảnh về sự cố thay vì phải theo dõi nhiều chuỗi rời rạc."
            )
        else:
            action_summary = f"Proposal to merge incident chains {pair_str} into a unified incident chain".strip()
            if edges:
                points.append(f"Verified {edges} cross-chain audit edges and temporal co-occurrence between the chains.")
            points.append("Consolidates fragmented chains belonging to the same cascading network incident.")
            why_better = (
                f"The chains {pair_str} demonstrate substantial topological adjacency and synchronous timing. "
                "Merging provides operators with a complete, end-to-end incident perspective."
            )

    else:
        action_summary = f"Đề xuất thao tác {operation}" if is_vi else f"Proposal {operation}"
        why_better = "Cải thiện các chỉ số gắn kết và cấu trúc chuỗi." if is_vi else "Improves chain structural cohesion metrics."

    return ComparativeExplanation(
        operation=operation,
        summary_action=action_summary,
        why_better=why_better,
        comparison_points=points,
        delta_highlights=[asdict(h) for h in highlights],
        language=language,
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
) -> ComparativeExplanation:
    """Optionally polish the comparative rationale using live Ollama LLM under ADR-0024."""
    draft = f"{explanation.summary_action}\n\nSo sánh trước và sau:\n" + "\n".join(f"- {p}" for p in explanation.comparison_points) + f"\n\nVì sao tốt hơn:\n{explanation.why_better}"
    fact_refs = [
        candidate_id,
        operation,
        f"highlights_count:{len(explanation.delta_highlights)}",
    ]
    facts = {
        "candidate_id": candidate_id,
        "operation": operation,
        "summary_action": explanation.summary_action,
        "why_better": explanation.why_better,
        "comparison_points": explanation.comparison_points,
        "delta_highlights": explanation.delta_highlights,
    }

    try:
        from nocpro_api.grounded_llm import render_grounded

        result = render_grounded(
            draft=draft,
            facts=facts,
            fact_refs=fact_refs,
            purpose="ADVISOR",
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
            )
    except Exception as exc:
        logger.debug("Ollama LLM polish skipped for candidate %s: %s", candidate_id, exc)

    return explanation
