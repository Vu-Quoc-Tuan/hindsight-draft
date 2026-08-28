"""Benchmark statistics must not overstate sparse samples."""

from __future__ import annotations

import pytest

from benchmarks.harness import TimingResult, nearest_rank_percentile


def test_nearest_rank_percentile_uses_the_observed_upper_tail():
    assert nearest_rank_percentile([1.0, 2.0, 10.0], 0.95) == 10.0
    assert nearest_rank_percentile(list(range(1, 21)), 0.95) == 19


def test_percentile_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        nearest_rank_percentile([], 0.95)
    with pytest.raises(ValueError):
        nearest_rank_percentile([1.0], 0.0)


def test_three_samples_are_not_labeled_reliable_p95():
    result = TimingResult("tier_1b", "small", [1.0, 2.0, 10.0])
    assert result.p95 == 10.0
    assert result.p95_reliable is False
    assert result.summary()["p95_reliable"] is False


def test_twenty_samples_resolve_a_five_percent_tail():
    result = TimingResult("tier_1b", "matrix", [float(i) for i in range(1, 21)])
    assert result.p95 == 19.0
    assert result.p95_reliable is True
