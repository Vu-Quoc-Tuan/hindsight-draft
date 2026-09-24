"""Read-only NocPro Assistant with native LLM tool calling.

The assistant is a projection and navigation layer over the current workspace.
It uses native LLM tool selection to interpret user intent without brittle keyword
matching, while ensuring all tool executions and navigation targets remain strictly
bound and validated against the active snapshot.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .grounded_llm import (
    assistant_message_with_tool_calls,
    call_grounded_assistant,
    is_provider_configured,
    render_grounded,
    tool_result_message,
    validate_grounded_content,
)
from .assistant_knowledge import KnowledgeCatalog, knowledge_result_message

logger = logging.getLogger(__name__)

ProviderRunner = Callable[..., Awaitable[Any]]

REGISTRY_VERSION = "nocpro-assistant-registry-v1"

WORKSPACE_TABS = (
    "snapshots-overview",
    "snapshot-overview",
    "all-chains",
    "chain-overview",
    "why",
    "members",
    "structure",
    "review",
    "evolution",
    "topology",
    "validation",
)

# Provider models can retain vocabulary from an earlier UI contract even when
# the tool schema has been updated. These are explicit one-to-one aliases to
# current tabs, not query-driven navigation or a fallback answer path.
WORKSPACE_TAB_ALIASES = {
    "audit": "structure",
    "structural-audit": "structure",
    "counterfactual": "review",
    "recommendations": "review",
    "timeline": "evolution",
    "chains": "all-chains",
}

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
            "name": "search_project_knowledge",
            "description": "Tra kho kiến thức versioned của dự án để lấy thuật ngữ, công thức, ý nghĩa, điều kiện khả dụng và ranh giới diễn giải. Dùng cho mọi câu hỏi methodology hoặc metric.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Thuật ngữ, alias hoặc câu hỏi ngắn cần tra cứu."
                    },
                    "category": {"type": "string", "description": "Bộ lọc category tùy chọn."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_workspace",
            "description": "Tạo action điều hướng có kiểm tra snapshot tới một trang workspace. Có thể dùng chain/pair đang xem nếu người dùng nói 'chuỗi này' hoặc 'cặp này'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tab": {
                        "type": "string",
                        "enum": list(WORKSPACE_TABS),
                        "description": "Trang giao diện cần mở.",
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
            "name": "explain_capability_boundary",
            "description": "Đọc ranh giới của hệ thống về root cause, causal claim, synthetic/production validation, unavailable evidence hoặc thao tác ghi dữ liệu.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_mapping_capability",
            "description": "Kiểm tra capability mapping resource/service/topology trong context hiện tại. Không giả lập mapping nếu artifact không có.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_current_view",
            "description": "Đọc projection có cấu trúc của màn hình/selection hiện tại: snapshot, chain, member, pair, biểu đồ Audit/Review/Evolution. Dùng khi người dùng hỏi 'cái này', 'metric này' hoặc số đang thấy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": [
                            "current",
                            "snapshot",
                            "chain",
                            "member",
                            "pair",
                            "attribution_deletion_curve",
                            "conductance_cut",
                            "evolution_lineage",
                            "counterfactual_review",
                        ],
                        "description": "Projection cần đọc; current dùng page/selection trong context.",
                    },
                    "selected_metric": {"type": "string", "description": "Metric người dùng đang trỏ tới nếu biết."},
                    "chain_id": {
                        "type": "string",
                        "description": "ID chuỗi cảnh báo cần xem biểu đồ. Nếu bỏ trống sẽ lấy chuỗi đang chọn trong ngữ cảnh.",
                    },
                },
                "required": ["view"],
            },
        },
    },
]

TAB_LABELS: dict[str, str] = {
    "snapshots-overview": "Open Snapshots Portfolio",
    "snapshot-overview": "Open Snapshot Overview",
    "all-chains": "Open All Chains",
    "chain-overview": "Open Chain Overview",
    "why": "Open Pair WHY",
    "members": "Open Member Diagnostics",
    "structure": "Open Structural Audit",
    "review": "Open Counterfactual Review",
    "evolution": "Open Evolution",
    "topology": "Open Topology",
    "validation": "Open Validation",
}

TOOL_ALIASES = {
    "explain_metric": "search_project_knowledge",
    "explain_root_cause_boundary": "explain_capability_boundary",
    "report_resource_mapping_unavailable": "inspect_mapping_capability",
    "inspect_chart": "inspect_current_view",
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


def _get_persisted_audit(service: Any, chain_id: str) -> Any | None:
    package = service.require_package()
    if chain_id not in package.chains:
        return None
    job_view = service.jobs.latest_succeeded(
        package.snapshot.snapshot_id, package.snapshot.snapshot_version, chain_id
    )
    if job_view is not None and job_view.result is not None:
        return job_view.result

    return None


async def _handle_inspect_chart(
    service: Any,
    chain_id: str,
    chart_kind: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    if chart_kind == "conductance_cut":
        audit_res = _get_persisted_audit(service, chain_id)
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
        try:
            from .serializers import evolution_view

            evolution = evolution_view(await service.evolution(chain_id))
            chart_data = {
                "chart_type": "evolution_lineage",
                **evolution.model_dump(mode="json"),
            }
        except Exception:
            logger.exception("Could not load persisted Evolution artifact for chain=%s", chain_id)
            return _unavailable(
                f"Không thể tải Evolution artifact đã lưu của chuỗi {chain_id}.",
                "EVOLUTION_ARTIFACT_UNAVAILABLE",
            )

        if evolution.status != "AVAILABLE":
            reason = evolution.reason or "SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE"
            return {
                "status": "UNAVAILABLE",
                "message": (
                    f"Evolution của chuỗi {chain_id} chưa khả dụng ({reason}). "
                    "Hệ thống không dựng timeline khi chưa có verified sequential snapshots."
                ),
                "chart_data": chart_data,
                "fact_refs": [f"capability:{reason}"],
                "actions": [
                    _navigation_action(
                        service,
                        label="Open Evolution",
                        tab="evolution",
                        chain_id=chain_id,
                    )
                ],
            }

        return {
            "status": "AVAILABLE",
            "message": (
                f"Evolution artifact của chuỗi {chain_id} đã được xác minh và lưu bền vững: "
                f"{len(evolution.nodes)} node, {len(evolution.edges)} edge; "
                f"source_kind={evolution.source_kind}, "
                f"production_validation={evolution.production_validation}."
            ),
            "chart_data": chart_data,
            "fact_refs": [
                f"chain:{chain_id}",
                f"lineage:{evolution.lineage_component_id}",
            ],
            "actions": [
                _navigation_action(
                    service,
                    label="Open Evolution",
                    tab="evolution",
                    chain_id=chain_id,
                )
            ],
        }

    if chart_kind == "counterfactual_review":
        review_action = _navigation_action(
            service,
            label="Open Counterfactual Review",
            tab="review",
            chain_id=chain_id,
        )
        try:
            latest = await service.latest_review(chain_id)
        except Exception:
            logger.exception("Could not load persisted Review artifact for chain=%s", chain_id)
            return {
                **_unavailable(
                    f"Không thể tải Review artifact đã lưu của chuỗi {chain_id}.",
                    "REVIEW_ARTIFACT_NOT_AVAILABLE",
                ),
                "actions": [review_action],
            }

        if latest is None or getattr(latest, "result", None) is None:
            return {
                **_unavailable(
                    f"Chuỗi {chain_id} chưa có Counterfactual Review artifact tương thích.",
                    "REVIEW_ARTIFACT_NOT_AVAILABLE",
                ),
                "actions": [review_action],
            }

        from tier2.counterfactual.public_contract import public_review_result

        stored_result = latest.result
        review_result = (
            public_review_result(stored_result)
            if hasattr(stored_result, "recommendations")
            else dict(stored_result)
        )
        recommendations = list(review_result.get("recommendations") or [])
        evaluated = list(review_result.get("evaluated_candidates") or [])
        frontier = dict(review_result.get("frontier") or {})
        chart_data = {
            "chain_id": chain_id,
            "chart_type": "counterfactual_review",
            **review_result,
        }
        return {
            "status": "AVAILABLE",
            "message": (
                f"Counterfactual Review artifact của chuỗi {chain_id} có "
                f"{len(evaluated)} candidate đã đánh giá, "
                f"{len(recommendations)} recommendation và "
                f"{frontier.get('count_before_limit', 0)} candidate trên frontier trước limit. "
                "Đây là đề xuất để operator xem xét, không phải thay đổi tự động."
            ),
            "chart_data": chart_data,
            "fact_refs": [
                f"chain:{chain_id}",
                f"review-contract:{review_result.get('contract_version', 'unknown')}",
            ],
            "actions": [review_action],
        }

    # Default: attribution_deletion_curve
    audit_res = _get_persisted_audit(service, chain_id)
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
        "reverse_curve": reverse_curve,
        "random_mean_curve": random_mean_curve,
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


async def dispatch_assistant_tool(
    service: Any,
    tool_name: str,
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Execute a validated assistant tool call against the active snapshot."""
    requested_name = tool_name
    tool_name = TOOL_ALIASES.get(tool_name, tool_name)

    if tool_name == "search_project_knowledge":
        query = str(arguments.get("query") or arguments.get("metric_name") or "")
        entries = KnowledgeCatalog.load_default().search(
            query,
            category=str(arguments["category"]) if arguments.get("category") else None,
            limit=int(arguments.get("limit", 5)),
        )
        if entries:
            refs = [f"knowledge:{entry['id']}" for entry in entries]
            if requested_name == "explain_metric":
                legacy_key = _normalize(query)
                if legacy_key in SEMANTIC_REGISTRY:
                    refs.append(f"semantic-registry:{legacy_key}")
            return {
                "status": "AVAILABLE",
                "message": knowledge_result_message(entries),
                "data": {"catalog_version": "nocpro-assistant-knowledge-v1", "entries": entries},
                "fact_refs": refs,
                "actions": [],
            }
        # Preserve the old five-entry behavior for legacy callers during migration.
        raw_metric = _normalize(query)
        if requested_name == "explain_metric" and raw_metric in SEMANTIC_REGISTRY:
            message, refs = _definition_response(raw_metric)
            return {"status": "AVAILABLE", "message": message, "data": {}, "fact_refs": refs, "actions": []}
        return {
            "status": "NO_FINDING",
            "message": "Không tìm thấy thuật ngữ phù hợp trong kho kiến thức dự án.",
            "data": {"catalog_version": "nocpro-assistant-knowledge-v1", "entries": []},
            "fact_refs": ["knowledge:nocpro-assistant-knowledge-v1"],
            "actions": [],
        }

    if tool_name == "explain_capability_boundary":
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
            "data": {"boundary": KnowledgeCatalog.load_default().search("root cause", limit=1)[0]},
            "fact_refs": ["knowledge:boundary.root_cause"],
            "actions": actions,
        }

    if tool_name == "inspect_mapping_capability":
        return {
            "status": "UNAVAILABLE",
            "message": "Resource-to-chain search is unavailable in this context. Topology source navigation does not establish an alarm-to-resource mapping or dependency semantics.",
            "data": {"resource_mapping": "UNAVAILABLE", "reason": "RESOURCE_TO_CHAIN_MAPPING_UNAVAILABLE"},
            "fact_refs": ["capability:RESOURCE_TO_CHAIN_MAPPING_UNAVAILABLE", "semantic-registry:topology"],
            "actions": [_navigation_action(service, label="Open Topology", tab="topology")],
        }

    if tool_name == "navigate_workspace":
        requested_tab = str(arguments.get("tab", "structure")).strip().casefold()
        tab = WORKSPACE_TAB_ALIASES.get(requested_tab, requested_tab)
        if tab not in WORKSPACE_TABS:
            return _unavailable(
                f"Workspace tab {requested_tab!r} is not available in this UI version.",
                "UNSUPPORTED_WORKSPACE_TAB",
            )
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
                    tab="chain-overview",
                    chain_id=chain.chain_id,
                )
                for chain in matches
            ]
            return {
                "status": "AVAILABLE",
                "message": f"Found {len(matches)} matching chain(s) in the active snapshot. Select one to navigate.",
                "data": {"matches": [{"chain_id": chain.chain_id, "title": chain.auto_title, "member_count": chain.member_count} for chain in matches]},
                "fact_refs": ["tool:search_chains", f"snapshot:{service.active_identity()[0]}:{service.active_identity()[1]}"],
                "actions": actions,
            }
        return {
            "status": "NO_FINDING",
            "message": "No deterministic match was found. Try a chain ID/title, or ask for a definition of conductance, membership support, Pair WHY, Counterfactual Review, or topology.",
            "data": {"matches": []},
            "fact_refs": [f"semantic-registry:{REGISTRY_VERSION}"],
            "actions": [],
        }

    if tool_name == "inspect_current_view":
        target_chain = arguments.get("chain_id")
        effective_context = {
            **context,
            **({"chain_id": target_chain} if target_chain else {}),
        }
        raw_type = str(arguments.get("view") or arguments.get("chart_type") or context.get("page") or "current").casefold()
        if raw_type == "current":
            raw_type = str(context.get("page") or "chain").casefold()
        package = service.require_package()
        if raw_type in {"snapshot", "snapshots-overview", "snapshot-overview", "all-chains"}:
            listed = service.list_chains()
            data = {
                "view": raw_type,
                "snapshot_id": package.snapshot.snapshot_id,
                "snapshot_version": package.snapshot.snapshot_version,
                "chain_count": len(listed.chains),
                "chains": [
                    {"chain_id": chain.chain_id, "title": chain.auto_title, "member_count": chain.member_count}
                    for chain in sorted(listed.chains.values(), key=lambda item: item.chain_id)[:20]
                ],
            }
            return {
                "status": "AVAILABLE",
                "message": f"Snapshot hiện tại có {len(listed.chains)} chuỗi; projection trả tối đa 20 chuỗi.",
                "data": data,
                "fact_refs": [f"snapshot:{package.snapshot.snapshot_id}:{package.snapshot.snapshot_version}"],
                "actions": [],
            }
        chain_id = _active_chain_id(service, effective_context)
        if chain_id is None:
            return _unavailable(
                "Màn hình này yêu cầu một chuỗi hợp lệ trong snapshot hiện tại.",
                "CHAIN_CONTEXT_UNAVAILABLE",
            )
        selection = context.get("selection") if isinstance(context.get("selection"), dict) else {}
        selected_metric = str(arguments.get("selected_metric") or context.get("selected_metric") or selection.get("metric_id") or "").strip()
        if raw_type in {"current", "chain", "member", "pair", "snapshot", "chain-overview", "members", "why"}:
            chain = package.chains[chain_id]
            members = list(package.members_of(chain_id))
            data = {
                "view": raw_type,
                "page": context.get("page"),
                "snapshot_id": package.snapshot.snapshot_id,
                "snapshot_version": package.snapshot.snapshot_version,
                "chain_id": chain_id,
                "chain_title": getattr(chain, "auto_title", None),
                "member_count": len(members),
                "members": members[:20],
                "selected_metric": selected_metric or None,
                "alarm_id": context.get("alarm_id"),
                "pair_alarm_id_a": context.get("pair_alarm_id_a"),
                "pair_alarm_id_b": context.get("pair_alarm_id_b"),
            }
            if selected_metric:
                data["knowledge"] = KnowledgeCatalog.load_default().search(selected_metric, limit=1)
            return {
                "status": "AVAILABLE",
                "message": f"Đang xem chuỗi {chain_id} với {len(members)} cảnh báo. Dữ liệu selection đã được kiểm tra lại theo snapshot hiện hành.",
                "data": data,
                "fact_refs": [f"snapshot:{package.snapshot.snapshot_id}:{package.snapshot.snapshot_version}", f"chain:{chain_id}"],
                "actions": [],
            }
        if "conductance" in raw_type or "cut" in raw_type or "audit" in raw_type:
            chart_kind = "conductance_cut"
        elif "evolution" in raw_type or "timeline" in raw_type:
            chart_kind = "evolution_lineage"
        elif "review" in raw_type or "counterfactual" in raw_type:
            chart_kind = "counterfactual_review"
        else:
            chart_kind = "attribution_deletion_curve"

        result = await _handle_inspect_chart(service, chain_id, chart_kind, context)
        if "data" not in result:
            result["data"] = result.get("chart_data") or {}
        return result

    return {
        "status": "NO_FINDING",
        "message": f"Unknown tool call: {tool_name}",
        "fact_refs": [f"semantic-registry:{REGISTRY_VERSION}"],
        "actions": [],
    }


