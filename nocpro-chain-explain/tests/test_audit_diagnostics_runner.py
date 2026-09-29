from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from audit_diagnostics import runner as diagnostic_runner
from audit_diagnostics.capture import DiagnosticLimitError
from audit_diagnostics.contracts import DiagnosticReport
from audit_diagnostics.runner import (
    DiagnosticInputError,
    DiagnosticManifestMismatch,
    DiagnosticPreparationError,
    DiagnosticTimeoutError,
    prepare,
    run_manifest,
    run_manifest_inline,
)
from audit_diagnostics.capture import capture_exact_audit_inputs
from audit_diagnostics.coverage import aggregate_coverage
from audit_diagnostics.contracts import ResourceLimits
from audit_diagnostics.scope import load_scope_policy
from audit_diagnostics.registry import resolve_execution_registry
from audit_diagnostics.runner import _coverage_pair_examples
from audit_diagnostics.serialization import canonical_json_bytes, semantic_result_digest, sha256_bytes
from configuration import load_analysis_config
from libs.contracts import load_validated_package
from tier2 import AuditExecutionPolicy, analyze_structural_audit


REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_CONFIG = REPO_ROOT / "config/thresholds/v1.yaml"
SCOPE_POLICY = REPO_ROOT / "config/audit_diagnostics/scope-v1.yaml"
BASE_EXPERIMENT = REPO_ROOT / "config/audit_diagnostics/experiment-v1.json"
CHAIN_ID = "SYN-CHAIN-T0"


@pytest.fixture
def snapshot_file(mock_root: Path, tmp_path: Path) -> Path:
    source = mock_root / "docs/examples/synthetic/temporal_topology/snapshot_000.json"
    if not source.is_file():
        pytest.skip("canonical temporal_topology snapshot fixture is unavailable")
    target = tmp_path / "snapshot.json"
    shutil.copyfile(source, target)
    return target


def _prepare(snapshot_file: Path, tmp_path: Path, *, experiment: Path = BASE_EXPERIMENT):
    return prepare(
        snapshot_file,
        CHAIN_ID,
        ANALYSIS_CONFIG,
        experiment,
        tmp_path / "runs",
        SCOPE_POLICY,
    )


def test_prepare_and_cli_run_publish_reproducible_strict_artifacts(snapshot_file, tmp_path):
    manifest, run_dir = _prepare(snapshot_file, tmp_path)
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "manifest.sha256").is_file()
    assert not (run_dir / "report.json").exists()
    assert manifest.variants[0].variant_id == "baseline"
    assert manifest.materiality_policy.delta_phi is None
    assert isinstance(manifest.source_binding.dirty, bool)
    with tempfile.TemporaryDirectory(prefix="audit-diagnostic-first-run-") as first_output:
        direct_report = run_manifest_inline(run_dir / "manifest.json", first_output)

    command = [
        sys.executable,
        str(REPO_ROOT / "benchmarks/run_audit_diagnostics.py"),
        "run",
        "--manifest",
        str(run_dir / "manifest.json"),
    ]
    first = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    response = json.loads(first.stdout)
    report_payload = json.loads((run_dir / "report.json").read_text())
    assert response["status"] == "COMPLETE"
    assert report_payload["complete"] is True
    assert report_payload["semantic_result_digest"] == direct_report.semantic_result_digest
    json.dumps(report_payload, allow_nan=False)
    assert report_payload["semantic_result_digest"] == semantic_result_digest(
        DiagnosticReport.model_validate(report_payload)
    )
    assert report_payload["materiality_policy"]["delta_phi"] is None
    assert all(variant["computation_status"] == "EXACT" for variant in report_payload["variants"])
    assert all(score["status"] == "SKIPPED_SMALL_CHAIN"
               for variant in report_payload["variants"]
               for score in variant["candidate_scores"])
    assert "SKIPPED_SMALL_CHAIN" in (run_dir / "report.md").read_text()
    with pytest.raises(DiagnosticPreparationError, match="already exist"):
        run_manifest(run_dir / "manifest.json")


def test_prepare_freezes_all_inputs_and_run_rejects_snapshot_byte_change(snapshot_file, tmp_path):
    _, run_dir = _prepare(snapshot_file, tmp_path)
    snapshot_file.write_bytes(snapshot_file.read_bytes() + b"\n")
    with pytest.raises(DiagnosticManifestMismatch, match="snapshot bytes changed"):
        run_manifest(run_dir / "manifest.json")
    assert not (run_dir / "report.json").exists()
    assert not (run_dir / "report.md").exists()


