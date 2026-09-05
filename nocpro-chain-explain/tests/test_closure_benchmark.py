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
