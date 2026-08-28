"""Run the real-data Tier-1/Tier-2 benchmark matrix.

Run from the chain-explain root::

    ../nocpro-mock/.venv/bin/python benchmarks/run_benchmark.py

Tier-1B latency uses 20 repetitions by default so the observed nearest-rank P95
resolves a five-percent tail. Expensive Tier-1A is sampled separately and is
explicitly marked unreliable when fewer than 20 samples are requested.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/analysis-worker"))

from benchmarks.harness import (
    BenchmarkReport,
    TimingResult,
    check_against_objectives,
    measure,
)
from channels import build_indexed_statistics, evaluate_pair_channels
from configuration import load_analysis_config
from descriptor import build_predicate_index
from libs.contracts import load_package
from tier1a import Tier1Cache, precompute_snapshot
from tier1b import analyze_chain_configured
from tier2 import AuditExecutionPolicy, analyze_structural_audit

MOCK_ROOT = Path(__file__).resolve().parents[2] / "nocpro-mock"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
TARGET_SIZES = (1, 10, 50, 200, 500, 1072)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/thresholds/v1.yaml"
ANALYSIS_CONFIG = load_analysis_config(CONFIG_PATH)
MINING = ANALYSIS_CONFIG.mining_config()


def _replay():
    result = subprocess.run(
        [
            str(MOCK_ROOT / ".venv/bin/python"),
            "-m",
            "nocpro_mock.cli",
            "replay",
            "--snapshot-id",
            "bench_full",
        ],
        cwd=MOCK_ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"mock CLI failed: {result.stderr[:500]}")
    return load_package(json.loads(result.stdout))


def _workloads(package) -> list[tuple[int, str, int]]:
    sizes = [(chain.member_count, chain_id) for chain_id, chain in package.chains.items()]
    selected: list[tuple[int, str, int]] = []
    seen: set[str] = set()
    for target in TARGET_SIZES:
        actual, chain_id = min(sizes, key=lambda item: (abs(item[0] - target), item[1]))
        if chain_id not in seen:
            selected.append((target, chain_id, actual))
            seen.add(chain_id)
    return selected


def _phase_results(
    package,
    chain_id: str,
    *,
    workload: str,
    predicate_index,
    repetitions: int,
) -> list[TimingResult]:
    phases: dict[str, TimingResult] = {}

    def run_once():
        analysis = analyze_chain_configured(
            package,
            chain_id,
            analysis_config=ANALYSIS_CONFIG,
            predicate_index=predicate_index,
        )
        for name, duration in analysis.phase_durations.items():
            phases.setdefault(
                name,
                TimingResult(operation=f"tier_1b_phase_{name}", workload=workload),
            ).durations_seconds.append(duration)

    total = measure(
        "tier_1b_on_chain_open_p95",
        workload,
        run_once,
        repetitions=repetitions,
        track_memory=False,
    )
    return [total, *[phases[name] for name in sorted(phases)]]


def run() -> BenchmarkReport:
    tier1b_repetitions = int(os.environ.get("BENCHMARK_REPETITIONS", "20"))
    tier1a_repetitions = int(os.environ.get("BENCHMARK_TIER1A_REPETITIONS", "3"))
    report = BenchmarkReport(
        metadata={
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "p95_method": "observed nearest-rank",
            "tier_1b_repetitions": tier1b_repetitions,
            "tier_1a_repetitions": tier1a_repetitions,
            "analysis_config_version": ANALYSIS_CONFIG.config_version,
        }
    )

    print("Loading full export...")
    load_result = measure(
        "source_package_load",
        "full_export",
        _replay,
        repetitions=3,
        track_memory=False,
    )
    report.results.append(load_result)
    package = _replay()
    report.metadata["workload"] = (
        f"{len(package.alarms)} alarms, {len(package.chains)} chains, "
        f"max={max(chain.member_count for chain in package.chains.values())}"
    )

    print("Building reusable predicate index...")
    predicate_index = build_predicate_index(
        list(package.alarms.values()),
        max_values_per_field=int(
            ANALYSIS_CONFIG.value("descriptor.max_values_per_field")
        ),
    )

    print("Benchmarking Tier-1A full snapshot...")
    report.results.append(
        measure(
            "tier_1a_snapshot_background",
            "full_export",
            lambda: precompute_snapshot(
                package,
                mining_config=MINING,
                cache=Tier1Cache(),
                max_values_per_field=int(
                    ANALYSIS_CONFIG.value("descriptor.max_values_per_field")
                ),
            ),
            repetitions=tier1a_repetitions,
            track_memory=False,
        )
    )
    report.results.append(
        measure(
            "tier_1a_peak_memory",
            "full_export",
            lambda: precompute_snapshot(
                package,
                mining_config=MINING,
                cache=Tier1Cache(),
                max_values_per_field=int(
                    ANALYSIS_CONFIG.value("descriptor.max_values_per_field")
                ),
            ),
            repetitions=1,
            track_memory=True,
        )
    )

    matrix = _workloads(package)
    report.metadata["chain_matrix"] = [
        {"target_size": target, "actual_size": actual, "chain_id": chain_id}
        for target, chain_id, actual in matrix
    ]

    for target, chain_id, actual in matrix:
        workload = f"target_{target}_chain_{chain_id}_n_{actual}"
        print(f"Benchmarking Tier-1B {workload}...")
        report.results.append(
            measure(
                "tier_1b_index_build",
                workload,
                lambda cid=chain_id: build_indexed_statistics(
                    package,
                    cid,
                    silent_gap_seconds=int(
                        ANALYSIS_CONFIG.value("temporal.burst.gap_seconds")
                    ),
                    d_max=int(ANALYSIS_CONFIG.value("dependency.max_hop")),
                ),
                repetitions=tier1b_repetitions,
                track_memory=False,
            )
        )
        report.results.extend(
            _phase_results(
                package,
                chain_id,
                workload=workload,
                predicate_index=predicate_index,
                repetitions=tier1b_repetitions,
            )
        )

        members = package.members_of(chain_id)
        if len(members) >= 2:
            report.results.append(
                measure(
                    "pair_on_click",
                    workload,
                    lambda cid=chain_id, left=members[0], right=members[1]: (
                        evaluate_pair_channels(
                            package,
                            cid,
                            left,
                            right,
                            delay_threshold=float(
                                ANALYSIS_CONFIG.value(
                                    "temporal.delay.support_threshold"
                                )
                            ),
                            d_max=int(ANALYSIS_CONFIG.value("dependency.max_hop")),
                            silent_gap_seconds=int(
                                ANALYSIS_CONFIG.value("temporal.burst.gap_seconds")
                            ),
                        )
                    ),
                    repetitions=tier1b_repetitions,
                    track_memory=False,
                )
            )

        report.results.append(
            measure(
                "tier_1b_peak_memory",
                workload,
                lambda cid=chain_id: analyze_chain_configured(
                    package,
                    cid,
                    analysis_config=ANALYSIS_CONFIG,
                    predicate_index=predicate_index,
                ),
                repetitions=1,
                track_memory=True,
            )
        )

        if actual <= 50 and actual >= 2:
            report.results.append(
                measure(
                    "tier_2_exact_audit",
                    workload,
                    lambda cid=chain_id, bound=actual: analyze_structural_audit(
                        package,
                        cid,
                        policy=AuditExecutionPolicy(exact_max_members=bound),
                        mining_config=MINING,
                        epsilon=float(
                            ANALYSIS_CONFIG.value("audit.global_weak_baseline")
                        ),
                    ),
                    repetitions=3,
                    track_memory=False,
                )
            )

    report.metadata["objective_warnings"] = check_against_objectives(report.results)
    output = report.write(RESULTS_DIR / "latest.json")
    print(f"Report written to {output}")
    return report


if __name__ == "__main__":
    run()