def test_recomputed_manifest_checksum_cannot_override_frozen_experiment(snapshot_file, tmp_path):
    _, run_dir = _prepare(snapshot_file, tmp_path)
    manifest_path = run_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text())
    payload["limits"]["max_pairs"] = 1
    raw = canonical_json_bytes(payload)
    manifest_path.write_bytes(raw + b"\n")
    (run_dir / "manifest.sha256").write_text(sha256_bytes(raw) + "\n")

    with pytest.raises(DiagnosticManifestMismatch, match="resource limits do not match"):
        run_manifest(manifest_path)
    assert not (run_dir / "report.json").exists()
    assert not (run_dir / "report.md").exists()


@pytest.mark.parametrize(
    ("changed_input", "expected_error"),
    [
        ("analysis", "analysis config changed"),
        ("scope", "scope applicability policy changed"),
        ("experiment", "experiment definition changed"),
    ],
)
def test_run_rejects_changed_frozen_config_files(
    snapshot_file, tmp_path, changed_input, expected_error
):
    analysis_file = tmp_path / "analysis.yaml"
    scope_file = tmp_path / "scope.yaml"
    experiment_file = tmp_path / "experiment.json"
    shutil.copyfile(ANALYSIS_CONFIG, analysis_file)
    shutil.copyfile(SCOPE_POLICY, scope_file)
    shutil.copyfile(BASE_EXPERIMENT, experiment_file)
    _, run_dir = prepare(
        snapshot_file,
        CHAIN_ID,
        analysis_file,
        experiment_file,
        tmp_path / "runs",
        scope_file,
    )

    target = {
        "analysis": analysis_file,
        "scope": scope_file,
        "experiment": experiment_file,
    }[changed_input]
    if changed_input == "scope":
        target.write_text(target.read_text().replace('policy_version: "1"', 'policy_version: "2"'))
    else:
        target.write_bytes(target.read_bytes() + b"\n# changed after prepare\n")

    with pytest.raises(DiagnosticManifestMismatch, match=expected_error):
        run_manifest_inline(run_dir / "manifest.json", tmp_path / "worker-output")


def test_run_rejects_changed_relevant_source_digest(snapshot_file, tmp_path, monkeypatch):
    _, run_dir = _prepare(snapshot_file, tmp_path)
    current = diagnostic_runner._current_source_binding()
    first_source = sorted(current["file_digests"])[0]
    current["file_digests"][first_source] = "0" * 64
    monkeypatch.setattr(
        diagnostic_runner, "_current_source_binding", lambda: current
    )

    with pytest.raises(DiagnosticManifestMismatch, match="relevant source file set or content changed"):
        run_manifest_inline(run_dir / "manifest.json", tmp_path / "worker-output")


def test_member_limit_fails_before_manifest_is_created(snapshot_file, tmp_path):
    experiment = json.loads(BASE_EXPERIMENT.read_text())
    experiment["limits"]["max_members"] = 1
    experiment_file = tmp_path / "limited-experiment.json"
    experiment_file.write_text(json.dumps(experiment))
    with pytest.raises(DiagnosticLimitError, match="exceeding effective member cap"):
        _prepare(snapshot_file, tmp_path, experiment=experiment_file)
    runs_root = tmp_path / "runs"
    assert not runs_root.exists() or not any(runs_root.iterdir())


def test_timeout_is_enforced_by_the_diagnostic_child(snapshot_file, tmp_path):
    experiment = json.loads(BASE_EXPERIMENT.read_text())
    experiment["limits"]["timeout_seconds"] = 0.000001
    experiment_file = tmp_path / "short-deadline.json"
    experiment_file.write_text(json.dumps(experiment))
    _, run_dir = _prepare(snapshot_file, tmp_path, experiment=experiment_file)
    with pytest.raises((DiagnosticTimeoutError, DiagnosticInputError)):
        run_manifest(run_dir / "manifest.json")
    assert not (run_dir / "report.json").exists()
    assert not (run_dir / "report.md").exists()


