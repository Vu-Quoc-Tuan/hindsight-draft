"""Benchmark harness (§11).

Measures per-tier latency and peak memory across a matrix of workloads:

    N_alarm ∈ {10k, 50k, 100k}  (or whatever is available)
    K = #chains, C_max = max chain size, C_p95
    Topology mapping coverage
    Đo: P50/P95 latency per tier · throughput · MEMORY PEAK

Two different shapes of "100k alarm" are explicitly called out:
  "100k chains × 1" (heavy singleton) and "5 chains × 20k" (heavy large-chain)
have completely different performance profiles.

This module provides the harness; the actual data comes from either the mock CLI
or synthetic generation. Results are written to a JSON report so they can be
compared across runs.
"""

from __future__ import annotations

import json
import statistics
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class WorkloadSpec:
    """One cell in the benchmark matrix."""

    name: str
    n_alarms: int
    n_chains: int
    max_chain_size: int
    description: str = ""


@dataclass
class TimingResult:
    """Wall-clock results for one operation across N repetitions."""

    operation: str
    workload: str
    durations_seconds: list[float] = field(default_factory=list)
    peak_memory_bytes: int | None = None

    @property
    def n(self) -> int:
        return len(self.durations_seconds)

    @property
    def p50(self) -> float | None:
        if not self.durations_seconds:
            return None
        return statistics.median(self.durations_seconds)

    @property
    def p95(self) -> float | None:
        if self.n < 2:
            return self.p50
        ordered = sorted(self.durations_seconds)
        index = int(0.95 * (self.n - 1))
        return ordered[index]

    @property
    def mean(self) -> float | None:
        if not self.durations_seconds:
            return None
        return statistics.mean(self.durations_seconds)

    def summary(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "workload": self.workload,
            "n": self.n,
            "p50_s": round(self.p50, 4) if self.p50 is not None else None,
            "p95_s": round(self.p95, 4) if self.p95 is not None else None,
            "mean_s": round(self.mean, 4) if self.mean is not None else None,
            "peak_memory_mb": (
                round(self.peak_memory_bytes / 1024 / 1024, 2)
                if self.peak_memory_bytes is not None
                else None
            ),
        }


@dataclass
class BenchmarkReport:
    """Full benchmark run results."""

    results: list[TimingResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "metadata": self.metadata,
            "results": [r.summary() for r in self.results],
        }
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return target


def measure(
    operation: str,
    workload: str,
    fn: Callable[[], Any],
    *,
    repetitions: int = 3,
    track_memory: bool = True,
) -> TimingResult:
    """Time one operation and optionally measure peak memory."""
    result = TimingResult(operation=operation, workload=workload)
    peak_memory = 0

    for _ in range(repetitions):
        if track_memory:
            tracemalloc.start()
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        result.durations_seconds.append(elapsed)
        if track_memory:
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_memory = max(peak_memory, peak)

    if track_memory:
        result.peak_memory_bytes = peak_memory
    return result


#: Design objectives from §11 (not SLOs, hypotheses pending benchmark).
DESIGN_OBJECTIVES = {
    "tier_1a_snapshot_background": 30.0,
    "tier_1b_on_chain_open_p95": 5.0,
    "tier_2_per_chain": 30.0,
}


def check_against_objectives(results: list[TimingResult]) -> list[str]:
    """Report which results exceed design objectives (informational, not blocking)."""
    warnings: list[str] = []
    for result in results:
        objective = DESIGN_OBJECTIVES.get(result.operation)
        if objective is not None and result.p95 is not None:
            if result.p95 > objective:
                warnings.append(
                    f"{result.operation} [{result.workload}]: P95={result.p95:.2f}s "
                    f"exceeds design objective {objective}s"
                )
    return warnings
