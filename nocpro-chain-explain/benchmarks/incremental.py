"""Incremental snapshot indexing measurement (§11).

§11 states:

    "Incremental snapshot indexing — hypothesis cần đo: thiết kế hỗ trợ delta
    update (NEW/CLEARED); benefit phụ thuộc overlap thực tế. Việc đo bắt buộc:
    phân bố J(A_t, A_{t+1}) trên 1–4 tuần production."

This module measures that overlap, reporting the Jaccard distribution across a
sequence of snapshots. The outcome decides whether incremental indexing is worth
its complexity:

    median Jaccard > 90%  =>  incremental keeps Tier-1A at the low end of 10–30s
    Jaccard drops to ~50% =>  need a full-path fast enough as fallback

The measurement is a prerequisite for an informed architecture decision, not the
implementation of incremental indexing itself. What gets built depends on the
numbers this reports.

Reconciliation trigger from §11: "delta count vượt ngưỡng / cache consistency
error / snapshot version gap / lịch off-peak". The thresholds for these are
derived from this Jaccard distribution once it is observed on real data.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from libs.contracts import IngestedPackage


@dataclass(frozen=True)
class SnapshotOverlap:
    """Jaccard overlap between two consecutive snapshots."""

    previous_snapshot_id: str
    current_snapshot_id: str
    previous_alarm_count: int
    current_alarm_count: int
    intersection: int
    union: int
    new_count: int
    cleared_count: int

    @property
    def jaccard(self) -> float:
        return self.intersection / self.union if self.union else 0.0

    @property
    def delta_ratio(self) -> float:
        """Fraction of alarms that changed (either appeared or cleared)."""
        return (self.new_count + self.cleared_count) / self.union if self.union else 0.0


@dataclass
class OverlapDistribution:
    """Jaccard distribution across a sequence of snapshot pairs."""

    overlaps: list[SnapshotOverlap] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.overlaps)

    @property
    def jaccards(self) -> list[float]:
        return [o.jaccard for o in self.overlaps]

    @property
    def median_jaccard(self) -> float | None:
        if not self.jaccards:
            return None
        return statistics.median(self.jaccards)

    @property
    def min_jaccard(self) -> float | None:
        return min(self.jaccards) if self.jaccards else None

    @property
    def p10_jaccard(self) -> float | None:
        """P10: the 10th percentile, where the worst alarm floods live."""
        if len(self.jaccards) < 2:
            return self.min_jaccard
        ordered = sorted(self.jaccards)
        return ordered[int(0.10 * (len(ordered) - 1))]

    def summary(self) -> dict:
        return {
            "n_pairs": self.n,
            "median_jaccard": (
                round(self.median_jaccard, 4) if self.median_jaccard is not None else None
            ),
            "min_jaccard": (
                round(self.min_jaccard, 4) if self.min_jaccard is not None else None
            ),
            "p10_jaccard": (
                round(self.p10_jaccard, 4) if self.p10_jaccard is not None else None
            ),
            "recommendation": self._recommendation(),
        }

    def _recommendation(self) -> str:
        median = self.median_jaccard
        if median is None:
            return "insufficient data"
        if median >= 0.90:
            return (
                "high overlap: incremental delta update likely keeps Tier-1A near "
                "the 10s target"
            )
        if median >= 0.70:
            return (
                "moderate overlap: incremental worthwhile but full-path fallback "
                "needs to be fast"
            )
        return (
            "low overlap: alarm flood / heavy churn; full rebuild may be as fast "
            "as delta tracking overhead"
        )


def measure_overlap(previous: IngestedPackage, current: IngestedPackage) -> SnapshotOverlap:
    """Compute Jaccard overlap between two snapshot alarm sets."""
    prev_ids = set(previous.alarms)
    curr_ids = set(current.alarms)
    intersection = prev_ids & curr_ids
    union = prev_ids | curr_ids
    return SnapshotOverlap(
        previous_snapshot_id=previous.snapshot.snapshot_id,
        current_snapshot_id=current.snapshot.snapshot_id,
        previous_alarm_count=len(prev_ids),
        current_alarm_count=len(curr_ids),
        intersection=len(intersection),
        union=len(union),
        new_count=len(curr_ids - prev_ids),
        cleared_count=len(prev_ids - curr_ids),
    )


def measure_sequence_overlap(snapshots: list[IngestedPackage]) -> OverlapDistribution:
    """Measure Jaccard across a sequence of consecutive snapshots."""
    distribution = OverlapDistribution()
    for index in range(1, len(snapshots)):
        overlap = measure_overlap(snapshots[index - 1], snapshots[index])
        distribution.overlaps.append(overlap)
    return distribution
