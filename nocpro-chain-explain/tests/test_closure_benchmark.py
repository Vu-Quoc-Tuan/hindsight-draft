import json

from benchmarks.closure import (
    LARGE_CHAIN_ANTI_ALL_PAIRS_GATE,
    TARGET_CHAIN_SIZES,
    closure_manifest,
    empty_closure_results,
)
from benchmarks.run_closure_benchmark import run


def test_closure_manifest_pins_1072_fail_closed_gate():
    manifest = closure_manifest()
    assert LARGE_CHAIN_ANTI_ALL_PAIRS_GATE in TARGET_CHAIN_SIZES
    assert manifest["anti_all_pairs_gate"] == {
        "chain_size": 1072,
        "tier": "Tier-1B",
        "requirement": "dense_pairwise_fallback_forbidden",
        "verification": "tests/spec_sanity/test_tier1_execution_boundary.py",
    }
    assert "temporal_delay_pair_why" in {
        item["name"] for item in manifest["operations"]
    }
    assert all(item["status"] == "NOT_RUN" for item in empty_closure_results())


def test_closure_manifest_writer_does_not_execute_benchmark(tmp_path):
    output = run(tmp_path / "closure.json")
    assert output.exists()
    assert '"contract": "closure-benchmark-v1"' in output.read_text()


def test_closure_manifest_requires_artifacts_for_review_measurements(tmp_path):
    output = run(tmp_path / "closure.json", results_dir=tmp_path)
    payload = json.loads(output.read_text())
    review = next(item for item in payload["results"] if item["operation"] == "review_move_member")
    attribution = next(item for item in payload["results"] if item["operation"] == "evidence_attribution")
    persistence = next(item for item in payload["results"] if item["operation"] == "review_persistence")
    assert review["status"] == "NOT_RUN"
    assert attribution["reason"] == "NO_ISOLATED_MEASUREMENT"
    assert persistence["reason"] == "NO_ISOLATED_PERSISTENCE_MEASUREMENT"


def test_closure_manifest_reads_review_measurements_from_artifact(tmp_path):
    (tmp_path / "counterfactual-latest.json").write_text(json.dumps({
        "scope": "SYNTHETIC_CORRECTNESS_ONLY",
        "operation_summaries": [{
            "operation": "MOVE_MEMBER",
            "repair_accuracy": 1.0,
            "mean_ari": 1.0,
            "mean_ami": 1.0,
            "latency_p50_seconds": 0.1,
            "latency_p95_seconds": 0.2,
            "latency_p95_reliable": True,
            "repetitions_per_mutation": 20,
        }],
    }))
    output = run(tmp_path / "closure.json", results_dir=tmp_path)
    payload = json.loads(output.read_text())
    move = next(item for item in payload["results"] if item["operation"] == "review_move_member")
    remove = next(item for item in payload["results"] if item["operation"] == "review_remove_member")
    assert move["status"] == "MEASURED"
    assert move["provenance"] == "benchmarks/results/counterfactual-latest.json"
    assert move["p95_seconds"] == 0.2
    assert remove["status"] == "NOT_RUN"


def test_closure_manifest_reads_isolated_stage_measurements(tmp_path):
    (tmp_path / "isolated-latest.json").write_text(json.dumps({
        "contract": "isolated-closure-benchmark-v1",
        "measurements": [
            {
                "operation": "evidence_attribution",
                "scope": "LOCAL_RAW_EXPORT_PERFORMANCE_ONLY",
                "workload": "chain-1072",
                "p50_seconds": 0.01,
                "p95_seconds": 0.01,
                "p95_reliable": True,
                "repetitions": 20,
                "samples_seconds": [0.01] * 20,
            },
            {
                "operation": "review_serialization",
                "scope": "SYNTHETIC_CORRECTNESS_ONLY",
                "workload": "counterfactual_merge",
                "p50_seconds": 0.001,
                "p95_seconds": 0.001,
                "p95_reliable": True,
                "repetitions": 20,
                "samples_seconds": [0.001] * 20,
            },
        ],
    }))
    output = run(tmp_path / "closure.json", results_dir=tmp_path)
    payload = json.loads(output.read_text())
    attribution = next(item for item in payload["results"] if item["operation"] == "evidence_attribution")
    serialization = next(item for item in payload["results"] if item["operation"] == "review_serialization")
    deletion = next(item for item in payload["results"] if item["operation"] == "attribution_deletion_curve")
    assert attribution["status"] == "MEASURED"
    assert attribution["scope"] == "LOCAL_RAW_EXPORT_PERFORMANCE_ONLY"
    assert attribution["p95_seconds"] == 0.01
    assert serialization["status"] == "MEASURED"
    assert deletion["status"] == "NOT_RUN"


