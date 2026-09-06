"""Read-only NocPro Assistant with native LLM tool calling and deterministic fallback.

The assistant is a projection and navigation layer over the current workspace.
It uses native LLM tool selection to interpret user intent without brittle keyword
matching, while ensuring all tool executions and navigation targets remain strictly
bound and validated against the active snapshot.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from .grounded_llm import (
    call_grounded_assistant,
    is_provider_configured,
    render_grounded,
)

logger = logging.getLogger(__name__)

REGISTRY_VERSION = "nocpro-assistant-registry-v1"

SEMANTIC_REGISTRY: dict[str, dict[str, str]] = {
    "conductance": {
        "title": "Audit conductance",
        "definition": "The exact Audit cut score compares edges crossing a cut with the smaller side's volume.",
        "interpretation": "Lower values can indicate a weakly connected separation, but are not a root-cause claim.",
        "limitation": "UNAVAILABLE means no exact eligible Audit result exists; it is not zero conductance.",
    },
    "membership_support": {
        "title": "Membership support",
        "definition": "The computed support for one alarm's membership in the currently selected chain.",
        "interpretation": "It is evidence support, not a causal probability or an instruction to remove an alarm.",
        "limitation": "INSUFFICIENT_DATA and an unavailable value must not be rendered as zero.",
    },
    "pair_why": {
        "title": "Pair WHY",
        "definition": "A lazy evaluation of evidence channels for two selected alarms in one chain.",
        "interpretation": "It explains available evidence for the pair; it does not establish root cause.",
        "limitation": "The pair must belong to the selected chain and uses the active snapshot identity.",
    },
    "counterfactual_review": {
        "title": "Counterfactual Review",
        "definition": "A bounded, exact evaluation of candidate partition edits already produced by the Review engine.",
        "interpretation": "Recommendations are operator-facing proposals, not automatic changes to NocPro membership.",
        "limitation": "Missing or incompatible artifacts remain unavailable; the assistant never starts a Review job.",
    },
    "topology": {
        "title": "Topology navigation",
        "definition": "A read-only normalized source-relation tree for navigating IP or IT topology records.",
        "interpretation": "IT directed source relations are navigation data, not validated operational dependency semantics.",
        "limitation": "Topology navigation never promotes an edge to P2/RCA evidence.",
    },
}

ASSISTANT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "explain_metric",
            "description": "Giải thích định nghĩa lý thuyết, ý nghĩa khái niệm và ranh giới khoa học của các thuật ngữ (conductance, membership_support, pair_why, counterfactual_review, topology). Dùng khi người dùng hỏi khái niệm/định nghĩa chung. KHÔNG dùng khi người dùng hỏi về số liệu, lát cắt hay biểu đồ của một chuỗi cụ thể.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_name": {
                        "type": "string",
                        "enum": [
                            "conductance",
                            "membership_support",
                            "pair_why",
                            "counterfactual_review",
                            "topology",
                        ],
                        "description": "Tên chỉ số hoặc khái niệm cần giải thích.",
                    }
                },
                "required": ["metric_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_workspace",
            "description": "Điều hướng giao diện làm việc tới một tab tương ứng (why, structure, review, evolution, topology) cho một chuỗi cảnh báo (chain_id) hoặc cặp cảnh báo (pair_alarm_id_a, pair_alarm_id_b).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tab": {
                        "type": "string",
                        "enum": ["why", "structure", "review", "evolution", "topology", "tree"],
                        "description": "Tab giao diện cần mở: structure (Audit kiểm định cấu trúc), why (Bằng chứng cặp Pair WHY), review (Đề xuất tách/gộp chuỗi), evolution (Tiến hóa sự cố), topology (Cây topology), tree (Chi tiết chuỗi).",
                    },
                    "chain_id": {
                        "type": "string",
                        "description": "ID của chuỗi sự cố cần mở (nếu có).",
                    },
                    "pair_alarm_id_a": {
                        "type": "string",
                        "description": "ID của cảnh báo thứ nhất nếu mở tab Pair WHY.",
                    },
                    "pair_alarm_id_b": {
                        "type": "string",
                        "description": "ID của cảnh báo thứ hai nếu mở tab Pair WHY.",
                    },
                },
                "required": ["tab"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_chains",
            "description": "Tìm kiếm các chuỗi cảnh báo trong snapshot hiện tại theo ID hoặc từ khóa tiêu đề/triệu chứng.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Từ khóa tìm kiếm (chuỗi ID hoặc tên triệu chứng/thiết bị).",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_root_cause_boundary",
            "description": "Giải thích lý do tại sao bằng chứng gom nhóm cảnh báo không thể tự động kết luận nguyên nhân gốc (root cause/RCA) và đưa ra các hành động xem bằng chứng kiểm định cấu trúc hoặc so sánh cặp.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_resource_mapping_unavailable",
            "description": "Báo cáo rằng tìm kiếm từ tài nguyên/service sang chuỗi không khả dụng và điều hướng sang cây Topology.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_chart",
            "description": "Lấy dữ liệu số thực tế và đường vẽ của biểu đồ hoặc lát cắt trên một chuỗi cảnh báo cụ thể (đường cong Deletion Curve, diện tích AUC, độ dốc, điểm rơi, độ dẫn Conductance Φ của lát cắt Best Cut, Over-merge). Dùng khi người dùng hỏi về số liệu, lát cắt hoặc đường vẽ biểu đồ của chuỗi đang xem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": [
                            "attribution_deletion_curve",
                            "conductance_cut",
                            "evolution_lineage",
                            "counterfactual_review",
                        ],
                        "description": "Loại biểu đồ cần lấy dữ liệu: attribution_deletion_curve (đường cong Deletion curve và diện tích AUC), conductance_cut (lát cắt độ dẫn Conductance Cut và over-merge), evolution_lineage (tiến hóa theo thời gian), counterfactual_review (so sánh can thiệp tách/gộp).",
                    },
                    "chain_id": {
                        "type": "string",
                        "description": "ID chuỗi cảnh báo cần xem biểu đồ. Nếu bỏ trống sẽ lấy chuỗi đang chọn trong ngữ cảnh.",
                    },
                },
                "required": ["chart_type"],
            },
        },
    },
]

TAB_LABELS: dict[str, str] = {
    "why": "Open Pair WHY",
    "structure": "Open Structural Audit",
    "review": "Open Counterfactual Review",
    "evolution": "Open Evolution",
    "topology": "Open Topology",
    "tree": "Open Chain",
}


@dataclass(frozen=True)
class AssistantAction:
    kind: str
    label: str
    target: dict[str, str | None]


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _definition_response(key: str) -> tuple[str, list[str]]:
    item = SEMANTIC_REGISTRY[key]
    return (
        f"**{item['title']}**\n\n{item['definition']}\n\n"
        f"Interpretation: {item['interpretation']}\n\n"
        f"Boundary: {item['limitation']}",
        [f"semantic-registry:{key}"],
    )


def _find_chain_matches(service: Any, query: str) -> list[Any]:
    needle = _normalize(query)
    if not needle:
        return []
    listed = service.list_chains()
    matches = [
        chain for chain in listed.chains.values()
        if needle in _normalize(chain.chain_id) or needle in _normalize(chain.auto_title)
    ]
    return sorted(matches, key=lambda chain: chain.chain_id)[:10]


def _active_context_matches(service: Any, context: dict[str, Any]) -> bool:
    requested_id = context.get("snapshot_id")
    requested_version = context.get("snapshot_version")
    active = service.active_identity()
    return (
        active is not None
        and requested_id == active[0]
        and requested_version == active[1]
    )


def _navigation_action(
    service: Any,
    *,
    label: str,
    tab: str,
    chain_id: str | None = None,
    pair_alarm_id_a: str | None = None,
    pair_alarm_id_b: str | None = None,
) -> dict[str, Any]:
    """Make an identity-bound in-app action from the currently active snapshot."""
    active = service.active_identity()
    if active is None:
        raise RuntimeError("assistant action requested without an active snapshot")
    action = AssistantAction(
        "NAVIGATE",
        label,
        {
            "snapshot_id": active[0],
            "snapshot_version": active[1],
            "chain_id": chain_id,
            "tab": tab,
            "pair_alarm_id_a": pair_alarm_id_a,
            "pair_alarm_id_b": pair_alarm_id_b,
        },
    )
    return {"kind": action.kind, "label": action.label, "target": action.target}


def _active_chain_id(service: Any, context: dict[str, Any]) -> str | None:
    """Return a context chain only when it belongs to the active snapshot."""
    chain_id = context.get("chain_id")
    if not isinstance(chain_id, str) or not chain_id:
        return None
    package = service.require_package()
    return chain_id if chain_id in package.chains else None


def _active_pair(service: Any, context: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return a validated same-chain pair without evaluating Pair WHY."""
    chain_id = _active_chain_id(service, context)
    alarm_a = context.get("pair_alarm_id_a")
    alarm_b = context.get("pair_alarm_id_b")
    if (
        chain_id is None
        or not isinstance(alarm_a, str)
        or not isinstance(alarm_b, str)
        or not alarm_a
        or not alarm_b
        or alarm_a == alarm_b
    ):
        return None
    package = service.require_package()
    members = set(package.members_of(chain_id))
    if alarm_a not in members or alarm_b not in members:
        return None
    return chain_id, alarm_a, alarm_b


