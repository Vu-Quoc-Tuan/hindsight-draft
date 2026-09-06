from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.run_runtime_review_benchmark import (
    observed_nearest_rank,
    persistence_payload,
)


def test_observed_nearest_rank_uses_the_95th_observed_value() -> None:
    values = [0.1] * 19 + [9.9]
    assert observed_nearest_rank(values) == 0.1
    assert observed_nearest_rank(values, 0.96) == 9.9


def test_persistence_payload_clones_identity_under_a_unique_job_id() -> None:
    template = {
        "job_id": "original",
        "chain_id": "C1",
        "status": "SUCCEEDED",
        "progress_percent": 100,
        "cache_hit": False,
        "cache_fingerprint": "a" * 64,
        "identity": {"snapshot_id": "S1", "snapshot_version": "v1"},
        "result": {"status": "AVAILABLE"},
        "error": None,
    }
    payload = persistence_payload(template, job_id="benchmark-copy")
    assert payload["job_id"] == "benchmark-copy"
    assert payload["snapshot_id"] == "S1"
    assert payload["snapshot_version"] == "v1"
    assert payload["chain_id"] == "C1"
    assert payload["result"] == {"status": "AVAILABLE"}
