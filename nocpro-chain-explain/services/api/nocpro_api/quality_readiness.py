"""Fail-closed evidence readiness gate for deterministic chain quality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ReadinessStatus = Literal["READY", "PARTIAL", "INSUFFICIENT", "NOT_APPLICABLE"]


@dataclass(frozen=True)
class QualityReadiness:
    status: ReadinessStatus
    observed_families: tuple[str, ...]
    complete_families: tuple[str, ...]
    missing_reasons: tuple[str, ...]
    evaluated_pair_count: int
    eligible_pair_count: int


def quality_assessment_contract_is_valid(value: object) -> bool:
    """Fail closed when persisted status, readiness, and public stars disagree."""
    if not isinstance(value, dict):
        return False
    status = str(value.get("status") or "").upper()
    readiness = str(value.get("readiness") or "").upper()
    stars = value.get("stars")
    if (
        value.get("readiness_policy_version") != "quality-readiness-v1"
        or not isinstance(value.get("reason_codes"), list)
        or not all(isinstance(code, str) for code in value["reason_codes"])
        or not isinstance(value.get("evidence_coverage"), dict)
    ):
        return False
    if status == "EVALUATED":
        return readiness == "READY" and type(stars) is int and 1 <= stars <= 5
    if status == "UNAVAILABLE":
        return readiness in {"PARTIAL", "INSUFFICIENT"} and stars is None
    if status == "NOT_APPLICABLE":
        return readiness == "NOT_APPLICABLE" and stars is None
    return False


def _count(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def evaluate_quality_readiness(
    *,
    alarm_count: int,
    evaluated_members: int,
    topology_status: str,
    mapped_alarm_count: int,
    evaluated_pair_count: int,
    eligible_pair_count: int,
    mapped_device_count: int,
    total_device_count: int,
    audit_status: str,
    audit_complete: bool,
    review_status: str,
) -> QualityReadiness:
    """Decide whether public stars are defensible from independent evidence.

    The topology family is independent only when source input is complete, each
    relevant alarm/device maps, and every eligible mapped-resource pair was
    evaluated under the bounded path policy. A measured zero connected-pair
    count is still an evaluated result; inputs are evaluated/eligible counts,
    not just positive paths.
    """
    counts = {
        "alarm_count": _count("alarm_count", alarm_count),
        "evaluated_members": _count("evaluated_members", evaluated_members),
        "mapped_alarm_count": _count("mapped_alarm_count", mapped_alarm_count),
        "evaluated_pair_count": _count("evaluated_pair_count", evaluated_pair_count),
        "eligible_pair_count": _count("eligible_pair_count", eligible_pair_count),
        "mapped_device_count": _count("mapped_device_count", mapped_device_count),
        "total_device_count": _count("total_device_count", total_device_count),
    }
    if counts["evaluated_members"] > counts["alarm_count"]:
        raise ValueError("evaluated_members cannot exceed alarm_count")
    if counts["mapped_alarm_count"] > counts["alarm_count"]:
        raise ValueError("mapped_alarm_count cannot exceed alarm_count")
    if counts["evaluated_pair_count"] > counts["eligible_pair_count"]:
        raise ValueError("evaluated_pair_count cannot exceed eligible_pair_count")
    if counts["mapped_device_count"] > counts["total_device_count"]:
        raise ValueError("mapped_device_count cannot exceed total_device_count")
    if not isinstance(audit_complete, bool):
        raise ValueError("audit_complete must be a boolean")

    topology = str(topology_status or "").upper()
    audit = str(audit_status or "").upper()
    review = str(review_status or "").upper()
    if topology not in {"AVAILABLE", "PARTIAL", "UNAVAILABLE", "NOT_APPLICABLE"}:
        raise ValueError("topology_status is not a supported readiness state")
    if audit not in {"EVALUATED", "PARTIAL", "UNAVAILABLE", "NOT_EVALUATED", "NOT_APPLICABLE"}:
        raise ValueError("audit_status is not a supported readiness state")
    if review not in {"COMPLETED", "UNAVAILABLE", "NOT_EVALUATED"}:
        raise ValueError("review_status is not a supported readiness state")
    if audit_complete and audit != "EVALUATED":
        raise ValueError("audit_complete requires audit_status=EVALUATED")

    if counts["alarm_count"] <= 1:
        return QualityReadiness(
            status="NOT_APPLICABLE",
            observed_families=(),
            complete_families=(),
            missing_reasons=("SINGLETON_CHAIN",),
            evaluated_pair_count=counts["evaluated_pair_count"],
            eligible_pair_count=counts["eligible_pair_count"],
        )

    role_coverage = counts["evaluated_members"] / counts["alarm_count"]
    observed_families: list[str] = []
    if counts["evaluated_members"] > 0:
        observed_families.append("membership")

    mapping_complete = (
        counts["mapped_alarm_count"] == counts["alarm_count"]
        and counts["total_device_count"] > 0
        and counts["mapped_device_count"] == counts["total_device_count"]
    )
    pair_coverage_complete = (
        counts["eligible_pair_count"] > 0
        and counts["evaluated_pair_count"] == counts["eligible_pair_count"]
    )
    topology_complete = (
        topology == "AVAILABLE" and mapping_complete and pair_coverage_complete
    )
    topology_present = topology in {"AVAILABLE", "PARTIAL"}
    topology_partial = topology == "PARTIAL" or (
        topology_present and (not mapping_complete or not pair_coverage_complete)
    )
    if topology_present and (counts["mapped_device_count"] > 0 or counts["eligible_pair_count"] > 0):
        observed_families.append("topology")
    if audit_complete:
        observed_families.append("structural")

    reasons: list[str] = []
    if topology == "UNAVAILABLE":
        reasons.append("TOPOLOGY_NOT_USED")
    elif topology_present:
        if not mapping_complete:
            reasons.append("TOPOLOGY_MAPPING_INCOMPLETE")
        if not pair_coverage_complete:
            reasons.append("TOPOLOGY_PAIR_COVERAGE_INCOMPLETE")
        if topology == "PARTIAL" and not reasons:
            reasons.append("TOPOLOGY_SOURCE_PARTIAL")
        if not topology_complete and audit_complete:
            reasons.append("TOPOLOGY_NOT_USED")

    if audit == "PARTIAL":
        reasons.append("AUDIT_INCOMPLETE")
    elif audit == "UNAVAILABLE":
        reasons.append("AUDIT_UNAVAILABLE")
    elif audit == "NOT_EVALUATED":
        reasons.append("AUDIT_NOT_EVALUATED")
    elif audit == "EVALUATED" and not audit_complete:
        reasons.append("AUDIT_INCOMPLETE")

    if review != "COMPLETED":
        reasons.append(
            "REVIEW_UNAVAILABLE" if review == "UNAVAILABLE" else "REVIEW_NOT_COMPLETED"
        )

    independent_family_observed = topology_complete or audit_complete
    complete_families = tuple(
        family
        for family, complete in (
            ("topology", topology_complete),
            ("structural", audit_complete),
        )
        if complete
    )
    if role_coverage < 0.5:
        reasons.insert(0, "INSUFFICIENT_ROLE_COVERAGE")
        status: ReadinessStatus = "INSUFFICIENT"
    elif not independent_family_observed:
        reasons.append("INSUFFICIENT_INDEPENDENT_EVIDENCE")
        status = "INSUFFICIENT"
    elif (
        review != "COMPLETED"
        or audit == "PARTIAL"
        or (topology_partial and not audit_complete)
    ):
        status = "PARTIAL"
    else:
        status = "READY"

    return QualityReadiness(
        status=status,
        observed_families=tuple(observed_families),
        complete_families=complete_families,
        missing_reasons=tuple(dict.fromkeys(reasons)),
        evaluated_pair_count=counts["evaluated_pair_count"],
        eligible_pair_count=counts["eligible_pair_count"],
    )