def test_exact_capture_matches_canonical_tier2_graph_winner_and_verdict(mock_root: Path):
    snapshot = mock_root / "docs/examples/synthetic/counterfactual_split/snapshot_000.json"
    if not snapshot.is_file():
        pytest.skip("canonical counterfactual_split snapshot fixture is unavailable")
    package = load_validated_package(json.loads(snapshot.read_text()))
    chain_id = next(iter(package.chains))
    config = load_analysis_config(ANALYSIS_CONFIG)
    policy = load_scope_policy(SCOPE_POLICY)
    epsilon_phi = float(config.value("audit.global_weak_baseline"))
    exact = capture_exact_audit_inputs(
        package,
        chain_id,
        analysis_config=config,
        scope_policy=policy,
        limits=ResourceLimits(),
        epsilon_phi=epsilon_phi,
    )
    canonical = analyze_structural_audit(
        package,
        chain_id,
        policy=AuditExecutionPolicy(exact_max_members=2000),
        mining_config=config.mining_config(),
        epsilon=epsilon_phi,
        rho=float(config.value("audit.rho")),
        min_side_size=int(config.value("audit.min_side_size")),
        small_chain_threshold=int(config.value("audit.small_chain_threshold")),
        delay_threshold=float(config.value("temporal.delay.support_threshold")),
        d_max=int(config.value("dependency.max_hop")),
        silent_gap_seconds=int(config.value("temporal.burst.gap_seconds")),
    )

    assert canonical.graph is not None
    assert exact.graph.members == canonical.graph.members
    assert exact.graph.edges == canonical.graph.edges
    assert exact.production_baseline_verdict == canonical.structural_audit.verdict.value
    assert canonical.structural_audit.best_cut is not None
    assert exact.production_baseline_winner_id is not None
    winner = next(
        score for score in exact.baseline_scores
        if score.partition_id == exact.production_baseline_winner_id
    )
    assert winner.phi == pytest.approx(canonical.structural_audit.best_cut.conductance.phi)


def test_exact_capture_accepts_noncanonical_membership_order(mock_root: Path):
    snapshot = mock_root / "docs/examples/synthetic/counterfactual_split/snapshot_000.json"
    if not snapshot.is_file():
        pytest.skip("canonical counterfactual_split snapshot fixture is unavailable")
    package = load_validated_package(json.loads(snapshot.read_text()))
    chain_id = next(
        chain_id for chain_id, members in package.memberships.items() if len(members) >= 2
    )
    package.memberships[chain_id].reverse()
    config = load_analysis_config(ANALYSIS_CONFIG)
    policy = load_scope_policy(SCOPE_POLICY)

    exact = capture_exact_audit_inputs(
        package,
        chain_id,
        analysis_config=config,
        scope_policy=policy,
        limits=ResourceLimits(),
        epsilon_phi=float(config.value("audit.global_weak_baseline")),
    )

    expected_pairs = len(package.members_of(chain_id)) * (len(package.members_of(chain_id)) - 1) // 2
    assert exact.pair_count == expected_pairs
    assert len(exact.pair_channel_values) == expected_pairs


def test_pair_example_cap_changes_display_only_not_coverage_aggregates(mock_root: Path):
    snapshot = mock_root / "docs/examples/synthetic/counterfactual_split/snapshot_000.json"
    if not snapshot.is_file():
        pytest.skip("canonical counterfactual_split snapshot fixture is unavailable")
    package = load_validated_package(json.loads(snapshot.read_text()))
    chain_id = next(iter(package.chains))
    config = load_analysis_config(ANALYSIS_CONFIG)
    policy = load_scope_policy(SCOPE_POLICY)
    registry = resolve_execution_registry(package, policy)
    exact = capture_exact_audit_inputs(
        package,
        chain_id,
        analysis_config=config,
        scope_policy=policy,
        limits=ResourceLimits(),
        epsilon_phi=float(config.value("audit.global_weak_baseline")),
    )
    full = aggregate_coverage(
        exact.members,
        exact.pair_channel_values,
        candidates=exact.candidates,
        policy=policy,
        expected_channel_ids=registry.channel_ids,
        expected_group_channels=registry.group_channels,
    )
    small_examples, small_omitted = _coverage_pair_examples(
        exact.members,
        exact.pair_channel_values,
        registry,
        policy,
        limits=ResourceLimits(max_example_pairs_per_section=5),
    )
    large_examples, large_omitted = _coverage_pair_examples(
        exact.members,
        exact.pair_channel_values,
        registry,
        policy,
        limits=ResourceLimits(max_example_pairs_per_section=50),
    )
    after_display_sampling = aggregate_coverage(
        exact.members,
        exact.pair_channel_values,
        candidates=exact.candidates,
        policy=policy,
        expected_channel_ids=registry.channel_ids,
        expected_group_channels=registry.group_channels,
    )
    assert tuple(row.model_dump(mode="json") for row in full.channel_rows_all) == tuple(
        row.model_dump(mode="json") for row in after_display_sampling.channel_rows_all
    )
    assert len(small_examples) == 5
    assert small_omitted == 115
    assert len(large_examples) == 50
    assert large_omitted == 70
