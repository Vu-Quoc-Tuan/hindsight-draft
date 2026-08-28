"""Run the benchmark matrix against the real alarm export.

Requires the sibling nocpro-mock repo with its .venv and real data in
``datasets/raw/alarm_data.csv``. Run from the chain-explain root:

    ../nocpro-mock/.venv/bin/python benchmarks/run_benchmark.py

Results are written to ``benchmarks/results/latest.json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/analysis-worker"))

from benchmarks.harness import (
    BenchmarkReport,
    WorkloadSpec,
    check_against_objectives,
    measure,
)
from descriptor import MiningConfig
from groups import RoleThresholds
from libs.contracts import load_package
from tier1a import precompute_snapshot, Tier1Cache
from tier1b import analyze_chain

MOCK_ROOT = Path(__file__).resolve().parents[2] / "nocpro-mock"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

THRESHOLDS = RoleThresholds(config_version="bench-v1")
MINING = MiningConfig(config_version="bench-mine-v1")


def _replay(*, limit: int | None = None, chain_ids: list[str] | None = None):
    args = [
        str(MOCK_ROOT / ".venv/bin/python"),
        "-m", "nocpro_mock.cli", "replay",
        "--snapshot-id", f"bench_{limit or 'full'}",
    ]
    if limit:
        args += ["--limit", str(limit)]
    if chain_ids:
        for cid in chain_ids:
            args += ["--chain-id", cid]
    result = subprocess.run(
        args, cwd=MOCK_ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"mock CLI failed: {result.stderr[:500]}")
    return load_package(json.loads(result.stdout))


def run() -> BenchmarkReport:
    report = BenchmarkReport(metadata={"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})

    # --- Workload: full export (8714 alarms / 2824 chains) ---
    print("Loading full export...")
    full = _replay()
    n_alarms = len(full.alarms)
    n_chains = len(full.chains)
    max_chain = max(c.member_count for c in full.chains.values())
    spec = WorkloadSpec(
        name="full_export",
        n_alarms=n_alarms,
        n_chains=n_chains,
        max_chain_size=max_chain,
        description=f"{n_alarms} alarms, {n_chains} chains, max={max_chain}",
    )
    report.metadata["workload"] = spec.description

    # Tier-1A: precompute over the whole snapshot.
    print(f"Benchmarking Tier-1A ({spec.description})...")
    cache = Tier1Cache()
    r = measure(
        "tier_1a_snapshot_background",
        spec.name,
        lambda: precompute_snapshot(full, mining_config=MINING, cache=cache),
        repetitions=3,
    )
    report.results.append(r)
    print(f"  Tier-1A: P50={r.p50:.2f}s P95={r.p95:.2f}s mem={r.peak_memory_bytes/1024/1024:.1f}MB")

    # Tier-1B: single chain analysis on the largest chain.
    largest_id = max(full.chains, key=lambda c: full.chains[c].member_count)
    print(f"Benchmarking Tier-1B (chain {largest_id}, {full.chains[largest_id].member_count} members)...")
    r = measure(
        "tier_1b_on_chain_open_p95",
        f"chain_{largest_id}_{full.chains[largest_id].member_count}",
        lambda: analyze_chain(full, largest_id, thresholds=THRESHOLDS, mining_config=MINING),
        repetitions=3,
    )
    report.results.append(r)
    print(f"  Tier-1B: P50={r.p50:.2f}s P95={r.p95:.2f}s mem={r.peak_memory_bytes/1024/1024:.1f}MB")

    # Tier-1B: singleton (first-class path, 73% of chains).
    singleton_id = next(
        (cid for cid, c in full.chains.items() if c.member_count == 1), None
    )
    if singleton_id:
        print(f"Benchmarking Tier-1B singleton ({singleton_id})...")
        r = measure(
            "tier_1b_singleton",
            "singleton",
            lambda: analyze_chain(full, singleton_id, thresholds=THRESHOLDS, mining_config=MINING),
            repetitions=3,
        )
        report.results.append(r)
        print(f"  Tier-1B singleton: P50={r.p50:.3f}s")

    # --- Check against design objectives ---
    warnings = check_against_objectives(report.results)
    if warnings:
        print("\n⚠️  Design objective warnings:")
        for w in warnings:
            print(f"  {w}")
    else:
        print("\n✓ All results within design objectives.")

    # Write report.
    output = report.write(RESULTS_DIR / "latest.json")
    print(f"\nReport written to {output}")
    return report


if __name__ == "__main__":
    run()