async def answer_query(
    service: Any,
    query: str,
    context: dict[str, Any],
    *,
    history: list[dict[str, str]] | None = None,
    provider_runner: ProviderRunner | None = None,
) -> dict[str, Any]:
    """Run a bounded LLM/tool loop without fabricating an AI narrative.

    Deterministic tools may still supply verified navigation actions and fact
    references, but provider failure is surfaced as an empty AI message rather
    than a canned deterministic paragraph.
    """
    def provider_unavailable_result(
        result: dict[str, Any], reason: str, used_tools: list[str] | None = None
    ) -> dict[str, Any]:
        return {
            **result,
            "message": "",
            "model": os.environ.get("AI_MODEL", "").strip(),
            "provider_status": reason,
            "response_mode": "PROVIDER_UNAVAILABLE",
            "tools_used": used_tools or [],
        }

    if not _active_context_matches(service, context):
        return provider_unavailable_result({
            "status": "STALE_CONTEXT",
            "fact_refs": [],
            "actions": [],
        }, "STALE_CONTEXT")

    text = _normalize(query)
    if not text:
        selected_metric = _normalize(str(context.get("selected_metric") or ""))
        if selected_metric in SEMANTIC_REGISTRY:
            _, refs = _definition_response(selected_metric)
            return provider_unavailable_result(
                {"status": "AVAILABLE", "fact_refs": refs, "actions": []},
                "EMPTY_QUERY",
            )
        return provider_unavailable_result(
            {
                "status": "NO_FINDING",
                "fact_refs": [f"semantic-registry:{REGISTRY_VERSION}"],
                "actions": [],
            },
            "EMPTY_QUERY",
        )

    # If LLM is configured, invoke it with tools
    if is_provider_configured():
        system_prompt = (
            "You are the NocPro Assistant, a read-only investigation helper for alarm chains.\n"
            f"Active snapshot: {context.get('snapshot_id')} version {context.get('snapshot_version')}.\n"
            f"Selected chain: {context.get('chain_id') or 'none'}.\n"
            f"Selected pair: {context.get('pair_alarm_id_a') or 'none'}, {context.get('pair_alarm_id_b') or 'none'}.\n\n"
            f"Current page: {context.get('page') or 'unknown'}; selected metric: {context.get('selected_metric') or 'none'}.\n\n"
            "You are in a bounded agent loop. Select and call one or more appropriate read-only tools when the user asks to explain a metric, inspect current screen/chart/curve numbers, "
            "navigate tabs, search for chains, or asks about root causes. For any factual claim about the active snapshot, chain, "
            "alarms, roles, Audit, Review, Evolution, topology, chart, or metric, you must call a read-only tool before making factual claims. "
            "Do not invent or infer chain-specific facts, counts, scores, statuses, recommendations, or causal conclusions without tool data. "
            "If no tool can verify a requested repository fact, say that it cannot be verified from the available read-only tools. "
            "All user-facing prose must be written in Vietnamese. Keep alarm names, device IDs, IP addresses, interface names, "
            "component names, and other technical identifiers exactly as supplied, even when those literals are English. "
            "You may answer general conceptual or conversational questions directly in Vietnamese when they do not assert repository-specific facts."
        )
        bounded_history_reversed: list[dict[str, str]] = []
        history_chars = 0
        for item in reversed((history or [])[-8:]):
            if item.get("role") not in {"user", "assistant"} or not item.get("content"):
                continue
            content = item["content"][:2000]
            remaining = 8000 - history_chars
            if remaining <= 0:
                break
            content = content[-remaining:]
            bounded_history_reversed.append({"role": item["role"], "content": content})
            history_chars += len(content)
        bounded_history = list(reversed(bounded_history_reversed))
        messages = [{"role": "system", "content": system_prompt}, *bounded_history, {"role": "user", "content": query}]
        authoritative: dict[str, Any] = {"status": "AVAILABLE", "fact_refs": [], "actions": []}
        deterministic_messages: list[str] = []
        tool_payloads: list[dict[str, Any]] = []
        tools_used: list[str] = []
        total_tool_calls = 0

        async def run_provider() -> Any:
            if provider_runner is None:
                return call_grounded_assistant(messages=messages, tools=ASSISTANT_TOOLS)
            return await provider_runner(call_grounded_assistant, messages=messages, tools=ASSISTANT_TOOLS)

        async def provider_unavailable_after_tools(reason: str) -> dict[str, Any]:
            if deterministic_messages:
                return provider_unavailable_result({**authoritative, "message": ""}, reason, tools_used)
            return provider_unavailable_result(
                {"status": "NO_FINDING", "fact_refs": [], "actions": []},
                reason,
                tools_used,
            )

        for _round in range(3):
            llm_result = await run_provider()
            if not llm_result.used_provider:
                return await provider_unavailable_after_tools(llm_result.provider_status)
            if llm_result.tool_calls:
                if total_tool_calls + len(llm_result.tool_calls) > 4:
                    return await provider_unavailable_after_tools("TOOL_LOOP_LIMIT")
                messages.append(assistant_message_with_tool_calls(llm_result))
                for index, call in enumerate(llm_result.tool_calls):
                    if not _active_context_matches(service, context):
                        return provider_unavailable_result({"status": "STALE_CONTEXT", "fact_refs": [], "actions": []}, "STALE_CONTEXT")
                    dispatched = await dispatch_assistant_tool(service, call.name, call.arguments, context)
                    tool_payloads.append(dispatched)
                    total_tool_calls += 1
                    canonical_name = TOOL_ALIASES.get(call.name, call.name)
                    tools_used.append(canonical_name)
                    deterministic_messages.append(str(dispatched.get("message", "")))
                    for ref in dispatched.get("fact_refs", []):
                        if ref not in authoritative["fact_refs"]:
                            authoritative["fact_refs"].append(ref)
                    existing_actions = {
                        repr((action.get("kind"), action.get("target")))
                        for action in authoritative["actions"]
                        if isinstance(action, dict)
                    }
                    for action in dispatched.get("actions", []):
                        key = repr((action.get("kind"), action.get("target")))
                        if key not in existing_actions:
                            authoritative["actions"].append(action)
                            existing_actions.add(key)
                    status_priority = {"AVAILABLE": 0, "NO_FINDING": 1, "UNAVAILABLE": 2, "STALE_CONTEXT": 3}
                    dispatched_status = str(dispatched.get("status", "AVAILABLE"))
                    if status_priority.get(dispatched_status, 1) > status_priority.get(str(authoritative["status"]), 0):
                        authoritative["status"] = dispatched_status
                    if dispatched.get("chart_data") is not None:
                        authoritative["chart_data"] = dispatched["chart_data"]
                    call_id = call.id or f"call_{index}_{call.name}"
                    messages.append(tool_result_message(call_id, call.name, dispatched))
                continue
            if llm_result.content:
                draft = "\n\n".join(deterministic_messages) or query
                validated = validate_grounded_content(
                    content=llm_result.content,
                    draft=draft,
                    facts={"tool_results": tool_payloads, "context": context},
                    fact_refs=[str(ref) for ref in authoritative["fact_refs"]],
                    model=llm_result.model,
                    provider_status=llm_result.provider_status,
                    preserve_provider_output=True,
                )
                if validated.used_provider:
                    return {
                        **authoritative,
                        "message": validated.message,
                        "model": validated.model,
                        "provider_status": validated.provider_status,
                        "response_mode": "LLM_PRIMARY",
                        "tools_used": tools_used,
                    }
                return await provider_unavailable_after_tools(validated.provider_status)
        return await provider_unavailable_after_tools("TOOL_LOOP_LIMIT")

    # Provider unavailable: do not infer intent from keywords or fabricate a
    # navigation/chart result.  Tool selection belongs to the configured
    # provider; a missing provider is an explicit unavailable state.
    return provider_unavailable_result(
        {"status": "NO_FINDING", "fact_refs": [], "actions": []},
        "NOT_CONFIGURED",
    )


def render_answer(
    *,
    context: dict[str, Any],
    deterministic: dict[str, Any],
) -> dict[str, Any]:
    """Render only an Assistant message; preserve all deterministic controls."""
    if deterministic.get("status") == "STALE_CONTEXT":
        return {
            **deterministic,
            "model": "",
            "provider_status": "STALE_CONTEXT",
            "response_mode": "PROVIDER_UNAVAILABLE",
            "tools_used": [],
        }
    if deterministic.get("response_mode"):
        return {key: value for key, value in deterministic.items() if key != "data"}

    # Native tool-calling output has already been grounded or marked
    # unavailable. Never invoke a third provider pass here.
    if deterministic.get("used_llm_tools"):
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
        requested_language="vi",
        preserve_provider_output=True,
    )
    return {
        **{k: v for k, v in deterministic.items() if k != "used_llm_tools"},
        "message": rendered.message,
        "model": rendered.model,
        "provider_status": rendered.provider_status,
    }
