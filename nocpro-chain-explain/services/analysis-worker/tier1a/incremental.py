"""Exact delta predicate index for consecutive complete snapshots (§11).

The production decision to enable this path by default still depends on the
required 1--4 week overlap study.  This module supplies the semantics-preserving
implementation and explicit reconciliation signals without inventing that
policy.  Full predicate postings are retained internally so a value outside the
current display/mining top-K can become eligible after a delta update.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from enum import Enum

from descriptor import (
    DEFAULT_MAX_VALUES_PER_FIELD,
    PREDICATE_FIELDS,
    Predicate,
    PredicateIndex,
)
from descriptor.predicates import read_field
from libs.contracts import IngestedAlarm, IngestedPackage

from .precompute import IncompleteSnapshotError


@dataclass(frozen=True)
class IncrementalUpdate:
    previous_snapshot_id: str
    current_snapshot_id: str
    new_ids: frozenset[str]
    cleared_ids: frozenset[str]
    updated_ids: frozenset[str]

    @property
    def delta_count(self) -> int:
        return len(self.new_ids) + len(self.cleared_ids) + len(self.updated_ids)


class ReconciliationReason(str, Enum):
    DELTA_THRESHOLD_EXCEEDED = "DELTA_THRESHOLD_EXCEEDED"
    CACHE_CONSISTENCY_ERROR = "CACHE_CONSISTENCY_ERROR"
    SNAPSHOT_VERSION_GAP = "SNAPSHOT_VERSION_GAP"
    OFF_PEAK_SCHEDULE = "OFF_PEAK_SCHEDULE"


@dataclass(frozen=True)
class ReconciliationPolicy:
    """Caller-selected policy; no production default before overlap evidence."""

    max_delta_ratio: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.max_delta_ratio <= 1.0:
            raise ValueError("max_delta_ratio must be in [0,1]")


def reconciliation_reasons(
    update: IncrementalUpdate,
    *,
    active_alarm_count: int,
    policy: ReconciliationPolicy,
    cache_consistency_error: bool = False,
    snapshot_version_gap: bool = False,
    off_peak_due: bool = False,
) -> frozenset[ReconciliationReason]:
    """Resolve the four configurable reconciliation triggers frozen in §11."""
    denominator = max(active_alarm_count, 1)
    reasons: set[ReconciliationReason] = set()
    if update.delta_count / denominator >= policy.max_delta_ratio:
        reasons.add(ReconciliationReason.DELTA_THRESHOLD_EXCEEDED)
    if cache_consistency_error:
        reasons.add(ReconciliationReason.CACHE_CONSISTENCY_ERROR)
    if snapshot_version_gap:
        reasons.add(ReconciliationReason.SNAPSHOT_VERSION_GAP)
    if off_peak_due:
        reasons.add(ReconciliationReason.OFF_PEAK_SCHEDULE)
    return frozenset(reasons)


@dataclass
class IncrementalPredicateIndex:
    """Stable-slot exact postings updated from NEW/CLEARED/changed alarms."""

    snapshot_id: str
    fields: tuple[tuple[str, str], ...] = PREDICATE_FIELDS
    max_values_per_field: int = DEFAULT_MAX_VALUES_PER_FIELD
    _slots: list[str | None] = field(default_factory=list)
    _positions: dict[str, int] = field(default_factory=dict)
    _alarms: dict[str, IngestedAlarm] = field(default_factory=dict)
    _postings: dict[Predicate, int] = field(default_factory=dict)
    _free_slots: list[int] = field(default_factory=list)

    @classmethod
    def from_package(
        cls,
        package: IngestedPackage,
        *,
        fields: tuple[tuple[str, str], ...] = PREDICATE_FIELDS,
        max_values_per_field: int = DEFAULT_MAX_VALUES_PER_FIELD,
    ) -> "IncrementalPredicateIndex":
        if not package.snapshot.is_complete:
            raise IncompleteSnapshotError(
                f"snapshot {package.snapshot.snapshot_id!r} must be COMPLETE "
                "before incremental indexing"
            )
        result = cls(
            snapshot_id=package.snapshot.snapshot_id,
            fields=fields,
            max_values_per_field=max_values_per_field,
        )
        for alarm_id in sorted(package.alarms):
            result._add(package.alarms[alarm_id])
        result._assert_consistent()
        return result

    def _predicates_of(self, alarm: IngestedAlarm) -> frozenset[Predicate]:
        result: set[Predicate] = set()
        for field_name, derivation_tag in self.fields:
            value = read_field(alarm, field_name)
            if value is not None:
                result.add(Predicate(field_name, value, derivation_tag))
        return frozenset(result)

    def _allocate_slot(self, alarm_id: str) -> int:
        if self._free_slots:
            position = heapq.heappop(self._free_slots)
            self._slots[position] = alarm_id
        else:
            position = len(self._slots)
            self._slots.append(alarm_id)
        self._positions[alarm_id] = position
        return position

    def _add(self, alarm: IngestedAlarm) -> None:
        position = self._allocate_slot(alarm.alarm_id)
        bit = 1 << position
        for predicate in self._predicates_of(alarm):
            self._postings[predicate] = self._postings.get(predicate, 0) | bit
        self._alarms[alarm.alarm_id] = alarm

    def _remove(self, alarm_id: str) -> None:
        alarm = self._alarms.pop(alarm_id)
        position = self._positions.pop(alarm_id)
        bit_mask = ~(1 << position)
        for predicate in self._predicates_of(alarm):
            remaining = self._postings[predicate] & bit_mask
            if remaining:
                self._postings[predicate] = remaining
            else:
                del self._postings[predicate]
        self._slots[position] = None
        heapq.heappush(self._free_slots, position)

    def _replace(self, alarm: IngestedAlarm) -> None:
        alarm_id = alarm.alarm_id
        position = self._positions[alarm_id]
        bit = 1 << position
        old = self._alarms[alarm_id]
        old_predicates = self._predicates_of(old)
        new_predicates = self._predicates_of(alarm)
        for predicate in old_predicates - new_predicates:
            remaining = self._postings[predicate] & ~bit
            if remaining:
                self._postings[predicate] = remaining
            else:
                del self._postings[predicate]
        for predicate in new_predicates - old_predicates:
            self._postings[predicate] = self._postings.get(predicate, 0) | bit
        self._alarms[alarm_id] = alarm

    def apply_snapshot(self, package: IngestedPackage) -> IncrementalUpdate:
        if not package.snapshot.is_complete:
            raise IncompleteSnapshotError(
                f"snapshot {package.snapshot.snapshot_id!r} must be COMPLETE "
                "before incremental indexing"
            )
        previous_id = self.snapshot_id
        previous_ids = set(self._alarms)
        current_ids = set(package.alarms)
        cleared = previous_ids - current_ids
        new = current_ids - previous_ids
        updated = {
            alarm_id
            for alarm_id in previous_ids & current_ids
            if self._predicates_of(self._alarms[alarm_id])
            != self._predicates_of(package.alarms[alarm_id])
        }

        for alarm_id in sorted(cleared):
            self._remove(alarm_id)
        for alarm_id in sorted(updated):
            self._replace(package.alarms[alarm_id])
        for alarm_id in sorted(new):
            self._add(package.alarms[alarm_id])
        self.snapshot_id = package.snapshot.snapshot_id
        self._assert_consistent()
        return IncrementalUpdate(
            previous_snapshot_id=previous_id,
            current_snapshot_id=self.snapshot_id,
            new_ids=frozenset(new),
            cleared_ids=frozenset(cleared),
            updated_ids=frozenset(updated),
        )

    def view(self) -> PredicateIndex:
        """Expose bounded active postings without rebuilding alarm predicates."""
        by_field: dict[str, list[Predicate]] = {}
        for predicate in self._postings:
            by_field.setdefault(predicate.field, []).append(predicate)
        kept: dict[Predicate, int] = {}
        for predicates in by_field.values():
            predicates.sort(
                key=lambda predicate: (
                    -self._postings[predicate].bit_count(),
                    predicate.value,
                )
            )
            for predicate in predicates[: self.max_values_per_field]:
                kept[predicate] = self._postings[predicate]
        return PredicateIndex(
            universe=tuple(self._slots),
            bitmaps=kept,
            active_size=len(self._alarms),
            positions=dict(self._positions),
        )

    def _assert_consistent(self) -> None:
        active_from_slots = {
            alarm_id for alarm_id in self._slots if alarm_id is not None
        }
        if active_from_slots != set(self._alarms) or active_from_slots != set(
            self._positions
        ):
            raise RuntimeError("incremental predicate index consistency error")
        for alarm_id, position in self._positions.items():
            if self._slots[position] != alarm_id:
                raise RuntimeError("incremental predicate slot mapping is inconsistent")