def test_closure_manifest_reads_isolated_review_persistence(tmp_path):
    (tmp_path / "runtime-review-latest.json").write_text(json.dumps({
        "scope": "LOCAL_DOCKER_RUNTIME_ONLY",
        "repetitions": 20,
        "review_persistence": {
            "p50_s": 0.01,
            "p95_s": 0.01,
            "p95_reliable": True,
            "samples_s": [0.01] * 20,
        },
    }))
    output = run(tmp_path / "closure.json", results_dir=tmp_path)
    payload = json.loads(output.read_text())
    persistence = next(item for item in payload["results"] if item["operation"] == "review_persistence")
    assert persistence["status"] == "MEASURED"
    assert persistence["scope"] == "LOCAL_DOCKER_RUNTIME_ONLY"
    assert persistence["p95_seconds"] == 0.01
    assert persistence["provenance"] == "benchmarks/results/runtime-review-latest.json"


def test_closure_manifest_rejects_runtime_measurement_without_all_raw_samples(tmp_path):
    (tmp_path / "runtime-review-latest.json").write_text(json.dumps({
        "scope": "LOCAL_DOCKER_RUNTIME_ONLY",
        "repetitions": 20,
        "review_persistence": {
            "p50_s": 0.01,
            "p95_s": 0.02,
            "p95_reliable": True,
            "samples_s": [0.01] * 19,
        },
    }))
    output = run(tmp_path / "closure.json", results_dir=tmp_path)
    payload = json.loads(output.read_text())
    persistence = next(item for item in payload["results"] if item["operation"] == "review_persistence")
    assert persistence["status"] == "NOT_RUN"
    assert persistence["reason"] == "INVALID_OR_INCOMPLETE_BENCHMARK_EVIDENCE"


def test_closure_manifest_rejects_summary_that_does_not_match_raw_samples(tmp_path):
    (tmp_path / "isolated-latest.json").write_text(json.dumps({
        "measurements": [{
            "operation": "review_serialization",
            "scope": "SYNTHETIC_CORRECTNESS_ONLY",
            "p50_seconds": 0.01,
            "p95_seconds": 9.0,
            "p95_reliable": True,
            "repetitions": 20,
            "samples_seconds": [0.01] * 20,
        }],
    }))
    output = run(tmp_path / "closure.json", results_dir=tmp_path)
    payload = json.loads(output.read_text())
    serialization = next(item for item in payload["results"] if item["operation"] == "review_serialization")
    assert serialization["status"] == "NOT_RUN"
    assert serialization["reason"] == "INVALID_OR_INCOMPLETE_BENCHMARK_EVIDENCE"


def test_closure_manifest_does_not_claim_reliable_p95_without_reliable_samples(tmp_path):
    (tmp_path / "latest.json").write_text(json.dumps({
        "results": [{
            "operation": "pair_on_click",
            "workload": "chain-58",
            "p50_s": 0.01,
            "p95_s": 0.02,
            "p95_reliable": False,
            "n": 1,
        }],
    }))
    output = run(tmp_path / "closure.json", results_dir=tmp_path)
    payload = json.loads(output.read_text())
    pair_why = next(item for item in payload["results"] if item["operation"] == "pair_why")
    assert pair_why["status"] == "MEASURED"
    assert pair_why["p95_reliable"] is False


def test_closure_manifest_requires_complete_review_timing(tmp_path):
    (tmp_path / "counterfactual-latest.json").write_text(json.dumps({
        "operation_summaries": [{"operation": "MOVE_MEMBER"}],
    }))
    output = run(tmp_path / "closure.json", results_dir=tmp_path)
    payload = json.loads(output.read_text())
    move = next(item for item in payload["results"] if item["operation"] == "review_move_member")
    assert move["status"] == "NOT_RUN"
    assert move["reason"] == "SYNTHETIC_REVIEW_BENCHMARK_NOT_EXECUTED"


def test_closure_manifest_rejects_invalid_timing_and_runtime_defaults(tmp_path):
    (tmp_path / "latest.json").write_text(json.dumps({
        "results": [{
            "operation": "pair_on_click",
            "workload": "chain-1072",
            "p50_s": 2.0,
            "p95_s": 1.0,
            "p95_reliable": True,
            "n": 0,
        }],
    }))
    (tmp_path / "runtime-review-latest.json").write_text(json.dumps({
        "persisted_review_hydration": {
            "p50_s": 0.1,
            "p95_s": 0.2,
            # A missing reliability flag/repetition must never become True/20 by default.
        },
    }))
    output = run(tmp_path / "closure.json", results_dir=tmp_path)
    payload = json.loads(output.read_text())
    pair_why = next(item for item in payload["results"] if item["operation"] == "pair_why")
    hydration = next(item for item in payload["results"] if item["operation"] == "review_restart_hydration")
    assert pair_why == {
        "operation": "pair_why",
        "tier": "Tier-1B",
        "status": "NOT_RUN",
        "reason": "INVALID_OR_INCOMPLETE_BENCHMARK_EVIDENCE",
        "exact_only": False,
        "requires_runtime": False,
    }
    assert hydration["status"] == "NOT_RUN"
    assert hydration["reason"] == "INVALID_OR_INCOMPLETE_BENCHMARK_EVIDENCE"
