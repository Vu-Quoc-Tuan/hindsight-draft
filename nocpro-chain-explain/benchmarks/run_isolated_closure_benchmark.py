"""Measure closure stages that are hidden inside larger benchmark operations.

The raw-export attribution measurements reuse an already-built exact indexed
statistics artifact, matching the Tier-2 call path. Cross-chain evidence and
Review serialization use the explicit synthetic MERGE fixture. The report is
performance evidence only; it never calibrates a production policy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/analysis-worker"))

from benchmarks.benchmark_counterfactual import (
    CONFIG as COUNTERFACTUAL_CONFIG,
    FIXTURES,
    _expected_recommendation,
    _fixture,
    _review,
)
from benchmarks.harness import TimingResult, measure
from benchmarks.run_benchmark import ANALYSIS_CONFIG, _replay
from channels import evaluate_chain_indexed, exact_cross_chain_evidence
from libs.contracts import load_validated_package
from tier2.attribution_evaluation import evaluate_attribution_deletion
from tier2.counterfactual.public_contract import public_review_result
from tier2.evidence_attribution import (
    AttributionExecutionPolicy,
    build_exact_attribution_support,
    compute_evidence_coverage_attribution,
)


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "benchmarks" / "results" / "isolated-latest.json"
WORKSPACE_ROOT = ROOT.parent


def file_provenance(path: Path) -> dict[str, str]:
    """Identify an exact local benchmark input without embedding machine paths."""
    return {
        "path": path.relative_to(WORKSPACE_ROOT).as_posix(),
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def measurement_payload(timing: TimingResult, *, scope: str) -> dict[str, object]:
    """Return one self-contained timing with the raw observations retained."""
    return {
        "operation": timing.operation,
        "scope": scope,
        "workload": timing.workload,
        "repetitions": timing.n,
        "p50_seconds": timing.p50,
        "p95_seconds": timing.p95,
        "p95_reliable": timing.p95_reliable,
        "samples_seconds": timing.durations_seconds,
    }


def run(*, repetitions: int = 20) -> dict[str, object]:
    if repetitions < 20:
        raise ValueError("isolated closure benchmark requires at least 20 repetitions")

    package = _replay()
    chain_id = max(
        package.chains,
        key=lambda candidate: package.chains[candidate].member_count,
    )
    members = tuple(package.members_of(chain_id))
    workload = f"raw_chain_{chain_id}_n_{len(members)}"
    indexed = evaluate_chain_indexed(
        package,
        chain_id,
        silent_gap_seconds=int(
            ANALYSIS_CONFIG.value("temporal.burst.gap_seconds")
        ),
        d_max=int(ANALYSIS_CONFIG.value("dependency.max_hop")),
    )
    policy = AttributionExecutionPolicy(
        exact_max_members=int(ANALYSIS_CONFIG.value("audit.exact_max_members"))
    )

    def attribute():
        support = build_exact_attribution_support(members, indexed.statistics)
        return compute_evidence_coverage_attribution(
            chain_id,
            members,
            indexed.statistics,
            policy=policy,
            exact_support=support,
        )

    attribution_check = attribute()
    if (
        attribution_check.status.value != "AVAILABLE"
        or attribution_check.mode.value != "EXACT"
    ):
        raise RuntimeError("raw attribution benchmark input is not AVAILABLE/EXACT")
    attribution_timing = measure(
        "evidence_attribution",
        workload,
        attribute,
        repetitions=repetitions,
        track_memory=False,
    )
    support = build_exact_attribution_support(members, indexed.statistics)
    attribution = compute_evidence_coverage_attribution(
        chain_id,
        members,
        indexed.statistics,
        policy=policy,
        exact_support=support,
    )
    deletion_check = evaluate_attribution_deletion(
        attribution,
        members,
        indexed.statistics,
        config=ANALYSIS_CONFIG.attribution_evaluation,
        exact_support=support,
    )
    if deletion_check.status.value != "AVAILABLE" or deletion_check.mode.value != "EXACT":
        raise RuntimeError("raw deletion benchmark input is not AVAILABLE/EXACT")
    deletion_timing = measure(
        "attribution_deletion_curve",
        workload,
        lambda: evaluate_attribution_deletion(
            attribution,
            members,
            indexed.statistics,
            config=ANALYSIS_CONFIG.attribution_evaluation,
            exact_support=support,
        ),
        repetitions=repetitions,
        track_memory=False,
    )

    merge_payload, merge_expected = _fixture("counterfactual_merge")
    merge_package = load_validated_package(merge_payload)
    left_chain_id, right_chain_id = merge_expected["expected_review"][
        "merged_chain_ids"
    ]
    cross_check = exact_cross_chain_evidence(
        merge_package, left_chain_id, right_chain_id
    )
    expected_cross_pairs = (
        len(merge_package.members_of(left_chain_id))
        * len(merge_package.members_of(right_chain_id))
    )
    if (
        cross_check.cross_pair_count != expected_cross_pairs
        or cross_check.cross_audit_edge_count <= 0
    ):
        raise RuntimeError("synthetic MERGE cross-chain evidence failed its oracle")
    cross_timing = measure(
        "merge_cross_chain_evidence",
        "synthetic_counterfactual_merge_v1",
        lambda: exact_cross_chain_evidence(
            merge_package, left_chain_id, right_chain_id
        ),
        repetitions=repetitions,
        track_memory=False,
    )
    review = _review(merge_payload, merge_expected["mutated_chain_id"])
    if _expected_recommendation(review, merge_expected) is None:
        raise RuntimeError("synthetic MERGE Review did not retain the expected recommendation")
    serialized_review = public_review_result(review)
    if (
        serialized_review.get("status") != "AVAILABLE"
        or serialized_review.get("calibration_status") != "SYNTHETIC_ONLY"
    ):
        raise RuntimeError("synthetic MERGE Review serialization failed its contract")
    serialization_timing = measure(
        "review_serialization",
        "synthetic_counterfactual_merge_v1",
        lambda: public_review_result(review),
        repetitions=repetitions,
        track_memory=False,
    )

    report = {
        "contract": "isolated-closure-benchmark-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_provenance": {
            "snapshot_id": package.snapshot.snapshot_id,
            "snapshot_version": package.snapshot.snapshot_version,
            "analysis_config_version": ANALYSIS_CONFIG.config_version,
            "counterfactual_config_version": (
                COUNTERFACTUAL_CONFIG.counterfactual.config_version
            ),
            "raw_export": file_provenance(
                WORKSPACE_ROOT / "nocpro-mock/datasets/raw/alarm/alarm_data.csv"
            ),
            "analysis_config": file_provenance(
                ROOT / "config/thresholds/v1.yaml"
            ),
            "counterfactual_config": file_provenance(
                ROOT / "config/thresholds/e2e-counterfactual.yaml"
            ),
            "merge_snapshot": file_provenance(
                FIXTURES / "counterfactual_merge/snapshot_000.json"
            ),
            "merge_assertions": file_provenance(
                FIXTURES / "counterfactual_merge/expected_assertions.yaml"
            ),
        },
        "measurements": [
            measurement_payload(
                attribution_timing,
                scope="LOCAL_RAW_EXPORT_PERFORMANCE_ONLY",
            ),
            measurement_payload(
                deletion_timing,
                scope="LOCAL_RAW_EXPORT_PERFORMANCE_ONLY",
            ),
            measurement_payload(
                cross_timing,
                scope="SYNTHETIC_CORRECTNESS_ONLY",
            ),
            measurement_payload(
                serialization_timing,
                scope="SYNTHETIC_CORRECTNESS_ONLY",
            ),
        ],
    }
    return report


def write_report(
    output: Path = RESULTS_PATH,
    *,
    repetitions: int = 20,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(run(repetitions=repetitions), indent=2) + "\n",
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    result = write_report(
        repetitions=int(os.environ.get("BENCHMARK_ISOLATED_REPETITIONS", "20"))
    )
    print(f"Isolated closure benchmark written to {result}")
