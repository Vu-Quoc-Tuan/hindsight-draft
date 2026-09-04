"""Deterministic, evidence-bound narrative for a chain analysis.

ADR-0024 allows a language model to render structured evidence, but the
operator-facing response itself must never acquire facts that the analysis did
not produce. Until an independently validated constrained renderer exists,
this module deliberately uses deterministic text only. It is therefore safe
to call from a GET endpoint and needs no provider credential.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AISuggestionResult:
    chain_id: str
    status: str
    model: str
    narrative: str
    grounded_claims: list[str]
    disclaimer: str
    provider_status: str | None = None

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


def _recommendation_facts(review_result: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(review_result, dict):
        return []
    evaluated = {
        str(candidate.get("candidate_id")): candidate
        for candidate in review_result.get("evaluated_candidates", [])
        if isinstance(candidate, dict) and candidate.get("candidate_id")
    }
    facts: list[dict[str, str]] = []
    for reference in review_result.get("recommendations", []):
        if not isinstance(reference, dict):
            continue
        candidate_id = reference.get("candidate_id")
        candidate = evaluated.get(str(candidate_id))
        operation = candidate.get("operation") if candidate else reference.get("operation")
        if candidate_id and operation:
            facts.append({"candidate_id": str(candidate_id), "operation": str(operation)})
    return facts


def extract_grounded_claims(
    chain_id: str,
    analysis: Any,
    review_result: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Project only facts directly produced by Tier-1B and Review v1."""
    members = _member_facts(analysis)
    descriptors = _descriptor_facts(analysis)
    proposals = _recommendation_facts(review_result)

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

    structured = {
        "chain_id": chain_id,
        "member_count": len(members),
        "role_counts": role_counts,
        "weak_members": weak_members,
        "insufficient_members": insufficient_members,
        "descriptors": descriptors,
        "proposals": proposals,
    }
    return structured, claims


def build_deterministic_narrative(
    chain_id: str,
    structured_data: dict[str, Any],
) -> str:
    """Render the grounded projection without causal or topology claims."""
    lines = [
        f"### Evidence summary for chain {chain_id}",
        f"- Analyzed members: **{structured_data['member_count']}**.",
    ]
    weak_members = structured_data["weak_members"]
    insufficient_members = structured_data["insufficient_members"]
    descriptors = structured_data["descriptors"]
    proposals = structured_data["proposals"]

    if weak_members:
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
    if proposals:
        for proposal in proposals:
            lines.append(
                f"- {proposal['operation']} ({proposal['candidate_id']}) "
                "is an operator-facing bounded recommendation."
            )
    else:
        lines.append("- No operator-facing counterfactual recommendation is available.")

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
) -> AISuggestionResult:
    """Return an evidence-bound summary with no external model invocation."""
    structured, claims = extract_grounded_claims(chain_id, analysis, review_result)
    return AISuggestionResult(
        chain_id=chain_id,
        status="AVAILABLE",
        model="DETERMINISTIC_EVIDENCE",
        narrative=build_deterministic_narrative(chain_id, structured),
        grounded_claims=claims,
        disclaimer=(
            "ADR-0024: this response renders deterministic evidence only; it "
            "does not create evidence, infer causality, or change NocPro."
        ),
        provider_status="NOT_USED",
    )