def _unavailable(message: str, reason: str) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "message": message,
        "fact_refs": [f"capability:{reason}"],
        "actions": [],
    }


def _get_or_run_audit(service: Any, chain_id: str) -> Any | None:
    package = service.require_package()
    if chain_id not in package.chains:
        return None
    job_view = service.jobs.latest_succeeded(
        package.snapshot.snapshot_id, package.snapshot.snapshot_version, chain_id
    )
    if job_view is not None and job_view.result is not None:
        return job_view.result

    try:
        service.submit_deep_dive(chain_id)
        for _ in range(25):
            job_view = service.jobs.latest_succeeded(
                package.snapshot.snapshot_id, package.snapshot.snapshot_version, chain_id
            )
            if job_view is not None and job_view.result is not None:
                return job_view.result
            time.sleep(0.04)
    except Exception as exc:
        logger.warning("Failed running Tier 2 deep dive for chain %s: %s", chain_id, exc)
    return None


def _handle_inspect_chart(
    service: Any, chain_id: str, chart_kind: str, context: dict[str, Any]
) -> dict[str, Any]:
    if chart_kind == "conductance_cut":
        audit_res = _get_or_run_audit(service, chain_id)
        if audit_res is None:
            return _unavailable(
                f"Không thể tải kết quả kiểm định cấu trúc Tier 2 cho chuỗi {chain_id}.",
                "TIER2_AUDIT_UNAVAILABLE",
            )
        structural = getattr(audit_res, "structural_audit", None)
        over_merge = getattr(audit_res, "over_merge", None)
        verdict = (
            getattr(structural.verdict, "value", str(structural.verdict))
            if structural
            else "UNAVAILABLE"
        )
        best_cut = getattr(structural, "best_cut", None)
        phi = (
            round(best_cut.conductance.phi, 4)
            if best_cut and getattr(best_cut, "conductance", None)
            else None
        )
        best_cut_label = (
            best_cut.candidate.label
            if best_cut and getattr(best_cut, "candidate", None)
            else "None"
        )
        part_a = list(best_cut.partition_a) if best_cut and getattr(best_cut, "partition_a", None) else []
        part_b = list(best_cut.partition_b) if best_cut and getattr(best_cut, "partition_b", None) else []
        over_strength = (
            getattr(over_merge.strength, "value", str(over_merge.strength))
            if over_merge
            else "NONE"
        )
        over_narrative = getattr(over_merge, "narrative", "") if over_merge else ""
        reason = getattr(structural, "reason", "") if structural else ""

        chart_data = {
            "chain_id": chain_id,
            "chart_type": "conductance_cut",
            "verdict": verdict,
            "conductance_phi": phi,
            "best_cut_label": best_cut_label,
            "over_merge_strength": over_strength,
            "partition_a_alarms": part_a,
            "partition_b_alarms": part_b,
            "reason": reason,
            "over_merge_narrative": over_narrative,
        }
        phi_str = f"{phi:.4f}" if phi is not None else "Không có lát cắt"
        message = (
            f"**Số liệu lát cắt Conductance Cut của chuỗi {chain_id}:**\n\n"
            f"- **Kết luận cấu trúc (Verdict):** `{verdict}`\n"
            f"- **Độ dẫn Best Cut (Conductance Φ):** `{phi_str}`\n"
            f"- **Nhãn lát cắt (Best Cut Label):** `{best_cut_label}`\n"
            f"- **Đánh giá Over-merge:** `{over_strength}`\n"
            f"- **Lý do / Diễn giải:** {over_narrative or reason}\n"
        )
        if part_a and part_b:
            message += (
                f"- **Phân hoạch A ({len(part_a)} cảnh báo):** `{part_a[:5]}`\n"
                f"- **Phân hoạch B ({len(part_b)} cảnh báo):** `{part_b[:5]}`\n"
            )

        return {
            "status": "AVAILABLE",
            "message": message,
            "chart_data": chart_data,
            "fact_refs": [
                f"chain:{chain_id}",
                "tier2:conductance_cut",
                "semantic-registry:conductance",
            ],
            "actions": [
                _navigation_action(
                    service,
                    label="Open Structural Audit",
                    tab="structure",
                    chain_id=chain_id,
                )
            ],
        }

    if chart_kind == "evolution_lineage":
        chart_data = {
            "chain_id": chain_id,
            "chart_type": "evolution_lineage",
            "status": "AVAILABLE",
        }
        return {
            "status": "AVAILABLE",
            "message": f"Biểu đồ tiến hóa (Evolution Lineage) hiển thị lịch sử biến động/sáp nhập chuỗi {chain_id} qua các mốc thời gian.",
            "chart_data": chart_data,
            "fact_refs": [f"chain:{chain_id}", "lineage:evolution"],
            "actions": [
                _navigation_action(
                    service,
                    label="Open Evolution",
                    tab="evolution",
                    chain_id=chain_id,
                )
            ],
        }

    # Default: attribution_deletion_curve
    audit_res = _get_or_run_audit(service, chain_id)
    if audit_res is None:
        return _unavailable(
            f"Không thể tải kết quả kiểm định Tier 2 cho chuỗi {chain_id}.",
            "TIER2_AUDIT_UNAVAILABLE",
        )
    attr_eval = getattr(audit_res, "evidence_attribution_evaluation", None)
    attr = getattr(audit_res, "evidence_attribution", None)

    eval_status = getattr(attr_eval, "status", None)
    eval_status_str = getattr(eval_status, "value", str(eval_status))
    if attr_eval is None or eval_status_str != "AVAILABLE":
        reason = getattr(attr_eval, "reason", "Chưa khả dụng") if attr_eval else "Chưa khả dụng"
        return _unavailable(
            f"Dữ liệu đường cong Deletion Curve chuỗi {chain_id} chưa khả dụng ({reason}).",
            "ATTRIBUTION_EVALUATION_UNAVAILABLE",
        )

    primary_auc = (
        round(attr_eval.primary.auc, 4) if attr_eval.primary.auc is not None else None
    )
    random_mean_auc = (
        round(attr_eval.random.mean_auc, 4)
        if attr_eval.random.mean_auc is not None
        else None
    )
    random_std_auc = (
        round(attr_eval.random.std_auc, 4)
        if attr_eval.random.std_auc is not None
        else None
    )
    reverse_auc = (
        round(attr_eval.reverse.auc, 4) if attr_eval.reverse.auc is not None else None
    )
    delta_vs_random_auc = (
        round(attr_eval.delta_vs_random_auc, 4)
        if attr_eval.delta_vs_random_auc is not None
        else None
    )
    delta_vs_reverse_auc = (
        round(attr_eval.delta_vs_reverse_auc, 4)
        if attr_eval.delta_vs_reverse_auc is not None
        else None
    )
    primary_curve = [round(v, 4) for v in attr_eval.primary.coverage_curve]
    reverse_curve = [round(v, 4) for v in attr_eval.reverse.coverage_curve]
    random_mean_curve = [round(v, 4) for v in attr_eval.random.mean_curve]

    drops = []
    curve = list(attr_eval.primary.coverage_curve)
    ordering = list(attr_eval.primary.ordering)
    for i in range(1, len(curve)):
        diff = curve[i - 1] - curve[i]
        if diff > 0.001:
            tag = ordering[i - 1] if i - 1 < len(ordering) else f"group_{i}"
            clean_tag = tag.split("|")[0] if "|" in tag else tag
            drops.append(
                f"Bước {i}: Loại bỏ bằng chứng '{clean_tag}', độ bao phủ giảm từ {curve[i-1]:.2f} xuống {curve[i]:.2f} (tụt {diff:.2f})"
            )

    top_contributions = []
    attr_status = getattr(attr, "status", None)
    attr_status_str = getattr(attr_status, "value", str(attr_status))
    if attr and attr_status_str == "AVAILABLE":
        for item in getattr(attr, "contributions", [])[:5]:
            top_contributions.append({
                "group": item.derivation_tag,
                "attribution": f"{item.attribution * 100:.1f}%",
                "supported_pairs": item.supported_pair_count,
            })

    chart_data = {
        "chain_id": chain_id,
        "chart_type": "attribution_deletion_curve",
        "status": "AVAILABLE",
        "primary_auc": primary_auc,
        "random_mean_auc": random_mean_auc,
        "reverse_auc": reverse_auc,
        "delta_vs_random_auc": delta_vs_random_auc,
        "delta_vs_reverse_auc": delta_vs_reverse_auc,
        "primary_curve": primary_curve,
        "drop_points": drops,
        "top_evidence_contributions": top_contributions,
    }

    drop_str = (
        "\n".join(f"- {d}" for d in drops)
        if drops
        else "- Độ bao phủ giảm đều hoặc không có bước tụt đột biến."
    )
    delta_str = (
        f"{delta_vs_random_auc:+.4f}" if delta_vs_random_auc is not None else "⊥"
    )
    message = (
        f"**Số liệu biểu đồ Deletion Curve của chuỗi {chain_id}:**\n\n"
        f"- **Primary AUC:** `{primary_auc}` (xóa theo thứ tự bằng chứng quan trọng nhất)\n"
        f"- **Random AUC:** `{random_mean_auc} ± {random_std_auc}` (baseline xóa ngẫu nhiên)\n"
        f"- **Reverse AUC:** `{reverse_auc}` (xóa bằng chứng yếu trước)\n"
        f"- **Chênh lệch Δ vs Random:** `{delta_str}`\n"
        f"- **Đường vẽ Primary (tọa độ):** `{primary_curve}`\n\n"
        f"**Các bước suy giảm then chốt trên đường cong:**\n{drop_str}"
    )

    return {
        "status": "AVAILABLE",
        "message": message,
        "chart_data": chart_data,
        "fact_refs": [
            f"chain:{chain_id}",
            "tier2:attribution_deletion_curve",
            "semantic-registry:conductance",
        ],
        "actions": [
            _navigation_action(
                service,
                label="Open Structural Audit",
                tab="structure",
                chain_id=chain_id,
            )
        ],
    }


