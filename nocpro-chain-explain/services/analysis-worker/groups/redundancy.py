"""REDUNDANCY role axis: NEAR_DUPLICATE_CANDIDATE / UNIQUE (§4B).

    NEAR_DUPLICATE_CANDIDATE <=> exists y: same alarm_name AND same entity
                                 AND small dt AND adds no new descriptor coverage
    otherwise UNIQUE

This is a candidate flag for operator review (e.g. dedup in the UI), not a
membership or structural verdict: a near-duplicate can still be CORE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from descriptor.mining import Descriptor
from libs.contracts import IngestedAlarm

#: Same-entity fields checked, in priority order.
ENTITY_FIELDS = ("node_reference", "device_code")

#: Small-delta window for "small dt", seconds.
DEFAULT_SMALL_DT_SECONDS = 5


class RedundancyRole(str, Enum):
    NEAR_DUPLICATE_CANDIDATE = "NEAR_DUPLICATE_CANDIDATE"
    UNIQUE = "UNIQUE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class RedundancyResult:
    alarm_id: str
    role: RedundancyRole
    duplicate_of: str | None
    reason: str


def _parse(value: str | None):
    from datetime import datetime

    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _same_entity(a: IngestedAlarm, b: IngestedAlarm) -> bool:
    for field in ENTITY_FIELDS:
        value_a = getattr(a, field, None)
        value_b = getattr(b, field, None)
        if value_a is not None and value_a == value_b:
            return True
    return False


def _adds_new_coverage(alarm_id: str, other_id: str, index, descriptors: tuple[Descriptor, ...]) -> bool:
    """True if ``alarm_id`` matches a descriptor that ``other_id`` does not.

    A near-duplicate must not add coverage a descriptor doesn't already have
    from the alleged duplicate; otherwise it is contributing new information.
    """
    try:
        pos_a = index.universe.index(alarm_id)
        pos_b = index.universe.index(other_id)
    except ValueError:
        return False
    for descriptor in descriptors:
        if descriptor.matches_alarm_bit(pos_a) and not descriptor.matches_alarm_bit(pos_b):
            return True
    return False


def classify_redundancy(
    alarm_id: str,
    members: list[IngestedAlarm],
    *,
    index,
    descriptors: tuple[Descriptor, ...],
    small_dt_seconds: int = DEFAULT_SMALL_DT_SECONDS,
) -> RedundancyResult:
    """Classify one member as a near-duplicate candidate or unique."""
    target = next((a for a in members if a.alarm_id == alarm_id), None)
    if target is None:
        return RedundancyResult(
            alarm_id=alarm_id,
            role=RedundancyRole.NOT_APPLICABLE,
            duplicate_of=None,
            reason="alarm not found in this chain",
        )

    target_time = _parse(target.canonical_start_time)
    target_name = (target.alarm_name or "").strip() or None

    if target_name is None or target_time is None:
        return RedundancyResult(
            alarm_id=alarm_id,
            role=RedundancyRole.NOT_APPLICABLE,
            duplicate_of=None,
            reason="alarm_name or timestamp unavailable",
        )

    for other in members:
        if other.alarm_id == alarm_id:
            continue
        other_name = (other.alarm_name or "").strip() or None
        other_time = _parse(other.canonical_start_time)
        if other_name != target_name or other_time is None:
            continue
        if not _same_entity(target, other):
            continue
        delta = abs((target_time - other_time).total_seconds())
        if delta > small_dt_seconds:
            continue
        if _adds_new_coverage(alarm_id, other.alarm_id, index, descriptors):
            continue
        return RedundancyResult(
            alarm_id=alarm_id,
            role=RedundancyRole.NEAR_DUPLICATE_CANDIDATE,
            duplicate_of=other.alarm_id,
            reason=(
                f"same alarm_name and entity as {other.alarm_id!r}, "
                f"dt={delta:.1f}s, no new descriptor coverage"
            ),
        )

    return RedundancyResult(
        alarm_id=alarm_id,
        role=RedundancyRole.UNIQUE,
        duplicate_of=None,
        reason="no matching near-duplicate found",
    )
