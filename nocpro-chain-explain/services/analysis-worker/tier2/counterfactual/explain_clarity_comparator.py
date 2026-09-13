"""Engine for evaluating and comparing explanation clarity, specificity, and causality.

Enables direct side-by-side comparison answering:
'Why is this explanation clearer, more specific, and more causal than that one?'
Applicable to:
1. Single-chain threshold tuning (Before vs After explanation clarity).
2. Pareto proposal evaluation (comparing explanations across candidate proposals to find the superior one).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from libs.contracts import IngestedPackage


@dataclass(frozen=True)
class ExplainDimensionScore:
    name: str
    score: float  # 0.0 to 1.0
    weight: float
    description: str
    strengths: list[str] = field(default_factory=list)
    shortcomings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExplainComparisonResult:
    label_a: str
    label_b: str
    explanation_a: str
    explanation_b: str
    winner: str  # "A" | "B" | "TIE"
    clarity_score_a: float  # 0 to 100
    clarity_score_b: float  # 0 to 100
    score_delta: float  # clarity_score_b - clarity_score_a
    why_clearer: list[str]  # Detailed reasons why winner is clearer than loser
    specificity_analysis: dict[str, Any]
    causality_analysis: dict[str, Any]
    actionability_analysis: dict[str, Any]
    summary_verdict: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProposalClarityItem:
    candidate_id: str
    operation: str
    summary_action: str
    explanation_text: str
    clarity_score: float  # 0 to 100
    causal_grounding: float  # 0 to 100
    operational_safety: float  # 0 to 100
    clarity_rank: int
    is_top_pick: bool
    key_strengths: list[str]


@dataclass(frozen=True)
class ProposalClarityComparisonResult:
    proposals: list[ProposalClarityItem]
    top_proposal_id: str | None
    top_proposal_operation: str | None
    head_to_head_comparisons: list[dict[str, Any]]
    overall_recommendation_rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposals": [asdict(p) for p in self.proposals],
            "top_proposal_id": self.top_proposal_id,
            "top_proposal_operation": self.top_proposal_operation,
            "head_to_head_comparisons": self.head_to_head_comparisons,
            "overall_recommendation_rationale": self.overall_recommendation_rationale,
        }


# Device and entity patterns (e.g., CMU0009AGG01, BTS, Router, Ring, Switch, Interface Gi0/1)
_DEVICE_REGEX = re.compile(
    r"\b([A-Z]{2,4}\d{2,6}[A-Z0-9]{2,8}|AGG\d+|SW\d+|ROUTER|SWITCH|BTS|CELL|TRẠM|OLT|ONU|PORT|ETH|GI\d+/\d+)\b",
    re.IGNORECASE,
)
_ALARM_NAME_REGEX = re.compile(
    r"\b(LINK_DOWN|POWER|SYNC|BGP|OSPF|PORT_DOWN|SFP|TEMP|LOS|AIS|ETH|BATTERY|HIGH_TEMP|OPTICAL)\b",
    re.IGNORECASE,
)
_METRIC_NUM_REGEX = re.compile(r"\b(\d+(\.\d+)?%?|\b0\.\d{1,4}\b)")
_VAGUE_TERMS = [
    "một số cảnh báo",
    "có thể có",
    "chưa rõ",
    "chung chung",
    "nhiều yếu tố",
    "some alarms",
    "uncertain",
    "unspecified",
]
_CAUSAL_TERMS = [
    "nguyên nhân",
    "dẫn đến",
    "hệ quả",
    "bởi vì",
    "lan truyền",
    "làm mất tín hiệu",
    "độc lập",
    "kéo theo",
    "do",
    "ảnh hưởng trực tiếp",
    "root cause",
    "cascading",
    "caused by",
    "leads to",
    "isolated",
]
_ACTION_TERMS = [
    "bóc tách",
    "loại bỏ",
    "tập trung xử lý",
    "kiểm tra tuyến",
    "không làm phân mảnh",
    "giữ lại",
    "cô lập",
    "khôi phục",
    "isolate",
    "remove",
    "investigate",
    "consolidate",
]


def evaluate_explain_clarity(
    text: str,
    context: Mapping[str, Any] | None = None,
) -> tuple[float, list[ExplainDimensionScore]]:
    """Evaluates the clarity, specificity, and causal strength of an explanation text.

    Returns:
        total_score (0.0 to 100.0)
        dimensions: breakdown across Specificity, Causality, Actionability, and Conciseness.
    """
    if not text or not text.strip():
        return 0.0, [
            ExplainDimensionScore("specificity", 0.0, 0.35, "Thiếu thông tin cụ thể", [], ["Văn bản giải thích trống"]),
            ExplainDimensionScore("causality", 0.0, 0.30, "Thiếu liên kết nhân quả", [], ["Văn bản giải thích trống"]),
            ExplainDimensionScore("actionability", 0.0, 0.20, "Thiếu hướng hành động", [], ["Văn bản giải thích trống"]),
            ExplainDimensionScore("conciseness", 0.0, 0.15, "Độ cô đọng", [], ["Văn bản giải thích trống"]),
        ]

    normalized_text = text.lower()

    # 1. Specificity Dimension (35% weight)
    # Detect entity mentions, alarm names, metric numbers
    devices_found = list(set(_DEVICE_REGEX.findall(text)))
    alarms_found = list(set(_ALARM_NAME_REGEX.findall(text)))
    numbers_found = _METRIC_NUM_REGEX.findall(text)
    vague_found = [term for term in _VAGUE_TERMS if term in normalized_text]

    spec_strengths: list[str] = []
    spec_shortcomings: list[str] = []

    spec_score = 0.3  # Base score for providing some text
    if devices_found:
        spec_score += min(0.35, len(devices_found) * 0.15)
        spec_strengths.append(f"Chỉ đích danh thiết bị/trạm: {', '.join(devices_found[:3])}")
    else:
        spec_shortcomings.append("Chưa nêu tên thiết bị hoặc trạm cụ thể")

    if alarms_found:
        spec_score += min(0.25, len(alarms_found) * 0.12)
        spec_strengths.append(f"Xác định đúng loại sự cố: {', '.join(alarms_found[:2])}")
    else:
        spec_shortcomings.append("Chưa định danh mã cảnh báo chính")

    if numbers_found:
        spec_score += min(0.15, len(numbers_found) * 0.05)
        spec_strengths.append("Có số liệu định lượng kiểm chứng Before/After")

    if vague_found:
        spec_score = max(0.1, spec_score - len(vague_found) * 0.15)
        spec_shortcomings.append(f"Sử dụng từ ngữ mơ hồ: \"{', '.join(vague_found)}\"")

    spec_score = min(1.0, max(0.0, spec_score))

    # 2. Causality Dimension (30% weight)
    # Detect causal reasoning vs just chronological listing
    causal_found = [term for term in _CAUSAL_TERMS if term in normalized_text]
    caus_strengths: list[str] = []
    caus_shortcomings: list[str] = []

    caus_score = 0.25
    if causal_found:
        caus_score += min(0.65, len(causal_found) * 0.20)
        caus_strengths.append(f"Chỉ rõ quan hệ nhân quả (Root Cause -> Consequence): {', '.join(causal_found[:3])}")
    else:
        caus_shortcomings.append("Chỉ liệt kê trạng thái tĩnh, chưa giải thích cơ chế lan truyền lỗi")

    if "nguyên nhân" in normalized_text or "root cause" in normalized_text:
        caus_score += 0.1
        caus_strengths.append("Xác định trực diện nguyên nhân gốc của sự cố")

    caus_score = min(1.0, max(0.0, caus_score))

    # 3. Actionability Dimension (20% weight)
    action_found = [term for term in _ACTION_TERMS if term in normalized_text]
    act_strengths: list[str] = []
    act_shortcomings: list[str] = []

    act_score = 0.2
    if action_found:
        act_score += min(0.7, len(action_found) * 0.25)
        act_strengths.append(f"Định hướng xử lý dứt khoát: {', '.join(action_found[:3])}")
    else:
        act_shortcomings.append("Chưa đưa ra khuyến nghị hành động cụ thể cho kỹ sư")

    act_score = min(1.0, max(0.0, act_score))

    # 4. Conciseness & Structure Dimension (15% weight)
    conc_strengths: list[str] = []
    conc_shortcomings: list[str] = []
    length = len(text)
    if 60 <= length <= 600:
        conc_score = 0.9
        conc_strengths.append("Độ dài cô đọng, vừa đủ thông tin cho ca trực NOC")
    elif length < 60:
        conc_score = 0.4
        conc_shortcomings.append("Giải thích quá ngắn, thiếu bối cảnh vận hành")
    else:
        conc_score = 0.7
        conc_shortcomings.append("Văn bản hơi dài, cần cô đọng vào trọng tâm")

    # Weighted Total Score (0 - 100)
    total = (
        spec_score * 0.35 +
        caus_score * 0.30 +
        act_score * 0.20 +
        conc_score * 0.15
    ) * 100.0

    dimensions = [
        ExplainDimensionScore("specificity", round(spec_score, 3), 0.35, "Tính cụ thể (Thiết bị, trạm, mã lỗi)", spec_strengths, spec_shortcomings),
        ExplainDimensionScore("causality", round(caus_score, 3), 0.30, "Tính nhân quả (Nguyên nhân -> Hệ quả)", caus_strengths, caus_shortcomings),
        ExplainDimensionScore("actionability", round(act_score, 3), 0.20, "Tính định hướng hành động (Xử lý dứt khoát)", act_strengths, act_shortcomings),
        ExplainDimensionScore("conciseness", round(conc_score, 3), 0.15, "Tính cô đọng & Cấu trúc lập luận", conc_strengths, conc_shortcomings),
    ]

    return round(total, 1), dimensions


def compare_two_explanations(
    exp_a: str,
    exp_b: str,
    *,
    label_a: str = "Lời giải thích A",
    label_b: str = "Lời giải thích B",
    context_a: Mapping[str, Any] | None = None,
    context_b: Mapping[str, Any] | None = None,
) -> ExplainComparisonResult:
    """Directly compares two explanations and explains why one is clearer than the other."""
    score_a, dims_a = evaluate_explain_clarity(exp_a, context_a)
    score_b, dims_b = evaluate_explain_clarity(exp_b, context_b)

    dim_a_spec = next(d for d in dims_a if d.name == "specificity")
    dim_b_spec = next(d for d in dims_b if d.name == "specificity")
    dim_a_caus = next(d for d in dims_a if d.name == "causality")
    dim_b_caus = next(d for d in dims_b if d.name == "causality")
    dim_a_act = next(d for d in dims_a if d.name == "actionability")
    dim_b_act = next(d for d in dims_b if d.name == "actionability")

    score_delta = round(score_b - score_a, 1)
    if abs(score_delta) < 1.0:
        winner = "TIE"
    elif score_delta > 0:
        winner = "B"
    else:
        winner = "A"

    why_clearer: list[str] = []

    if winner == "TIE":
        why_clearer.append(
            f"Hai lời giải thích có độ rõ ràng và mức độ thuyết phục tương đương nhau (chênh lệch điểm không đáng kể: {score_a:.1f} vs {score_b:.1f})."
        )
    else:
        winning_label = label_b if winner == "B" else label_a
        losing_label = label_a if winner == "B" else label_b
        winner_dims = dims_b if winner == "B" else dims_a
        loser_dims = dims_a if winner == "B" else dims_b

        # 1. Specificity Comparison
        dim_w_spec = next(d for d in winner_dims if d.name == "specificity")
        dim_l_spec = next(d for d in loser_dims if d.name == "specificity")
        if dim_w_spec.score > dim_l_spec.score:
            items_str = "; ".join(dim_w_spec.strengths[:2]) if dim_w_spec.strengths else "chỉ rõ thông tin đối tượng"
            why_clearer.append(
                f"Về tính cụ thể: {winning_label} chỉ đích danh thiết bị và đối tượng tác động ({items_str}), "
                f"thay vì dùng nhận định mơ hồ như {losing_label}."
            )

        # 2. Causality Comparison
        dim_w_caus = next(d for d in winner_dims if d.name == "causality")
        dim_l_caus = next(d for d in loser_dims if d.name == "causality")
        if dim_w_caus.score > dim_l_caus.score:
            why_clearer.append(
                f"Về tính nhân quả: {winning_label} phân tích rõ cơ chế lan truyền (nguyên nhân gốc -> hệ quả), "
                f"giúp kỹ sư bóc tách đúng bản chất sự cố thay vì chỉ liệt kê thời gian đơn thuần."
            )

        # 3. Actionability Comparison
        dim_w_act = next(d for d in winner_dims if d.name == "actionability")
        dim_l_act = next(d for d in loser_dims if d.name == "actionability")
        if dim_w_act.score > dim_l_act.score:
            why_clearer.append(
                f"Về tính hành động: {winning_label} đưa ra hướng xử lý dứt khoát cho kỹ sư trực ca, "
                f"không gây phân tán tài nguyên ứng cứu."
            )

        if not why_clearer:
            why_clearer.append(
                f"{winning_label} đạt điểm mạch lạc và thuyết phục tổng thể cao hơn ({max(score_a, score_b):.1f} vs {min(score_a, score_b):.1f} điểm)."
            )

    # Summary verdict
    if winner == "B":
        summary_verdict = (
            f"{label_b} rõ ràng và thuyết phục hơn {label_a} (+{abs(score_delta):.1f} điểm). "
            f"Lập luận sắc nét, chỉ đúng thiết bị và nguyên nhân cốt lõi."
        )
    elif winner == "A":
        summary_verdict = (
            f"{label_a} rõ ràng và thuyết phục hơn {label_b} (+{abs(score_delta):.1f} điểm). "
            f"Lập luận chắc chắn và có độ cụ thể cao hơn."
        )
    else:
        summary_verdict = "Cả hai lời giải thích đều đạt độ rõ ràng tương đương nhau trên các tiêu chí vận hành."

    return ExplainComparisonResult(
        label_a=label_a,
        label_b=label_b,
        explanation_a=exp_a,
        explanation_b=exp_b,
        winner=winner,
        clarity_score_a=score_a,
        clarity_score_b=score_b,
        score_delta=score_delta,
        why_clearer=why_clearer,
        specificity_analysis={
            "score_a": dim_a_spec.score,
            "score_b": dim_b_spec.score,
        },
        causality_analysis={
            "score_a": dim_a_caus.score,
            "score_b": dim_b_caus.score,
        },
        actionability_analysis={
            "score_a": dim_a_act.score,
            "score_b": dim_b_act.score,
        },
        summary_verdict=summary_verdict,
    )


def compare_proposal_explanations(
    candidates: Sequence[Mapping[str, Any]],
    package: IngestedPackage | None = None,
) -> ProposalClarityComparisonResult:
    """Evaluates and compares explanations across all Pareto optimal candidates.

    Identifies the proposal with the clearest, most grounded rationale and generates
    head-to-head comparative critique between proposals.
    """
    if not candidates:
        return ProposalClarityComparisonResult(
            proposals=[],
            top_proposal_id=None,
            top_proposal_operation=None,
            head_to_head_comparisons=[],
            overall_recommendation_rationale="Không có đề xuất nào trên biên Pareto để so sánh.",
        )

    evaluated_items: list[tuple[float, ProposalClarityItem, Mapping[str, Any]]] = []

    for c in candidates:
        cand_id = str(c.get("candidate_id", ""))
        op = str(c.get("operation", "UNKNOWN"))
        comp_exp = c.get("comparative_explanation") or {}
        summary_action = str(comp_exp.get("summary_action") or f"Đề xuất {op}")
        why_better = str(comp_exp.get("why_better") or "")
        ai_narrative = str(comp_exp.get("ai_narrative") or "")
        points = comp_exp.get("comparison_points") or []
        points_text = " ".join(str(p) for p in points)

        full_text = f"{summary_action}. {why_better}. {points_text}. {ai_narrative}".strip()

        score, dims = evaluate_explain_clarity(full_text)
        caus_dim = next((d for d in dims if d.name == "causality"), None)
        act_dim = next((d for d in dims if d.name == "actionability"), None)

        causal_grounding = round((caus_dim.score if caus_dim else 0.5) * 100, 1)
        operational_safety = round((act_dim.score if act_dim else 0.5) * 100, 1)

        strengths = []
        for d in dims:
            strengths.extend(d.strengths[:1])

        item = ProposalClarityItem(
            candidate_id=cand_id,
            operation=op,
            summary_action=summary_action,
            explanation_text=full_text,
            clarity_score=score,
            causal_grounding=causal_grounding,
            operational_safety=operational_safety,
            clarity_rank=0,
            is_top_pick=False,
            key_strengths=strengths[:3],
        )
        evaluated_items.append((score, item, c))

    # Sort proposals by clarity score descending
    evaluated_items.sort(key=lambda x: x[0], reverse=True)

    ranked_proposals: list[ProposalClarityItem] = []
    for rank_idx, (sc, item, raw_c) in enumerate(evaluated_items):
        updated_item = ProposalClarityItem(
            candidate_id=item.candidate_id,
            operation=item.operation,
            summary_action=item.summary_action,
            explanation_text=item.explanation_text,
            clarity_score=item.clarity_score,
            causal_grounding=item.causal_grounding,
            operational_safety=item.operational_safety,
            clarity_rank=rank_idx + 1,
            is_top_pick=(rank_idx == 0),
            key_strengths=item.key_strengths,
        )
        ranked_proposals.append(updated_item)

    top_item = ranked_proposals[0]

    # Head-to-head pairwise comparisons against the top pick
    head_to_head: list[dict[str, Any]] = []
    for other in ranked_proposals[1:]:
        comp_res = compare_two_explanations(
            other.explanation_text,
            top_item.explanation_text,
            label_a=f"Đề xuất {other.operation} ({other.candidate_id[:8]})",
            label_b=f"Đề xuất {top_item.operation} ({top_item.candidate_id[:8]})",
        )
        head_to_head.append({
            "target_candidate_id": other.candidate_id,
            "target_operation": other.operation,
            "target_clarity_score": other.clarity_score,
            "top_candidate_id": top_item.candidate_id,
            "top_operation": top_item.operation,
            "top_clarity_score": top_item.clarity_score,
            "score_advantage": comp_res.score_delta,
            "why_top_is_clearer": comp_res.why_clearer,
            "summary_verdict": comp_res.summary_verdict,
        })

    overall_rationale = (
        f"Trong số {len(candidates)} phương án trên biên Pareto, Đề xuất '{top_item.operation}' ({top_item.candidate_id[:8]}) "
        f"có lời giải thích rõ ràng và thuyết phục nhất ({top_item.clarity_score:.1f}/100 điểm). "
        f"Phương án này chỉ rõ bản chất sự cố, có căn cứ bóc tách dứt khoát và giảm thiểu rủi ro vận hành so với các phương án còn lại."
    )

    return ProposalClarityComparisonResult(
        proposals=ranked_proposals,
        top_proposal_id=top_item.candidate_id,
        top_proposal_operation=top_item.operation,
        head_to_head_comparisons=head_to_head,
        overall_recommendation_rationale=overall_rationale,
    )
