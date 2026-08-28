"""Descriptor metrics (§5).

Full metric set, reported side by side and never collapsed into one number:

    Coverage / Recall   TP / |C|
    Precision_global    TP / (TP + FP) over the global universe
    Precision_local     TP / (TP + FP) over U_local only
    FPR                 FP / |universe \\ C|
    Lift                Precision_global / base rate
    F1                  harmonic mean of coverage and precision_global

The imbalance example from the spec is why all of them are kept: 30 inside plus
500 outside of 100k gives Coverage 51.7% and FPR 0.5%, which look good, while
Precision_global is 5.66%, which is bad. Reporting FPR alone would mislead.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DescriptorMetrics:
    """Metrics for one rule extent against one target set."""

    true_positives: int
    false_positives: int
    target_size: int
    universe_size: int

    @property
    def extent_size(self) -> int:
        return self.true_positives + self.false_positives

    @property
    def coverage(self) -> float:
        """Recall over the target chain."""
        if self.target_size == 0:
            return 0.0
        return self.true_positives / self.target_size

    @property
    def precision(self) -> float:
        if self.extent_size == 0:
            return 0.0
        return self.true_positives / self.extent_size

    @property
    def negatives(self) -> int:
        return max(self.universe_size - self.target_size, 0)

    @property
    def false_positive_rate(self) -> float:
        if self.negatives == 0:
            return 0.0
        return self.false_positives / self.negatives

    @property
    def base_rate(self) -> float:
        """Prior probability of the target within the universe."""
        if self.universe_size == 0:
            return 0.0
        return self.target_size / self.universe_size

    @property
    def lift(self) -> float | None:
        """``precision / base_rate``; ``None`` when the base rate is zero."""
        base = self.base_rate
        if base <= 0:
            return None
        return self.precision / base

    @property
    def f1(self) -> float:
        precision, coverage = self.precision, self.coverage
        if precision + coverage == 0:
            return 0.0
        return 2 * precision * coverage / (precision + coverage)


def evaluate_extent(
    extent: int,
    target: int,
    *,
    universe_size: int,
    target_size: int,
) -> DescriptorMetrics:
    """Compute metrics for a rule extent by popcount."""
    true_positives = (extent & target).bit_count()
    return DescriptorMetrics(
        true_positives=true_positives,
        false_positives=extent.bit_count() - true_positives,
        target_size=target_size,
        universe_size=universe_size,
    )
