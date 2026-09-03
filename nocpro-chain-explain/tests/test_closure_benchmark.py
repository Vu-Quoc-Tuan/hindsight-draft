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