def dispatch_assistant_tool(
    service: Any,
    tool_name: str,
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Execute a validated assistant tool call against the active snapshot."""
    if tool_name == "explain_metric":
        raw_metric = _normalize(str(arguments.get("metric_name", "")))
        metric_key = raw_metric
        if metric_key not in SEMANTIC_REGISTRY:
            for k in SEMANTIC_REGISTRY:
                if k in raw_metric or raw_metric in k:
                    metric_key = k
                    break
        if metric_key in SEMANTIC_REGISTRY:
            message, refs = _definition_response(metric_key)
            return {"status": "AVAILABLE", "message": message, "fact_refs": refs, "actions": []}
        return {
            "status": "AVAILABLE",
            "message": "Ask about conductance, membership support, Pair WHY, Counterfactual Review, or topology.",
            "fact_refs": [f"semantic-registry:{REGISTRY_VERSION}"],
            "actions": [],
        }

    if tool_name == "explain_root_cause_boundary":
        chain_id = _active_chain_id(service, context)
        actions = []
        pair = _active_pair(service, context)
        if pair is not None:
            pair_chain, alarm_a, alarm_b = pair
            actions.append(_navigation_action(
                service,
                label="Open Pair WHY",
                tab="why",
                chain_id=pair_chain,
                pair_alarm_id_a=alarm_a,
                pair_alarm_id_b=alarm_b,
            ))
        if chain_id is not None:
            actions.append(_navigation_action(
                service, label="Open Structural Audit", tab="structure", chain_id=chain_id
            ))
        return {
            "status": "AVAILABLE",
            "message": "The available evidence can explain grouping and structural findings, but it does not establish a root cause. Open Pair WHY or Structural Audit to inspect the recorded evidence.",
            "fact_refs": ["semantic-registry:pair_why", "semantic-registry:topology"],
            "actions": actions,
        }

    if tool_name == "report_resource_mapping_unavailable":
        return {
            "status": "UNAVAILABLE",
            "message": "Resource-to-chain search is unavailable in this context. Topology source navigation does not establish an alarm-to-resource mapping or dependency semantics.",
            "fact_refs": ["capability:RESOURCE_TO_CHAIN_MAPPING_UNAVAILABLE", "semantic-registry:topology"],
            "actions": [_navigation_action(service, label="Open Topology", tab="topology")],
        }

    if tool_name == "navigate_workspace":
        tab = arguments.get("tab", "structure")
        label = TAB_LABELS.get(tab, f"Open {tab.capitalize()}")
        if tab == "why":
            target_a = arguments.get("pair_alarm_id_a")
            target_b = arguments.get("pair_alarm_id_b")
            effective_context = {
                **context,
                **({"pair_alarm_id_a": target_a} if target_a else {}),
                **({"pair_alarm_id_b": target_b} if target_b else {}),
                **({"chain_id": arguments.get("chain_id")} if arguments.get("chain_id") else {}),
            }
            pair = _active_pair(service, effective_context)
            if pair is None:
                return _unavailable(
                    "Pair WHY requires two distinct alarms from the active chain.",
                    "PAIR_CONTEXT_UNAVAILABLE",
                )
            chain_id, alarm_a, alarm_b = pair
            action = _navigation_action(
                service,
                label=label,
                tab=tab,
                chain_id=chain_id,
                pair_alarm_id_a=alarm_a,
                pair_alarm_id_b=alarm_b,
            )
        elif tab in {"structure", "review", "evolution"}:
            target_chain = arguments.get("chain_id")
            effective_context = {
                **context,
                **({"chain_id": target_chain} if target_chain else {}),
            }
            chain_id = _active_chain_id(service, effective_context)
            if chain_id is None:
                return _unavailable(
                    f"{label} requires a chain from the active snapshot.",
                    "CHAIN_CONTEXT_UNAVAILABLE",
                )
            action = _navigation_action(service, label=label, tab=tab, chain_id=chain_id)
        else:
            action = _navigation_action(service, label=label, tab=tab)
        return {
            "status": "AVAILABLE",
            "message": f"I can open {label.lower()} for the active chain. This navigation does not run analysis or change data.",
            "fact_refs": [f"ui-context:{context.get('chain_id') or 'none'}"],
            "actions": [action],
        }

    if tool_name == "search_chains":
        query = arguments.get("query", "")
        matches = _find_chain_matches(service, query)
        if matches:
            actions = [
                _navigation_action(
                    service,
                    label=f"Open {chain.chain_id} ({chain.member_count} alarms)",
                    tab="tree",
                    chain_id=chain.chain_id,
                )
                for chain in matches
            ]
            return {
                "status": "AVAILABLE",
                "message": f"Found {len(matches)} matching chain(s) in the active snapshot. Select one to navigate.",
                "fact_refs": ["tool:search_chains", f"snapshot:{service.active_identity()[0]}:{service.active_identity()[1]}"],
                "actions": actions,
            }
        return {
            "status": "NO_FINDING",
            "message": "No deterministic match was found. Try a chain ID/title, or ask for a definition of conductance, membership support, Pair WHY, Counterfactual Review, or topology.",
            "fact_refs": [f"semantic-registry:{REGISTRY_VERSION}"],
            "actions": [],
        }

    if tool_name == "inspect_chart":
        target_chain = arguments.get("chain_id")
        effective_context = {
            **context,
            **({"chain_id": target_chain} if target_chain else {}),
        }
        chain_id = _active_chain_id(service, effective_context)
        if chain_id is None:
            return _unavailable(
                "Biểu đồ yêu cầu một chuỗi hợp lệ trong snapshot hiện tại.",
                "CHAIN_CONTEXT_UNAVAILABLE",
            )
        raw_type = str(arguments.get("chart_type", "attribution_deletion_curve")).casefold()
        if "conductance" in raw_type or "cut" in raw_type or "audit" in raw_type:
            chart_kind = "conductance_cut"
        elif "evolution" in raw_type or "timeline" in raw_type:
            chart_kind = "evolution_lineage"
        elif "review" in raw_type or "counterfactual" in raw_type:
            chart_kind = "counterfactual_review"
        else:
            chart_kind = "attribution_deletion_curve"

        return _handle_inspect_chart(service, chain_id, chart_kind, context)

    return {
        "status": "NO_FINDING",
        "message": f"Unknown tool call: {tool_name}",
        "fact_refs": [f"semantic-registry:{REGISTRY_VERSION}"],
        "actions": [],
    }


def _fallback_route(service: Any, text: str, context: dict[str, Any]) -> dict[str, Any]:
    """Lightweight fallback routing used when LLM provider is offline or not configured."""
    for metric_key in SEMANTIC_REGISTRY:
        if metric_key in text:
            return dispatch_assistant_tool(service, "explain_metric", {"metric_name": metric_key}, context)

    if "độ dẫn" in text:
        return dispatch_assistant_tool(service, "explain_metric", {"metric_name": "conductance"}, context)
    if "thành viên" in text or "membership" in text:
        return dispatch_assistant_tool(service, "explain_metric", {"metric_name": "membership_support"}, context)

    if "root cause" in text or "nguyên nhân gốc" in text or "rca" in text:
        return dispatch_assistant_tool(service, "explain_root_cause_boundary", {}, context)

    if "service" in text or "dịch vụ" in text or "resource" in text or "tài nguyên" in text:
        return dispatch_assistant_tool(service, "report_resource_mapping_unavailable", {}, context)

    # Chart inspection fallback
    if any(m in text for m in ("biểu đồ", "chart", "đường vẽ", "đồ thị", "deletion", "auc", "lát cắt", "độ dốc")):
        raw_chart = (
            "conductance_cut"
            if any(c in text for c in ("conductance", "độ dẫn", "lát cắt", "cut"))
            else "attribution_deletion_curve"
        )
        return dispatch_assistant_tool(
            service, "inspect_chart", {"chart_type": raw_chart}, context
        )

    # Tab navigation fallback
    for tab, tab_key in [("why", "why"), ("pair", "why"), ("audit", "structure"), ("structure", "structure"),
                         ("review", "review"), ("evolution", "evolution"), ("topology", "topology")]:
        if tab in text:
            return dispatch_assistant_tool(service, "navigate_workspace", {"tab": tab_key}, context)

    # Search chains fallback
    matches = _find_chain_matches(service, text)
    if matches:
        return dispatch_assistant_tool(service, "search_chains", {"query": text}, context)

    return {
        "status": "NO_FINDING",
        "message": "No deterministic match was found. Try a chain ID/title, or ask for a definition of conductance, membership support, Pair WHY, Counterfactual Review, or topology.",
        "fact_refs": [f"semantic-registry:{REGISTRY_VERSION}"],
        "actions": [],
    }


def answer_query(service: Any, query: str, context: dict[str, Any]) -> dict[str, Any]:
    """Produce a bounded, evidence-referenced assistant response using LLM tool calling or fallback."""
    if not _active_context_matches(service, context):
        return {
            "status": "STALE_CONTEXT",
            "message": "The selected snapshot changed. Refresh the workspace before using this assistant result.",
            "fact_refs": [],
            "actions": [],
        }

    text = _normalize(query)
    if not text:
        selected_metric = _normalize(str(context.get("selected_metric") or ""))
        if selected_metric in SEMANTIC_REGISTRY:
            message, refs = _definition_response(selected_metric)
            return {"status": "AVAILABLE", "message": message, "fact_refs": refs, "actions": []}
        return {
            "status": "AVAILABLE",
            "message": "Ask about a metric, search a chain ID/title, or open Pair WHY, Audit, Review, Evolution, or Topology for the selected chain.",
            "fact_refs": [f"semantic-registry:{REGISTRY_VERSION}"],
            "actions": [],
        }

    # If LLM is configured, invoke it with tools
    if is_provider_configured():
        system_prompt = (
            "You are the NocPro Assistant, a read-only investigation helper for alarm chains.\n"
            f"Active snapshot: {context.get('snapshot_id')} version {context.get('snapshot_version')}.\n"
            f"Selected chain: {context.get('chain_id') or 'none'}.\n"
            f"Selected pair: {context.get('pair_alarm_id_a') or 'none'}, {context.get('pair_alarm_id_b') or 'none'}.\n\n"
            "Select and call the appropriate tool when the user asks to explain a metric, inspect chart/curve numbers, navigate tabs, "
            "search for chains, or asks about root causes. If no tool applies, respond directly and factually in Vietnamese."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]
        llm_result = call_grounded_assistant(messages=messages, tools=ASSISTANT_TOOLS)
        if llm_result.used_provider and llm_result.tool_calls:
            call = llm_result.tool_calls[0]
            dispatched = dispatch_assistant_tool(
                service, call.name, call.arguments, context
            )
            # If the tool returned structured chart data, run a second turn so LLM explains the numbers and curves
            if call.name == "inspect_chart" and dispatched.get("chart_data"):
                chart_data = dispatched["chart_data"]
                second_turn_messages = [
                    *messages,
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": call.id or "call_inspect_chart",
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": call.arguments,
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": call.id or "call_inspect_chart",
                        "content": json.dumps(chart_data, ensure_ascii=False),
                    },
                ]
                explained_result = call_grounded_assistant(
                    messages=second_turn_messages, tools=None
                )
                if explained_result.used_provider and explained_result.content:
                    return {
                        **dispatched,
                        "message": explained_result.content,
                        "model": explained_result.model,
                        "provider_status": explained_result.provider_status,
                        "used_llm_tools": True,
                    }

            # For other tools or if 2nd turn fails, preserve dispatched message
            message = dispatched.get("message", "")
            if llm_result.content:
                message = f"{llm_result.content}\n\n{message}"
            return {
                **dispatched,
                "message": message,
                "model": llm_result.model,
                "provider_status": llm_result.provider_status,
                "used_llm_tools": True,
            }
        elif llm_result.used_provider and llm_result.content:
            return {
                "status": "AVAILABLE",
                "message": llm_result.content,
                "fact_refs": [f"semantic-registry:{REGISTRY_VERSION}"],
                "actions": [],
                "model": llm_result.model,
                "provider_status": llm_result.provider_status,
                "used_llm_tools": True,
            }

    # Fallback when LLM is not configured or fails
    return _fallback_route(service, text, context)


def render_answer(
    *,
    context: dict[str, Any],
    deterministic: dict[str, Any],
) -> dict[str, Any]:
    """Render only an Assistant message; preserve all deterministic controls."""
    if deterministic.get("status") == "STALE_CONTEXT":
        return {
            **deterministic,
            "model": "DETERMINISTIC_EVIDENCE",
            "provider_status": "NOT_APPLIED",
        }

    # If the LLM already executed via native tool calling, keep its result directly
    if deterministic.get("used_llm_tools") and deterministic.get("provider_status") == "OK":
        return {key: val for key, val in deterministic.items() if key != "used_llm_tools"}

    actions = deterministic.get("actions", [])
    action_facts = [
        {
            "kind": action.get("kind"),
            "label": action.get("label"),
            "target": action.get("target"),
        }
        for action in actions
        if isinstance(action, dict)
    ]
    fact_refs = [str(ref) for ref in deterministic.get("fact_refs", [])]
    rendered = render_grounded(
        draft=str(deterministic.get("message", "")),
        facts={
            "status": deterministic.get("status"),
            "fact_refs": fact_refs,
            "actions": action_facts,
            "active_context": {
                "snapshot_id": context.get("snapshot_id"),
                "snapshot_version": context.get("snapshot_version"),
                "chain_id": context.get("chain_id"),
                "pair_alarm_id_a": context.get("pair_alarm_id_a"),
                "pair_alarm_id_b": context.get("pair_alarm_id_b"),
            },
        },
        fact_refs=fact_refs,
        purpose="ASSISTANT",
    )
    return {
        **{k: v for k, v in deterministic.items() if k != "used_llm_tools"},
        "message": rendered.message,
        "model": rendered.model,
        "provider_status": rendered.provider_status,
    }
