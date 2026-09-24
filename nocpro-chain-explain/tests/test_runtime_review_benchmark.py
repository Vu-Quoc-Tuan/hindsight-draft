from __future__ import annotations

import sys
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.run_runtime_review_benchmark import (
    BenchmarkOptions,
    _assert_provider_disabled,
    _inspect_stack,
    _run_read_only,
    _verified_review_identity,
    observed_nearest_rank,
    persistence_payload,
    parse_options,
    run,
    summarize_samples,
)


def test_observed_nearest_rank_uses_the_95th_observed_value() -> None:
    values = [0.1] * 19 + [9.9]
    assert observed_nearest_rank(values) == 0.1
    assert observed_nearest_rank(values, 0.96) == 9.9


def test_empty_sample_summary_keeps_errors_without_fabricating_latency() -> None:
    summary = summarize_samples([], ["TimeoutError", "TimeoutError", "HTTPError"])
    assert summary == {
        "sample_count": 0,
        "error_count": 3,
        "error_types": {"HTTPError": 1, "TimeoutError": 2},
        "p50_s": None,
        "p95_s": None,
        "samples_s": [],
    }


def test_cli_defaults_to_read_only_and_requires_identity() -> None:
    options = parse_options(
        ["--snapshot-id", "S1", "--snapshot-version", "v1"]
    )
    assert options.mode == "read-only"
    assert options.repetitions == 30
    assert options.warmups == 5


def test_acceptance_restart_requires_explicit_disruption_and_isolated_target() -> None:
    args = [
        "--mode", "acceptance-restart",
        "--snapshot-id", "S1",
        "--snapshot-version", "v1",
        "--compose-project", "hindsight-acceptance-test",
        "--database-url", "postgresql://user:secret@127.0.0.1:55432/test_db",
    ]
    with pytest.raises(ValueError, match="--allow-disruption"):
        parse_options(args)


@pytest.mark.parametrize(
    "api_url",
    ["file:///etc/passwd", "http://user:secret@127.0.0.1:8800", "http://127.0.0.1:8800/api/v1"],
)
def test_api_url_rejects_non_origin_and_embedded_credentials(api_url: str) -> None:
    with pytest.raises(ValueError, match=r"HTTP\(S\) origin"):
        parse_options(
            ["--api-url", api_url, "--snapshot-id", "S1", "--snapshot-version", "v1"]
        )


def test_read_only_benchmark_uses_catalog_and_pinned_overview_gets_only(
    monkeypatch,
) -> None:
    options = BenchmarkOptions(
        mode="read-only",
        api_url="http://127.0.0.1:8800",
        chain_id="C1",
        snapshot_id="S1",
        snapshot_version="v1",
        repetitions=2,
        warmups=0,
        output=Path("/tmp/report.json"),
        overwrite=False,
        allow_disruption=False,
        compose_project=None,
        database_url=None,
    )
    calls: list[tuple[str, str, dict[str, str] | None]] = []

    def forbid_subprocess(*_args, **_kwargs):
        raise AssertionError("read-only mode must not invoke Docker or other subprocesses")

    monkeypatch.setattr("benchmarks.run_runtime_review_benchmark.subprocess.run", forbid_subprocess)

    def fake_get(api_url: str, path: str, *, headers=None):
        calls.append((api_url, path, headers))
        if path == "/api/v1/snapshots":
            return {
                "active_snapshot_id": "S1",
                "active_snapshot_version": "v1",
                "snapshots": [],
            }, 0.01
        assert path == "/api/v1/chains/C1/overview-cards"
        assert headers == {
            "X-Nocpro-Snapshot-Id": "S1",
            "X-Nocpro-Snapshot-Version": "v1",
        }
        return {
            "snapshot_id": "S1",
            "snapshot_version": "v1",
            "chain_id": "C1",
            "status": "READY",
        }, 0.02

    result = _run_read_only(options, get=fake_get)

    assert result["safety"]["http_methods"] == ["GET"]
    assert result["safety"]["target_stack_mutations_requested"] is False
    assert result["safety"]["benchmark_report_file_written"] is True
    assert result["origin"] == "TEST_INJECTED_RESPONSE"
    assert result["production_validation"] == "NOT_ESTABLISHED"
    assert result["measurements"]["overview_projection"]["sample_count"] == 2
    assert result["measurements"]["concurrent_overview_10"]["sample_count"] == 20
    assert result["measurements"]["overview_projection_statuses"] == {"READY": 22}
    assert result["measurements"]["projection_versions"] == {"UNKNOWN": 22}
    assert all(path != "/api/v1/chains" for _, path, _ in calls)
    assert calls[0][1] == "/api/v1/snapshots"
    assert all(method_path != "/api/v1/snapshots/select" for _, method_path, _ in calls)


