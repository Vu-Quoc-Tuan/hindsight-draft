"""Consolidated closure-benchmark manifest and report shape.

This module deliberately does not create data, choose thresholds, or turn an
unavailable capability into a fallback.  It makes the benchmark matrix
explicit so a run report can distinguish a measured operation from one that
is intentionally unavailable or not run in the current environment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Iterable


LARGE_CHAIN_ANTI_ALL_PAIRS_GATE = 1072
TARGET_CHAIN_SIZES = (58, 200, 500, LARGE_CHAIN_ANTI_ALL_PAIRS_GATE)


@dataclass(frozen=True)
class ClosureBenchmarkOperation:
    name: str
    tier: str
    requires_runtime: bool = False
    exact_only: bool = False
    notes: str = ""


OPERATIONS: tuple[ClosureBenchmarkOperation, ...] = (
    ClosureBenchmarkOperation("tier_1a_snapshot_background", "Tier-1A"),
    ClosureBenchmarkOperation("tier_1b_cold_on_chain_open", "Tier-1B"),
    ClosureBenchmarkOperation("tier_1b_cache_hit_on_chain_open", "Tier-1B"),
    ClosureBenchmarkOperation("pair_why", "Tier-1B"),
    ClosureBenchmarkOperation("historical_h_pair_why", "Tier-1B"),
    ClosureBenchmarkOperation("temporal_delay_pair_why", "Tier-1B"),
    ClosureBenchmarkOperation("tier_2_structural_audit", "Tier-2", exact_only=True),
    ClosureBenchmarkOperation("evidence_attribution", "Tier-2", exact_only=True),
    ClosureBenchmarkOperation("attribution_deletion_curve", "Tier-2", exact_only=True),
    ClosureBenchmarkOperation("review_remove_member", "Review", exact_only=True),
    ClosureBenchmarkOperation("review_split_chain", "Review", exact_only=True),
    ClosureBenchmarkOperation("review_move_member", "Review", exact_only=True),
    ClosureBenchmarkOperation("merge_cross_chain_evidence", "Review", exact_only=True),
    ClosureBenchmarkOperation("review_merge_chains", "Review", exact_only=True),
    ClosureBenchmarkOperation("review_serialization", "Review"),
    ClosureBenchmarkOperation("review_persistence", "Review", requires_runtime=True),
    ClosureBenchmarkOperation("review_restart_hydration", "Review", requires_runtime=True),
)


def _finite_nonnegative(value: object) -> bool:
    """Benchmark timings are evidence only when they are real elapsed values."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0


