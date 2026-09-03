"""Consolidated closure-benchmark manifest and report shape.

This module deliberately does not create data, choose thresholds, or turn an
unavailable capability into a fallback.  It makes the benchmark matrix
explicit so a run report can distinguish a measured operation from one that
is intentionally unavailable or not run in the current environment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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
