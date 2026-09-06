from __future__ import annotations

from benchmarks.run_isolated_closure_benchmark import file_provenance, measurement_payload
from benchmarks.harness import TimingResult


def test_measurement_payload_preserves_samples_and_scope() -> None:
    timing = TimingResult(
        operation="evidence_attribution",
        workload="chain-1072",
        durations_seconds=[0.01] * 20,
    )
    payload = measurement_payload(
        timing,
        scope="LOCAL_RAW_EXPORT_PERFORMANCE_ONLY",
    )
    assert payload == {
        "operation": "evidence_attribution",
        "scope": "LOCAL_RAW_EXPORT_PERFORMANCE_ONLY",
        "workload": "chain-1072",
        "repetitions": 20,
        "p50_seconds": 0.01,
        "p95_seconds": 0.01,
        "p95_reliable": True,
        "samples_seconds": [0.01] * 20,
    }


def test_file_provenance_uses_relative_path_and_content_hash(tmp_path, monkeypatch) -> None:
    source = tmp_path / "fixture.json"
    source.write_text('{"status":"AVAILABLE"}\n')
    monkeypatch.setattr(
        "benchmarks.run_isolated_closure_benchmark.WORKSPACE_ROOT",
        tmp_path,
    )
    evidence = file_provenance(source)
    assert evidence["path"] == "fixture.json"
    assert len(evidence["sha256"]) == 64
