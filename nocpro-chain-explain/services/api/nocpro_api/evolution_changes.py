"""Pure, evidence-bound facts for one already selected lineage transition.

The caller supplies a verified edge and canonical member IDs. This module never
selects predecessors, fetches receipts, or infers physical topology changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any


def _get(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and bool(value.strip()) else None


def _instant(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _members(value: Any) -> set[str] | None:
    if value is None or isinstance(value, (str, bytes, dict)):
        return None
    try:
        members = set(value)
    except (TypeError, ValueError):
        return None
    if any(_text(member) is None for member in members):
        return None
    return members


def _identity(receipt: Any) -> Any:
    return _get(receipt, "analysis_identity")


def _receipt_matches(receipt: Any, key: dict[str, str]) -> bool:
    identity = _identity(receipt)
    return identity is not None and all(_get(identity, name) == value for name, value in key.items())


def _score(assessment: Any) -> float | None:
    value = _get(assessment, "score")
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        return None
    return value


def compare_evolution_facts(
    *, parent_members, child_members, parent_receipt, child_receipt, lineage_edge
) -> dict:
    """Compare one supplied edge; unavailable inputs never become empty evidence."""
    reasons: list[str] = []
    parent = {name: _text(_get(lineage_edge, f"parent_{name}")) for name in ("snapshot_id", "snapshot_version", "chain_id")}
    child = {name: _text(_get(lineage_edge, f"child_{name}")) for name in ("snapshot_id", "snapshot_version", "chain_id")}
    event_type = _text(_get(lineage_edge, "event_type")) or _text(_get(lineage_edge, "edge_type"))
    edge_valid = all(parent.values()) and all(child.values()) and event_type is not None and parent != child
    if not edge_valid:
        reasons.append("LINEAGE_EDGE_UNAVAILABLE")

    parent_time = _instant(_get(lineage_edge, "parent_snapshot_time"))
    child_time = _instant(_get(lineage_edge, "child_snapshot_time"))
    if parent_time is None or child_time is None:
        reasons.append("SNAPSHOT_TIME_UNAVAILABLE")
    elif child_time < parent_time:
        reasons.append("SNAPSHOT_TIME_OUT_OF_ORDER")

    before = _members(parent_members)
    after = _members(child_members)
    membership = None
    if not edge_valid or before is None or after is None:
        reasons.append("CANONICAL_MEMBERSHIP_UNAVAILABLE")
    else:
        retained = before & after
        overlap = _get(lineage_edge, "overlap_count")
        if overlap is not None and (type(overlap) is not int or overlap != len(retained)):
            reasons.append("LINEAGE_OVERLAP_MISMATCH")
        else:
            added, removed = sorted(after - before), sorted(before - after)
            membership = {
                "added_count": len(added), "removed_count": len(removed),
                "retained_count": len(retained), "added_alarm_ids": added[:100],
                "removed_alarm_ids": removed[:100],
                "truncated": len(added) > 100 or len(removed) > 100,
            }

    context_changes = []
    for field, parent_field, child_field in (
        ("topology_version", "topology_version", "topology_version"),
        ("analysis_config_version", "analysis_config_version", "analysis_config_version"),
        ("review_config_version", "review_config_version", "review_config_version"),
        ("pipeline_version", "pipeline_version", "pipeline_version"),
    ):
        left = _text(_get(_identity(parent_receipt), parent_field))
        right = _text(_get(_identity(child_receipt), child_field))
        if left is not None and right is not None and left != right:
            context_changes.append({"field": field, "before": left, "after": right})
    left_kind = _text(_get(lineage_edge, "parent_source_kind"))
    right_kind = _text(_get(lineage_edge, "child_source_kind"))
    if left_kind is not None and right_kind is not None and left_kind != right_kind:
        context_changes.append({"field": "source_kind", "before": left_kind, "after": right_kind})

    before_assessment = _get(parent_receipt, "assessment")
    after_assessment = _get(child_receipt, "assessment")
    before_score, after_score = _score(before_assessment), _score(after_assessment)
    quality_reasons: list[str] = []
    if parent_receipt is None or child_receipt is None:
        quality_reasons.append("QUALITY_RECEIPT_UNAVAILABLE")
    if not edge_valid or (parent_receipt is not None and not _receipt_matches(parent_receipt, parent)) or (child_receipt is not None and not _receipt_matches(child_receipt, child)):
        quality_reasons.append("RECEIPT_IDENTITY_MISMATCH")
    for assessment in (before_assessment, after_assessment):
        if _get(assessment, "status") != "EVALUATED" or _get(assessment, "readiness") != "READY":
            if "QUALITY_NOT_READY" not in quality_reasons:
                quality_reasons.append("QUALITY_NOT_READY")
    if before_score is None or after_score is None:
        quality_reasons.append("PRECISE_SCORE_UNAVAILABLE")
    for field, reason in (
        ("method", "QUALITY_METHOD_MISMATCH"),
        ("readiness_policy_version", "READINESS_POLICY_MISMATCH"),
    ):
        left = _text(_get(before_assessment, field))
        right = _text(_get(after_assessment, field))
        if left is None or right is None or left != right:
            quality_reasons.append(reason)
    for field, reason in (
        ("analysis_config_version", "ANALYSIS_CONFIG_MISMATCH"),
        ("review_config_version", "REVIEW_CONFIG_MISMATCH"),
        ("pipeline_version", "PIPELINE_MISMATCH"),
        ("topology_version", "TOPOLOGY_VERSION_MISMATCH"),
    ):
        left = _text(_get(_identity(parent_receipt), field))
        right = _text(_get(_identity(child_receipt), field))
        if left is None or right is None or left != right:
            quality_reasons.append(reason)
    comparable = not quality_reasons
    quality = {
        "comparable": comparable, "reason_codes": quality_reasons,
        "before_score": before_score, "after_score": after_score,
        "before_stars": _get(before_assessment, "stars"),
        "after_stars": _get(after_assessment, "stars"),
        "delta": after_score - before_score if comparable else None,
        "before_receipt_id": _text(_get(parent_receipt, "receipt_id")),
        "after_receipt_id": _text(_get(child_receipt, "receipt_id")),
    }

    explanations = []
    if membership is not None:
        if membership["added_count"]:
            explanations.append({"code": "MEMBERS_ENTERED_CHAIN", "text": f'{membership["added_count"]} alarm entered the child chain.', "evidence_ids": membership["added_alarm_ids"]})
        if membership["removed_count"]:
            explanations.append({"code": "MEMBERS_LEFT_CHAIN", "text": f'{membership["removed_count"]} alarm left the parent chain.', "evidence_ids": membership["removed_alarm_ids"]})
    if context_changes:
        explanations.append({"code": "CONTEXT_CHANGED", "text": "Comparison context changed: " + ", ".join(item["field"] for item in context_changes) + ".", "evidence_ids": []})
    if not comparable:
        explanations.append({"code": "QUALITY_NOT_COMPARABLE", "text": "The two quality scores are not directly comparable under the available assessment evidence.", "evidence_ids": [value for value in (quality["before_receipt_id"], quality["after_receipt_id"]) if value]})
    if "SNAPSHOT_TIME_OUT_OF_ORDER" in reasons:
        explanations.append({"code": "TIME_ORDER_UNAVAILABLE", "text": "The supplied snapshot times do not establish forward time order.", "evidence_ids": []})
    status = "UNAVAILABLE" if not edge_valid or (membership is None and parent_receipt is None and child_receipt is None) else "PARTIAL" if reasons or quality_reasons else "AVAILABLE"
    return {
        "status": status, "reason_codes": reasons,
        "parent": parent, "child": child, "event_type": event_type,
        "membership": membership, "context_changes": context_changes,
        "quality": quality, "explanations": explanations,
    }
