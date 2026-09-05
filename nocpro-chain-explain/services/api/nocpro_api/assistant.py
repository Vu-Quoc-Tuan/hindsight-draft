"""Deterministic, read-only NocPro Assistant.

The assistant is a projection and navigation layer over the current workspace.
It deliberately does not invoke an LLM, mutate analysis state, submit jobs, or
manufacture operational conclusions.  Every action is a typed in-app target.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


def answer_query(service: Any, query: str, context: dict[str, Any]) -> dict[str, Any]:
    """Produce a bounded, evidence-referenced assistant response.

    The intent vocabulary is intentionally small. Unknown language gets a
    transparent help response instead of an invented finding.
    """
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

    for key, phrases in {
        "conductance": ("conductance", "độ dẫn"),
        "membership_support": ("membership support", "membership", "hỗ trợ thành viên"),
        "pair_why": ("pair why", "why grouped", "tại sao gộp"),
        "counterfactual_review": ("counterfactual", "review", "khuyến nghị"),
        "topology": ("topology", "topo", "cấu trúc mạng"),
    }.items():
        if any(phrase in text for phrase in phrases) and any(
            marker in text for marker in ("là gì", "nghĩa", "how", "what", "giải thích", "explain")
        ):
            message, refs = _definition_response(key)
            return {"status": "AVAILABLE", "message": message, "fact_refs": refs, "actions": []}

    if any(phrase in text for phrase in ("root cause", "nguyên nhân gốc", "rca")):
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

    if any(phrase in text for phrase in ("service", "dịch vụ", "resource", "tài nguyên")):
        return {
            "status": "UNAVAILABLE",
            "message": "Resource-to-chain search is unavailable in this context. Topology source navigation does not establish an alarm-to-resource mapping or dependency semantics.",
            "fact_refs": ["capability:RESOURCE_TO_CHAIN_MAPPING_UNAVAILABLE", "semantic-registry:topology"],
            "actions": [_navigation_action(service, label="Open Topology", tab="topology")],
        }

    tab_by_phrase = {
        "pair why": ("why", "Open Pair WHY"),
        "audit": ("structure", "Open Structural Audit"),
        "review": ("review", "Open Counterfactual Review"),
        "evolution": ("evolution", "Open Evolution"),
        "topology": ("topology", "Open Topology"),
    }
    for phrase, (tab, label) in tab_by_phrase.items():
        if phrase in text and any(marker in text for marker in ("open", "mở", "go", "đến")):
            if tab == "why":
                pair = _active_pair(service, context)
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
                chain_id = _active_chain_id(service, context)
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
