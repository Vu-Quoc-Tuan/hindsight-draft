from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.run_runtime_review_benchmark import observed_nearest_rank


def test_observed_nearest_rank_uses_the_95th_observed_value() -> None:
    values = [0.1] * 19 + [9.9]
    assert observed_nearest_rank(values) == 0.1
    assert observed_nearest_rank(values, 0.96) == 9.9