def test_read_only_preflight_fails_closed_on_changed_active_identity() -> None:
    options = BenchmarkOptions(
        mode="read-only",
        api_url="http://127.0.0.1:8800",
        chain_id="C1",
        snapshot_id="S1",
        snapshot_version="v1",
        repetitions=1,
        warmups=0,
        output=Path("/tmp/report.json"),
        allow_disruption=False,
        overwrite=False,
        compose_project=None,
        database_url=None,
    )

    def fake_get(_api_url: str, _path: str, *, headers=None):
        return {
            "active_snapshot_id": "S2",
            "active_snapshot_version": "v1",
            "snapshots": [],
        }, 0.01

    try:
        _run_read_only(options, get=fake_get)
    except RuntimeError as exc:
        assert "active snapshot identity" in str(exc)
    else:
        raise AssertionError("benchmark must not silently run against another active snapshot")


def test_existing_report_is_not_overwritten_without_explicit_flag(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    output.write_text("preserve-me", encoding="utf-8")
    options = BenchmarkOptions(
        mode="read-only",
        api_url="http://127.0.0.1:8800",
        chain_id="C1",
        snapshot_id="S1",
        snapshot_version="v1",
        repetitions=30,
        warmups=0,
        output=output,
        overwrite=False,
        allow_disruption=False,
        compose_project=None,
        database_url=None,
    )
    with pytest.raises(FileExistsError, match="already exists"):
        run(options)
    assert output.read_text(encoding="utf-8") == "preserve-me"


def test_acceptance_container_provider_check_never_exposes_environment_value(
    monkeypatch,
) -> None:
    sentinel = "NEVER-PRINT-THIS-TEST-VALUE"
    monkeypatch.setattr(
        "benchmarks.run_runtime_review_benchmark.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=json.dumps([f"AI_API_KEY={sentinel}"])
        ),
    )
    with pytest.raises(RuntimeError, match="AI_API_KEY") as error:
        _assert_provider_disabled("container-id")
    assert sentinel not in str(error.value)


def test_acceptance_refuses_non_acceptance_project_before_docker(monkeypatch, tmp_path: Path) -> None:
    options = BenchmarkOptions(
        mode="acceptance-restart",
        api_url="http://127.0.0.1:8800",
        chain_id="C1",
        snapshot_id="S1",
        snapshot_version="v1",
        repetitions=30,
        warmups=0,
        output=tmp_path / "report.json",
        overwrite=False,
        allow_disruption=True,
        compose_project="production",
        database_url="postgresql://user:secret@127.0.0.1:55432/test_db",
    )
    monkeypatch.setattr(
        "benchmarks.run_runtime_review_benchmark.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Docker must not be called for a non-acceptance project")
        ),
    )
    with pytest.raises(ValueError, match="acceptance project"):
        _inspect_stack(options)


def test_persisted_acceptance_review_requires_full_identity_and_revision() -> None:
    options = BenchmarkOptions(
        mode="acceptance-restart",
        api_url="http://127.0.0.1:8800",
        chain_id="C1",
        snapshot_id="S1",
        snapshot_version="v1",
        repetitions=30,
        warmups=0,
        output=Path("/tmp/report.json"),
        overwrite=False,
        allow_disruption=True,
        compose_project="hindsight-acceptance-test",
        database_url="postgresql://user:secret@127.0.0.1:55432/test_db",
    )
    payload = {
        "analysis_identity": {
            "identity_version": "analysis-identity-v1",
            "snapshot_id": "S1",
            "snapshot_version": "v1",
            "chain_id": "C1",
            "topology_version": "topo-1",
            "analysis_config_version": "cfg-1",
            "review_config_version": "review-cfg-1",
            "pipeline_version": "pipeline-1",
            "input_fingerprint": "fingerprint-1",
        },
        "identity": {
            "snapshot_id": "S1",
            "snapshot_version": "v1",
            "chain_id": "C1",
            "topology_version": "topo-1",
            "analysis_version": "cfg-1",
            "config_version": "review-cfg-1",
            "engine_version": "pipeline-1",
            "tier1b_artifact_fingerprint": "fingerprint-1",
        },
        "artifact_revision": {
            "resource_kind": "counterfactual_review",
            "fingerprint": "review-fingerprint",
        },
    }
    identity, revision = _verified_review_identity(payload, options)
    assert identity["chain_id"] == "C1"
    assert revision["resource_kind"] == "counterfactual_review"
    payload["analysis_identity"]["review_config_version"] = "stale"
    with pytest.raises(RuntimeError, match="identity"):
        _verified_review_identity(payload, options)


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