def _positive_repetitions(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _valid_timing(
    p50: object,
    p95: object,
    repetitions: object,
    reliable: object,
) -> bool:
    return (
        _finite_nonnegative(p50)
        and _finite_nonnegative(p95)
        and p50 <= p95
        and _positive_repetitions(repetitions)
        and isinstance(reliable, bool)
    )


def _valid_entries(entries: list[dict]) -> bool:
    return bool(entries) and all(
        _valid_timing(
            entry.get("p50_s"),
            entry.get("p95_s"),
            entry.get("n"),
            entry.get("p95_reliable"),
        )
        for entry in entries
    )


def _invalid_measurement_result(
    operation: ClosureBenchmarkOperation,
    reason: str = "INVALID_OR_INCOMPLETE_BENCHMARK_EVIDENCE",
) -> dict:
    return {
        "operation": operation.name,
        "tier": operation.tier,
        "status": "NOT_RUN",
        "reason": reason,
        "exact_only": operation.exact_only,
        "requires_runtime": operation.requires_runtime,
    }


def closure_manifest() -> dict:
    """Return a stable, serializable closure benchmark contract."""
    return {
        "contract": "closure-benchmark-v1",
        "target_chain_sizes": list(TARGET_CHAIN_SIZES),
        "anti_all_pairs_gate": {
            "chain_size": LARGE_CHAIN_ANTI_ALL_PAIRS_GATE,
            "tier": "Tier-1B",
            "requirement": "dense_pairwise_fallback_forbidden",
            "verification": "tests/spec_sanity/test_tier1_execution_boundary.py",
        },
        "operations": [asdict(operation) for operation in OPERATIONS],
        "result_states": [
            "MEASURED",
            "UNAVAILABLE",
            "NOT_RUN",
            "SKIPPED_BY_EXACT_CEILING",
        ],
    }


def empty_closure_results(
    operations: Iterable[ClosureBenchmarkOperation] = OPERATIONS,
) -> list[dict]:
    """Make absence explicit before a machine-specific benchmark is run."""
    return [
        {
            "operation": operation.name,
            "tier": operation.tier,
            "status": "NOT_RUN",
            "reason": "BENCHMARK_NOT_EXECUTED",
            "exact_only": operation.exact_only,
            "requires_runtime": operation.requires_runtime,
        }
        for operation in operations
    ]


def consolidated_closure_results(
    results_dir: Path | None = None,
    operations: Iterable[ClosureBenchmarkOperation] = OPERATIONS,
) -> list[dict]:
    """Merge measured benchmark evidence from results directory into closure contract."""
    import json

    base = results_dir or Path(__file__).resolve().parent / "results"
    latest_file = base / "latest.json"
    runtime_file = base / "runtime-review-latest.json"
    review_file = base / "counterfactual-latest.json"

    latest_data = (
        json.loads(latest_file.read_text(encoding="utf-8"))
        if latest_file.is_file()
        else None
    )
    runtime_data = (
        json.loads(runtime_file.read_text(encoding="utf-8"))
        if runtime_file.is_file()
        else None
    )
    review_data = (
        json.loads(review_file.read_text(encoding="utf-8"))
        if review_file.is_file()
        else None
    )

    by_op: dict[str, list[dict]] = {}
    if latest_data and "results" in latest_data:
        for r in latest_data["results"]:
            by_op.setdefault(r.get("operation", ""), []).append(r)

    results: list[dict] = []
    for operation in operations:
        name = operation.name
        tier = operation.tier
        exact_only = operation.exact_only
        requires_runtime = operation.requires_runtime

        if name == "tier_1a_snapshot_background":
            entries = by_op.get("tier_1a_snapshot_background", [])
            if _valid_entries(entries):
                first = entries[0]
                results.append({
                    "operation": name,
                    "tier": tier,
                    "status": "MEASURED",
                    "provenance": "benchmarks/results/latest.json",
                    "p50_seconds": first.get("p50_s"),
                    "p95_seconds": first.get("p95_s"),
                    "p95_reliable": first["p95_reliable"],
                    "repetitions": first["n"],
                    "workload": first.get("workload", "full_export"),
                    "exact_only": exact_only,
                    "requires_runtime": requires_runtime,
                })
                continue
            if entries:
                results.append(_invalid_measurement_result(operation))
                continue

        if name == "tier_1b_cold_on_chain_open":
            entries = by_op.get("tier_1b_on_chain_open_p95", [])
            if _valid_entries(entries):
                matrix = [
                    {
                        "workload": r.get("workload"),
                        "p50_seconds": r.get("p50_s"),
                        "p95_seconds": r.get("p95_s"),
                    }
                    for r in entries
                ]
                p95 = max(r["p95_s"] for r in entries)
                results.append({
                    "operation": name,
                    "tier": tier,
                    "status": "MEASURED",
                    "provenance": "benchmarks/results/latest.json",
                    "chain_matrix": matrix,
                    "p95_seconds": p95,
                    "p95_reliable": all(r["p95_reliable"] for r in entries),
                    "repetitions": entries[0]["n"],
                    "exact_only": exact_only,
                    "requires_runtime": requires_runtime,
                })
                continue
            if entries:
                results.append(_invalid_measurement_result(operation))
                continue

        if name == "tier_1b_cache_hit_on_chain_open":
            entries = by_op.get("tier_1b_workspace_cache_hit_on_chain_open", [])
            if _valid_entries(entries):
                matrix = [
                    {
                        "workload": r.get("workload"),
                        "p50_seconds": r.get("p50_s"),
                        "p95_seconds": r.get("p95_s"),
                    }
                    for r in entries
                ]
                p95 = max(r["p95_s"] for r in entries)
                results.append({
                    "operation": name,
                    "tier": tier,
                    "status": "MEASURED",
                    "provenance": "benchmarks/results/latest.json",
                    "chain_matrix": matrix,
                    "p95_seconds": p95,
                    "p95_reliable": all(r["p95_reliable"] for r in entries),
                    "repetitions": entries[0]["n"],
                    "exact_only": exact_only,
                    "requires_runtime": requires_runtime,
                })
                continue
            if entries:
                results.append(_invalid_measurement_result(operation))
                continue

        if name == "pair_why":
            entries = by_op.get("pair_on_click", [])
            if _valid_entries(entries):
                matrix = [
                    {
                        "workload": r.get("workload"),
                        "p50_seconds": r.get("p50_s"),
                        "p95_seconds": r.get("p95_s"),
                    }
                    for r in entries
                ]
                p95 = max(r["p95_s"] for r in entries)
                results.append({
                    "operation": name,
                    "tier": tier,
                    "status": "MEASURED",
                    "provenance": "benchmarks/results/latest.json",
                    "chain_matrix": matrix,
                    "p95_seconds": p95,
                    "p95_reliable": all(r["p95_reliable"] for r in entries),
                    "repetitions": entries[0]["n"],
                    "exact_only": exact_only,
                    "requires_runtime": requires_runtime,
                })
                continue
            if entries:
                results.append(_invalid_measurement_result(operation))
                continue

        if name == "historical_h_pair_why":
            results.append({
                "operation": name,
                "tier": tier,
                "status": "UNAVAILABLE",
                "reason": "ALARM_TAXONOMY_NOT_USED_BY_SOURCE",
                "provenance": "docs/adr/0024-deterministic-evidence-synthesis.md",
                "notes": "Production export does not supply operational alarm_type_name or alarm_family; synthetic fixture verified separately",
                "exact_only": exact_only,
                "requires_runtime": requires_runtime,
            })
            continue

        if name == "temporal_delay_pair_why":
            results.append({
                "operation": name,
                "tier": tier,
                "status": "UNAVAILABLE",
                "reason": "PRODUCTION_DELAY_THRESHOLD_NOT_ESTABLISHED",
                "provenance": "IMPLEMENTATION_STATUS.md",
                "notes": "Frozen model and synthetic distribution verified; empirical production threshold blocked by data availability",
                "exact_only": exact_only,
                "requires_runtime": requires_runtime,
            })
            continue

        if name == "tier_2_structural_audit":
            entries = by_op.get("tier_2_structural_audit", [])
            if _valid_entries(entries):
                matrix = [
                    {
                        "workload": r.get("workload"),
                        "p50_seconds": r.get("p50_s"),
                        "p95_seconds": r.get("p95_s"),
                    }
                    for r in entries
                ]
                p95 = max(r["p95_s"] for r in entries)
                results.append({
                    "operation": name,
                    "tier": tier,
                    "status": "MEASURED",
                    "provenance": "benchmarks/results/latest.json",
                    "chain_matrix": matrix,
                    "p95_seconds": p95,
                    "p95_reliable": all(r["p95_reliable"] for r in entries),
                    "repetitions": entries[0]["n"],
                    "exact_only": exact_only,
                    "requires_runtime": requires_runtime,
                    "notes": "Includes exact conductance, candidate cuts, and over-merge verdict",
                })
                continue
            if entries:
                results.append(_invalid_measurement_result(operation))
                continue

        if name == "evidence_attribution":
            results.append({
                "operation": name,
                "tier": tier,
                "status": "NOT_RUN",
                "reason": "NO_ISOLATED_MEASUREMENT",
                "notes": "Executed within the measured Tier-2 Audit path, but has no independent latency measurement.",
                "exact_only": exact_only,
                "requires_runtime": requires_runtime,
            })
            continue

        if name == "attribution_deletion_curve":
            results.append({
                "operation": name,
                "tier": tier,
                "status": "NOT_RUN",
                "reason": "NO_ISOLATED_MEASUREMENT",
                "notes": "Executed within the measured Tier-2 Audit path, but has no independent latency measurement.",
                "exact_only": exact_only,
                "requires_runtime": requires_runtime,
            })
            continue

        review_operation = {
            "review_remove_member": "REMOVE_MEMBER",
            "review_split_chain": "SPLIT_CHAIN",
            "review_move_member": "MOVE_MEMBER",
            "review_merge_chains": "MERGE_CHAINS",
        }.get(name)
        if review_operation:
            summary = next(
                (
                    item
                    for item in (review_data or {}).get("operation_summaries", [])
                    if item.get("operation") == review_operation
                ),
                None,
            )
            required_measurements = (
                "latency_p50_seconds",
                "latency_p95_seconds",
                "latency_p95_reliable",
                "repetitions_per_mutation",
            )
            if summary and _valid_timing(
                summary.get("latency_p50_seconds"),
                summary.get("latency_p95_seconds"),
                summary.get("repetitions_per_mutation"),
                summary.get("latency_p95_reliable"),
            ):
                results.append({
                    "operation": name,
                    "tier": tier,
                    "status": "MEASURED",
                    "scope": (review_data or {}).get("scope", "SYNTHETIC_CORRECTNESS_ONLY"),
                    "provenance": "benchmarks/results/counterfactual-latest.json",
                    "repair_accuracy": summary.get("repair_accuracy"),
                    "ari": summary.get("mean_ari"),
                    "ami": summary.get("mean_ami"),
                    "p50_seconds": summary.get("latency_p50_seconds"),
                    "p95_seconds": summary.get("latency_p95_seconds"),
                    "p95_reliable": summary["latency_p95_reliable"],
                    "repetitions": summary.get("repetitions_per_mutation"),
                    "exact_only": exact_only,
                    "requires_runtime": requires_runtime,
                })
            elif summary and any(summary.get(field) is not None for field in required_measurements):
                results.append(_invalid_measurement_result(operation))
            else:
                results.append({
                    "operation": name,
                    "tier": tier,
                    "status": "NOT_RUN",
                    "reason": "SYNTHETIC_REVIEW_BENCHMARK_NOT_EXECUTED",
                    "exact_only": exact_only,
                    "requires_runtime": requires_runtime,
                })
            continue

        if name == "merge_cross_chain_evidence":
            results.append({
                "operation": name,
                "tier": tier,
                "status": "NOT_RUN",
                "reason": "NO_ISOLATED_MEASUREMENT",
                "notes": "Exercised by the synthetic MERGE fixture, but has no standalone latency measurement.",
                "exact_only": exact_only,
                "requires_runtime": requires_runtime,
            })
            continue

        if name == "review_serialization":
            results.append({
                "operation": name,
                "tier": tier,
                "status": "NOT_RUN",
                "reason": "NO_ISOLATED_MEASUREMENT",
                "notes": "Serialization correctness is covered by tests, but it has no standalone latency measurement.",
                "exact_only": exact_only,
                "requires_runtime": requires_runtime,
            })
            continue

        if name == "review_persistence":
            results.append({
                "operation": name,
                "tier": tier,
                "status": "NOT_RUN",
                "reason": "NO_ISOLATED_PERSISTENCE_MEASUREMENT",
                "notes": "Restart-to-health is recorded separately and does not measure the persistence write path.",
                "exact_only": exact_only,
                "requires_runtime": requires_runtime,
            })
            continue

        if name == "review_restart_hydration":
            hydration = (runtime_data or {}).get("persisted_review_hydration")
            runtime_repetitions = (runtime_data or {}).get("repetitions")
            if isinstance(hydration, dict) and _valid_timing(
                hydration.get("p50_s"),
                hydration.get("p95_s"),
                runtime_repetitions,
                hydration.get("p95_reliable"),
            ):
                results.append({
                    "operation": name,
                    "tier": tier,
                    "status": "MEASURED",
                    "scope": runtime_data.get("scope", "LOCAL_DOCKER_RUNTIME_ONLY"),
                    "provenance": "benchmarks/results/runtime-review-latest.json",
                    "hydration_p50_seconds": round(hydration["p50_s"], 4),
                    "hydration_p95_seconds": round(hydration["p95_s"], 4),
                    "p95_seconds": round(hydration["p95_s"], 4),
                    "p95_reliable": hydration["p95_reliable"],
                    "repetitions": runtime_repetitions,
                    "notes": f"Repository-backed Review hydration after API restart measured over {runtime_repetitions} iterations",
                    "exact_only": exact_only,
                    "requires_runtime": requires_runtime,
                })
            elif hydration is not None:
                results.append(_invalid_measurement_result(operation))
            else:
                results.append({
                    "operation": name,
                    "tier": tier,
                    "status": "NOT_RUN",
                    "reason": "DOCKER_RUNTIME_BENCHMARK_NOT_EXECUTED",
                    "exact_only": exact_only,
                    "requires_runtime": requires_runtime,
                })
            continue

        # Fallback for any unexpected operation
        results.append({
            "operation": name,
            "tier": tier,
            "status": "NOT_RUN",
            "reason": "BENCHMARK_NOT_EXECUTED",
            "exact_only": exact_only,
            "requires_runtime": requires_runtime,
        })

    return results
