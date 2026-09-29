"""Prepare and execute frozen, bounded Audit coverage/sensitivity runs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping

from audit_diagnostics.capture import (
    DiagnosticInputError,
    DiagnosticLimitError,
    candidate_generation_config_digest,
    capture_exact_audit_inputs,
)
from audit_diagnostics.comparison import compare_candidates, score_frozen_candidates
from audit_diagnostics.contracts import (
    ChannelPairTrace,
    ComputationStatus,
    DiagnosticReport,
    FrozenManifest,
    GroupRegistryEntry,
    GroupKey,
    InvariantResult,
    MaterialityPolicy,
    PairEvidenceExample,
    PairEvidencePriority,
    PairKey,
    ResourceLimits,
    RunStatus,
    InvocationStatus,
    ScopeState,
    ScopeQualityFlag,
    VariantKind,
    VariantResult,
    VariantSpec,
)
from audit_diagnostics.coverage import CoverageResult, aggregate_coverage, _evidence_reason_code
from audit_diagnostics.registry import ResolvedChannelRegistry, resolve_execution_registry
from audit_diagnostics.scope import ScopePolicy, classify_scope, load_scope_policy
from audit_diagnostics.serialization import (
    atomic_write_new,
    canonical_json_bytes,
    digest_json,
    publish_report_pair,
    render_markdown,
    semantic_result_digest,
    sha256_bytes,
)
from audit_diagnostics.variants import apply_logo, summarize_candidate_regions
from channels.base import ChannelValue
from configuration import AnalysisConfig, load_analysis_config
from libs.contracts import IngestedPackage, load_validated_package


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCOPE_POLICY = REPO_ROOT / "config/audit_diagnostics/scope-v1.yaml"
DEFAULT_EXPERIMENT = REPO_ROOT / "config/audit_diagnostics/experiment-v1.json"
BASELINE_POLICY_VERSION = "tier2-audit-canonical-v1"


class DiagnosticPreparationError(ValueError):
    """Input/configuration cannot be frozen into the declared diagnostic."""


class DiagnosticManifestMismatch(ValueError):
    """A pinned input, config, or source changed after prepare."""


class DiagnosticTimeoutError(TimeoutError):
    """The isolated diagnostic worker exceeded its pinned deadline."""


class DiagnosticWorkerError(RuntimeError):
    """The isolated worker failed before publishing a valid report."""


def prepare(
    snapshot_path: str | Path,
    chain_id: str,
    analysis_config_path: str | Path,
    experiment_path: str | Path = DEFAULT_EXPERIMENT,
    output_dir: str | Path = "/tmp/hindsight-audit-diagnostics",
    scope_policy_path: str | Path = DEFAULT_SCOPE_POLICY,
) -> tuple[FrozenManifest, Path]:
    """Freeze source/config/snapshot identity and variants without scoring evidence."""
    snapshot_file = Path(snapshot_path).expanduser().resolve()
    analysis_file = Path(analysis_config_path).expanduser().resolve()
    experiment_file = Path(experiment_path).expanduser().resolve()
    scope_file = Path(scope_policy_path).expanduser().resolve()
    for path in (snapshot_file, analysis_file, experiment_file, scope_file):
        if not path.is_file():
            raise DiagnosticPreparationError(f"required input file does not exist: {path}")

    try:
        snapshot_bytes = snapshot_file.read_bytes()
        package = _load_package(snapshot_bytes, snapshot_file)
        analysis_config = load_analysis_config(analysis_file)
        policy = load_scope_policy(scope_file)
        experiment_bytes = experiment_file.read_bytes()
        experiment = _parse_experiment(experiment_bytes)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise DiagnosticPreparationError(str(exc)) from exc
    if chain_id not in package.chains:
        raise DiagnosticPreparationError(f"unknown chain_id {chain_id!r}")

    limits = ResourceLimits.model_validate(experiment.get("limits", {}))
    audit_policy = _require_mapping(experiment, "audit_policy")
    epsilon_phi = _finite_unit(audit_policy.get("epsilon_phi"), "audit_policy.epsilon_phi")
    if experiment.get("variant_policy", {}).get("baseline") is not True:
        raise DiagnosticPreparationError("experiment must include the canonical baseline")
    logo_groups = experiment.get("variant_policy", {}).get("logo_groups")
    if logo_groups != "ALL_RESOLVED_AUDIT_ELIGIBLE_GROUPS":
        raise DiagnosticPreparationError(
            "v1 supports all resolved audit-eligible LOGO groups; declare a new experiment for any subset"
        )
    if experiment.get("variant_policy", {}).get("unsupported_variants") != "REJECT":
        raise DiagnosticPreparationError("unsupported variants must be rejected explicitly")

    registry = resolve_execution_registry(package, policy)
    if not registry.complete:
        raise DiagnosticPreparationError(
            "scope/execution registry is incomplete: " + ", ".join(registry.issues)
        )
    audit_groups = tuple(sorted(
        (key for key in registry.group_channels if key.audit_eligible),
        key=_group_sort_key,
    ))
    if 1 + len(audit_groups) > limits.max_variants:
        raise DiagnosticLimitError(
            f"baseline plus {len(audit_groups)} LOGO variants exceeds max_variants={limits.max_variants}; "
            "declare a group subset in a separate pre-registered experiment"
        )
    members = tuple(package.members_of(chain_id))
    if not package.snapshot.is_complete:
        raise DiagnosticPreparationError("diagnostic requires a COMPLETE canonical snapshot")
    if not members:
        raise DiagnosticPreparationError("chain membership must be non-empty")
    if len(members) != len(set(members)):
        raise DiagnosticPreparationError("duplicate chain membership rows are invalid")
    canonical_exact_max = int(analysis_config.value("audit.exact_max_members"))
    effective_max_members = min(limits.max_members, canonical_exact_max)
    if len(members) > effective_max_members:
        raise DiagnosticLimitError(
            f"chain has {len(members)} members, exceeding effective member cap {effective_max_members}"
        )
    pair_count = len(members) * (len(members) - 1) // 2
    if pair_count > limits.max_pairs:
        raise DiagnosticLimitError(
            f"chain has {pair_count} unordered pairs, exceeding max_pairs={limits.max_pairs}"
        )

    variant_specs = (
        VariantSpec(variant_id="baseline", kind=VariantKind.BASELINE),
        *tuple(
            VariantSpec(
                variant_id=f"logo-{digest_json(group.model_dump(mode='json'))[:16]}",
                kind=VariantKind.LOGO,
                excluded_group=group,
            )
            for group in audit_groups
        ),
    )
    materiality_raw = experiment.get("materiality_policy", {})
    materiality = MaterialityPolicy.model_validate(materiality_raw)
    topology_ref = package.snapshot.topology_ref
    topology_ref_id = None
    topology_version = package.snapshot.topology_version
    topology_digest = _digest_json(package.topology)
    if topology_ref is not None:
        topology_ref_id = getattr(topology_ref, "profile_id", None)
        topology_version = getattr(topology_ref, "topology_version", topology_version)
        topology_digest = getattr(topology_ref, "topology_hash", None) or topology_digest
    input_binding = {
        "snapshot_id": package.snapshot.snapshot_id,
        "snapshot_version": package.snapshot.snapshot_version,
        "chain_id": chain_id,
        "snapshot_ref": str(snapshot_file),
        "input_bytes_digest": sha256_bytes(snapshot_bytes),
        "canonical_package_digest": _digest_json(json.loads(snapshot_bytes)),
        "member_fingerprint": digest_json(members),
        "topology_ref": topology_ref_id,
        "topology_version": topology_version,
        "topology_digest": topology_digest,
        "mapping_digest": _digest_json(package.system_metadata),
        "provenance_digest": _digest_json(package.provenance_manifest),
        "hydration_digest": _digest_json({"topology": package.topology, "context": package.operational_context}),
        "taxonomy_digest": None,
        "delay_model_digest": None,
    }
    code_binding = _current_source_binding()
    analysis_ref = _path_ref(analysis_file)
    config_digest = sha256_bytes(analysis_file.read_bytes())
    source_file_digests = dict(code_binding["file_digests"])
    source_file_digests[f"config/analysis:{analysis_ref}"] = config_digest
    source_file_digests[f"config/scope:{_path_ref(scope_file)}"] = policy.digest
    source_file_digests[f"config/experiment:{_path_ref(experiment_file)}"] = sha256_bytes(experiment_bytes)
    source_binding = {
        "git_commit": code_binding["git_commit"],
        "dirty": code_binding["dirty"],
        "file_digests": source_file_digests,
        "source_bundle_digest": digest_json(code_binding["file_digests"]),
    }
    manifest = FrozenManifest(
        run_id=str(uuid.uuid4()),
        prepared_at=datetime.now(timezone.utc),
        analysis_version="audit-diagnostics-v1",
        baseline_policy_version=BASELINE_POLICY_VERSION,
        input_binding=input_binding,
        source_binding=source_binding,
        analysis_config_ref=str(analysis_file),
        analysis_config_digest=config_digest,
        scope_policy_ref=str(scope_file),
        scope_policy_id=policy.policy_id,
        scope_policy_version=policy.policy_version,
        scope_policy_digest=policy.digest,
        group_registry_digest=registry.group_registry_digest,
        execution_profile_digest=registry.execution_profile_digest,
        candidate_generation_config_digest=candidate_generation_config_digest(analysis_config),
        experiment_ref=str(experiment_file),
        experiment_digest=sha256_bytes(experiment_bytes),
        audit_epsilon_phi=epsilon_phi,
        audit_epsilon_phi_source=str(audit_policy.get("epsilon_phi_source", "experiment")),
        variants=variant_specs,
        limits=limits,
        materiality_policy=materiality,
    )

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / manifest.run_id
    try:
        run_dir.mkdir()
    except FileExistsError as exc:
        raise DiagnosticPreparationError(f"run directory already exists: {run_dir}") from exc
    manifest_bytes = canonical_json_bytes(manifest) + b"\n"
    try:
        atomic_write_new(run_dir / "manifest.json", manifest_bytes)
        atomic_write_new(run_dir / "manifest.sha256", (sha256_bytes(canonical_json_bytes(manifest)) + "\n").encode())
    except Exception:
        # This directory was just created by this prepare call.
        for child in run_dir.iterdir():
            child.unlink(missing_ok=True)
        run_dir.rmdir()
        raise
    return manifest, run_dir


def run_manifest(manifest_path: str | Path) -> DiagnosticReport:
    """Execute the frozen diagnostic in a bounded child process and publish results."""
    path = Path(manifest_path).expanduser().resolve()
    manifest = load_manifest(path)
    run_dir = path.parent
    if (run_dir / "report.json").exists() or (run_dir / "report.md").exists():
        raise DiagnosticPreparationError(f"immutable reports already exist in {run_dir}")
    entry = REPO_ROOT / "benchmarks/run_audit_diagnostics.py"
    with tempfile.TemporaryDirectory(prefix="audit-diagnostics-worker-") as scratch:
        worker_dir = Path(scratch)
        command = [sys.executable, str(entry), "_worker", "--manifest", str(path), "--output-dir", str(worker_dir)]
        env = os.environ.copy()
        required_paths = [REPO_ROOT, REPO_ROOT / "services/analysis-worker", REPO_ROOT / "services/api"]
        env["PYTHONPATH"] = os.pathsep.join([*(str(item) for item in required_paths), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        try:
            process = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=manifest.limits.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DiagnosticTimeoutError(
                f"diagnostic worker exceeded timeout_seconds={manifest.limits.timeout_seconds}; no report was published"
            ) from exc
        report_path = worker_dir / "report.json"
        markdown_path = worker_dir / "report.md"
        if process.returncode == 2:
            message = (process.stderr or process.stdout or "manifest/input mismatch").strip()
            raise DiagnosticManifestMismatch(message[-4000:])
        if process.returncode == 3 and (not report_path.is_file() or not markdown_path.is_file()):
            message = (process.stderr or process.stdout or "diagnostic lacks inputs for exact completion").strip()
            raise DiagnosticInputError(message[-4000:])
        if process.returncode not in (0, 3) or not report_path.is_file() or not markdown_path.is_file():
            message = (process.stderr or process.stdout or "worker returned no diagnostic report").strip()
            raise DiagnosticWorkerError(
                f"diagnostic worker exited {process.returncode}: {message[-4000:]}"
            )
        report_bytes = report_path.read_bytes()
        markdown_bytes = markdown_path.read_bytes()
    report = DiagnosticReport.model_validate_json(report_bytes)
    if report.manifest_digest != _manifest_digest(manifest):
        raise DiagnosticWorkerError("worker report manifest digest does not match frozen manifest")
    publish_report_pair(run_dir, report_bytes, markdown_bytes)
    return report


def run_manifest_inline(manifest_path: str | Path, output_dir: str | Path) -> DiagnosticReport:
    """Worker entry point. Caller enforces the wall-clock deadline externally."""
    manifest_file = Path(manifest_path).resolve()
    manifest = load_manifest(manifest_file)
    started = time.perf_counter()
    package, config, policy, registry = _verify_frozen_inputs(manifest)
    capture_started = time.perf_counter()
    exact = capture_exact_audit_inputs(
        package,
        manifest.input_binding.chain_id,
        analysis_config=config,
        scope_policy=policy,
        limits=manifest.limits,
        epsilon_phi=manifest.audit_epsilon_phi,
    )
    capture_seconds = time.perf_counter() - capture_started
    if exact.channel_registry.group_registry_digest != manifest.group_registry_digest:
        raise DiagnosticManifestMismatch("resolved effective group registry changed after prepare")
    if exact.channel_registry.execution_profile_digest != manifest.execution_profile_digest:
        raise DiagnosticManifestMismatch("resolved exact evaluator profile changed after prepare")
    if _variant_specs_for_registry(exact.channel_registry, manifest.limits) != manifest.variants:
        raise DiagnosticManifestMismatch("LOGO variant list differs from the pre-registered registry")
    if candidate_generation_config_digest(config) != manifest.candidate_generation_config_digest:
        raise DiagnosticManifestMismatch("candidate generation configuration changed after prepare")

    coverage = aggregate_coverage(
        exact.members,
        exact.pair_channel_values,
        candidates=exact.candidates,
        policy=policy,
        expected_channel_ids=registry.channel_ids,
        expected_group_channels=registry.group_channels,
    )
    if not coverage.registry_complete or not coverage.pair_matrix_complete:
        raise DiagnosticInputError(
            "exact registry/pair matrix is incomplete: " + ", ".join(coverage.issues)
        )
    pair_examples, omitted_pair_examples = _coverage_pair_examples(
        exact.members,
        exact.pair_channel_values,
        registry,
        policy,
        limits=manifest.limits,
    )
    variant_results: list[VariantResult] = []
    invariants: list[InvariantResult] = [
        InvariantResult(invariant_id="exact_unordered_pair_matrix", passed=True,
                        detail=f"{exact.pair_count} pairs evaluated from canonical chain evidence"),
        InvariantResult(invariant_id="canonical_audit_graph_rebuild", passed=True,
                        detail=f"{len(exact.graph.edges)} weighted edges; {len(exact.graph.members)} frozen members"),
        InvariantResult(invariant_id="candidate_set_frozen", passed=True,
                        detail=exact.candidate_set_digest),
    ]
    by_candidate_region = {
        candidate_id: tuple(rows)
        for candidate_id, rows in sorted(coverage.by_candidate_region.items())
    }
    baseline_variant = manifest.variants[0]
    variant_results.append(VariantResult(
        variant=baseline_variant,
        computation_status=ComputationStatus.EXACT,
        candidate_scores=exact.baseline_scores,
    ))
    total_variant_seconds = 0.0
    for variant in manifest.variants[1:]:
        variant_started = time.perf_counter()
        assert variant.kind is VariantKind.LOGO and variant.excluded_group is not None
        logo = apply_logo(
            exact.members,
            exact.pair_channel_values,
            exact.graph,
            variant.excluded_group,
            epsilon_num=manifest.materiality_policy.epsilon_num,
        )
        scores = score_frozen_candidates(
            logo.graph,
            exact.candidates,
            rho=float(config.value("audit.rho")),
            min_side_size=int(config.value("audit.min_side_size")),
            small_chain_threshold=int(config.value("audit.small_chain_threshold")),
        )
        comparison = compare_candidates(
            exact.baseline_scores,
            scores,
            production_baseline_winner_id=exact.production_baseline_winner_id,
            epsilon_phi=manifest.audit_epsilon_phi,
            materiality=manifest.materiality_policy,
        )
        region_summaries = summarize_candidate_regions(logo, exact.graph, exact.candidates)
        ordered_examples = sorted(
            logo.transitions,
            key=lambda item: (
                0 if item.baseline_support_group_count == 2 else 1,
                0 if item.transition.value != "RETAINED_UNCHANGED" else 1,
                item.pair.left,
                item.pair.right,
            ),
        )
        cap = manifest.limits.max_example_pairs_per_section
        examples = tuple(ordered_examples[:cap])
        omitted = max(0, len(ordered_examples) - len(examples))
        variant_results.append(VariantResult(
            variant=variant,
            computation_status=ComputationStatus.EXACT,
            edge_transition_summary=logo.summary,
            candidate_scores=scores,
            comparison=comparison,
            candidate_region_summaries=region_summaries,
            bounded_pair_examples=examples,
            omitted_example_count=omitted,
        ))
        invariants.extend(
            item.model_copy(update={"invariant_id": f"{variant.variant_id}:{item.invariant_id}"})
            for item in logo.invariants
        )
        total_variant_seconds += time.perf_counter() - variant_started

    scope_flags = _scope_quality_flags(coverage)
    report = DiagnosticReport(
        run_status=RunStatus.COMPLETE,
        complete=True,
        manifest_digest=_manifest_digest(manifest),
        semantic_result_digest="0" * 64,
        baseline_binding=manifest.input_binding,
        audit_epsilon_phi=manifest.audit_epsilon_phi,
        audit_epsilon_phi_source=manifest.audit_epsilon_phi_source,
        baseline_production_verdict=exact.production_baseline_verdict,
        materiality_policy=manifest.materiality_policy,
        execution_profile_digest=registry.execution_profile_digest,
        group_registry_digest=registry.group_registry_digest,
        registered_channel_ids=registry.channel_ids,
        registered_group_keys=tuple(sorted(registry.group_channels, key=_group_sort_key)),
        registered_groups=tuple(
            GroupRegistryEntry(effective_group_key=key, channel_ids=channels)
            for key, channels in sorted(registry.group_channels.items(), key=lambda item: _group_sort_key(item[0]))
        ),
        capability_catalog={
            str(key): {str(name): str(value) for name, value in metadata.items()}
            for key, metadata in policy.capability_catalog.items()
        },
        candidate_set_digest=exact.candidate_set_digest,
        registry_complete=coverage.registry_complete,
        pair_matrix_complete=coverage.pair_matrix_complete,
        scope_quality=coverage.channel_rows_all,
        scope_quality_flags=scope_flags,
        coverage_all_pairs=tuple(sorted(
            (*coverage.channel_rows_all, *coverage.group_rows_all),
            key=_coverage_sort_key,
        )),
        coverage_pair_examples=pair_examples,
        omitted_coverage_pair_example_count=omitted_pair_examples,
        candidates=exact.candidates,
        coverage_by_candidate_region=by_candidate_region,
        variants=tuple(variant_results),
        invariant_results=tuple(invariants),
        limitations=(
            "Descriptive coverage is snapshot-specific and is not a probability of correctness or confidence interval.",
            "Sensitivity is conditional on the frozen candidate set; it does not establish causality, missingness, or audit correctness.",
            "The scope policy is marked UNAPPROVED_DIAGNOSTIC_POLICY; no production policy is activated.",
            "epsilon_phi is the documented weak baseline and is not production-calibrated.",
        ),
        resource_counts={
            "members": len(exact.members),
            "unordered_pairs": exact.pair_count,
            "registered_channels": len(registry.channel_ids),
            "effective_groups": len(registry.group_channels),
            "audit_eligible_groups": sum(key.audit_eligible for key in registry.group_channels),
            "candidates": len(exact.candidates),
            "variants": len(manifest.variants),
            "bounded_examples": sum(len(item.bounded_pair_examples) for item in variant_results),
            "coverage_pair_examples": len(pair_examples),
            "omitted_coverage_pair_examples": omitted_pair_examples,
        },
        timings_seconds={
            "exact_capture": capture_seconds,
            "logo_variants": total_variant_seconds,
            "total_worker": time.perf_counter() - started,
        },
    )
    report = report.model_copy(update={"semantic_result_digest": semantic_result_digest(report)})
    markdown = render_markdown(report)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_bytes(canonical_json_bytes(report) + b"\n")
    (output / "report.md").write_text(markdown, encoding="utf-8")
    return report


def load_manifest(path: str | Path) -> FrozenManifest:
    manifest_file = Path(path).resolve()
    try:
        raw = manifest_file.read_bytes()
        payload = FrozenManifest.model_validate_json(raw)
        checksum_path = manifest_file.with_name("manifest.sha256")
        checksum = checksum_path.read_text(encoding="ascii").strip()
    except (OSError, ValueError) as exc:
        raise DiagnosticPreparationError(f"cannot load frozen manifest {manifest_file}: {exc}") from exc
    expected = sha256_bytes(canonical_json_bytes(payload))
    if checksum != expected:
        raise DiagnosticManifestMismatch("manifest checksum does not match manifest.sha256")
    return payload


def _verify_frozen_inputs(
    manifest: FrozenManifest,
) -> tuple[IngestedPackage, AnalysisConfig, ScopePolicy, ResolvedChannelRegistry]:
    snapshot_path = Path(manifest.input_binding.snapshot_ref)
    analysis_path = Path(manifest.analysis_config_ref)
    scope_path = Path(manifest.scope_policy_ref)
    experiment_path = Path(manifest.experiment_ref)
    for path in (snapshot_path, analysis_path, scope_path, experiment_path):
        if not path.is_file():
            raise DiagnosticManifestMismatch(f"pinned input disappeared: {path}")
    snapshot_bytes = snapshot_path.read_bytes()
    if sha256_bytes(snapshot_bytes) != manifest.input_binding.input_bytes_digest:
        raise DiagnosticManifestMismatch("snapshot bytes changed after prepare")
    package = _load_package(snapshot_bytes, snapshot_path)
    if _digest_json(json.loads(snapshot_bytes)) != manifest.input_binding.canonical_package_digest:
        raise DiagnosticManifestMismatch("canonical package content changed after prepare")
    if (
        package.snapshot.snapshot_id != manifest.input_binding.snapshot_id
        or package.snapshot.snapshot_version != manifest.input_binding.snapshot_version
    ):
        raise DiagnosticManifestMismatch("snapshot identity changed after prepare")
    members = tuple(package.members_of(manifest.input_binding.chain_id))
    if digest_json(members) != manifest.input_binding.member_fingerprint:
        raise DiagnosticManifestMismatch("chain member order/content changed after prepare")
    topology_ref = package.snapshot.topology_ref
    topology_ref_id = getattr(topology_ref, "profile_id", None) if topology_ref is not None else None
    topology_version = package.snapshot.topology_version
    topology_digest = _digest_json(package.topology)
    if topology_ref is not None:
        topology_version = getattr(topology_ref, "topology_version", topology_version)
        topology_digest = getattr(topology_ref, "topology_hash", None) or topology_digest
    expected_input_digests = {
        "topology_ref": topology_ref_id,
        "topology_version": topology_version,
        "topology_digest": topology_digest,
        "mapping_digest": _digest_json(package.system_metadata),
        "provenance_digest": _digest_json(package.provenance_manifest),
        "hydration_digest": _digest_json({"topology": package.topology, "context": package.operational_context}),
        "taxonomy_digest": None,
        "delay_model_digest": None,
    }
    for name, expected in expected_input_digests.items():
        if getattr(manifest.input_binding, name) != expected:
            raise DiagnosticManifestMismatch(f"manifest {name} does not match the canonical snapshot")
    if sha256_bytes(analysis_path.read_bytes()) != manifest.analysis_config_digest:
        raise DiagnosticManifestMismatch("analysis config changed after prepare")
    experiment_bytes = experiment_path.read_bytes()
    if sha256_bytes(experiment_bytes) != manifest.experiment_digest:
        raise DiagnosticManifestMismatch("experiment definition changed after prepare")
    try:
        experiment = _parse_experiment(experiment_bytes)
        experiment_limits = ResourceLimits.model_validate(experiment.get("limits", {}))
        experiment_policy = _require_mapping(experiment, "audit_policy")
        experiment_epsilon_phi = _finite_unit(
            experiment_policy.get("epsilon_phi"), "audit_policy.epsilon_phi"
        )
        experiment_epsilon_source = experiment_policy.get(
            "epsilon_phi_source", "experiment"
        )
        experiment_materiality = MaterialityPolicy.model_validate(
            experiment.get("materiality_policy", {})
        )
    except (DiagnosticPreparationError, TypeError, ValueError) as exc:
        raise DiagnosticManifestMismatch(f"pinned experiment is invalid: {exc}") from exc
    if experiment_limits != manifest.limits:
        raise DiagnosticManifestMismatch("manifest resource limits do not match the pinned experiment")
    if experiment_epsilon_phi != manifest.audit_epsilon_phi:
        raise DiagnosticManifestMismatch("manifest audit epsilon does not match the pinned experiment")
    if experiment_epsilon_source != manifest.audit_epsilon_phi_source:
        raise DiagnosticManifestMismatch("manifest audit epsilon source does not match the pinned experiment")
    if experiment_materiality != manifest.materiality_policy:
        raise DiagnosticManifestMismatch("manifest materiality policy does not match the pinned experiment")
    policy = load_scope_policy(scope_path)
    if (
        policy.digest != manifest.scope_policy_digest
        or policy.policy_id != manifest.scope_policy_id
        or policy.policy_version != manifest.scope_policy_version
    ):
        raise DiagnosticManifestMismatch("scope applicability policy changed after prepare")
    expected_config_bindings = {
        f"config/analysis:{_path_ref(analysis_path)}": manifest.analysis_config_digest,
        f"config/scope:{_path_ref(scope_path)}": policy.digest,
        f"config/experiment:{_path_ref(experiment_path)}": manifest.experiment_digest,
    }
    actual_config_bindings = {
        name: digest
        for name, digest in manifest.source_binding.file_digests.items()
        if name.startswith("config/")
    }
    if actual_config_bindings != expected_config_bindings:
        raise DiagnosticManifestMismatch("manifest config source map does not match pinned config references")
    config = load_analysis_config(analysis_path)
    _verify_source_binding(manifest)
    registry = resolve_execution_registry(package, policy)
    if not registry.complete:
        raise DiagnosticManifestMismatch("execution registry no longer resolves completely")
    if registry.group_registry_digest != manifest.group_registry_digest:
        raise DiagnosticManifestMismatch("effective group registry changed after prepare")
    if registry.execution_profile_digest != manifest.execution_profile_digest:
        raise DiagnosticManifestMismatch("exact execution profile changed after prepare")
    return package, config, policy, registry


def _verify_source_binding(manifest: FrozenManifest) -> None:
    current = _current_source_binding()
    if current["git_commit"] != manifest.source_binding.git_commit:
        raise DiagnosticManifestMismatch("git commit changed after prepare")
    pinned_code_files = {
        name: digest for name, digest in manifest.source_binding.file_digests.items()
        if not name.startswith("config/")
    }
    if current["file_digests"] != pinned_code_files:
        raise DiagnosticManifestMismatch("relevant source file set or content changed after prepare")
    for name, expected in manifest.source_binding.file_digests.items():
        if name.startswith("config/"):
            continue
        path = REPO_ROOT / name
        if not path.is_file():
            raise DiagnosticManifestMismatch(f"pinned source file disappeared: {name}")
        if sha256_bytes(path.read_bytes()) != expected:
            raise DiagnosticManifestMismatch(f"pinned source file changed after prepare: {name}")
    if digest_json(pinned_code_files) != _source_bundle_digest(manifest):
        raise DiagnosticManifestMismatch("source bundle digest does not match pinned source map")


def _source_bundle_digest(manifest: FrozenManifest) -> str:
    code_files = {
        name: digest for name, digest in manifest.source_binding.file_digests.items()
        if not name.startswith("config/")
    }
    return digest_json(code_files)


def _current_source_binding() -> dict[str, Any]:
    source_paths = {
        "services/analysis-worker/channels/base.py",
        "services/analysis-worker/channels/__init__.py",
        "services/analysis-worker/channels/entity.py",
        "services/analysis-worker/channels/semantic.py",
        "services/analysis-worker/channels/temporal.py",
        "services/analysis-worker/channels/dependency.py",
        "services/analysis-worker/channels/failure_domain.py",
        "services/analysis-worker/channels/evaluator.py",
        "services/analysis-worker/audit/graph.py",
        "services/analysis-worker/audit/candidates.py",
        "services/analysis-worker/audit/conductance.py",
        "services/analysis-worker/audit/verdict.py",
        "services/analysis-worker/audit/__init__.py",
        "services/analysis-worker/tier2/audit_analysis.py",
        "services/analysis-worker/configuration/analysis_config.py",
        "services/analysis-worker/configuration/__init__.py",
        "services/analysis-worker/descriptor/mining.py",
        "services/analysis-worker/descriptor/predicates.py",
        "services/analysis-worker/descriptor/__init__.py",
        "services/analysis-worker/groups/__init__.py",
        "services/analysis-worker/groups/roles.py",
        "services/analysis-worker/tier2/__init__.py",
        "libs/contracts/loader.py",
        "libs/contracts/__init__.py",
        "libs/provenance/__init__.py",
        "libs/provenance/derivation.py",
        "libs/provenance/eligibility.py",
        "contracts/v1/__init__.py",
        "contracts/v1/models.py",
        "contracts/v1/enums.py",
        "contracts/v1/parsing.py",
        "contracts/v1/serialization.py",
        "contracts/v1/validation.py",
        "benchmarks/run_audit_diagnostics.py",
    }
    source_paths.update(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "services/analysis-worker/audit_diagnostics").glob("*.py")
    )
    digests = {}
    for name in sorted(source_paths):
        path = REPO_ROOT / name
        if not path.is_file():
            raise DiagnosticPreparationError(f"required source file is missing: {name}")
        digests[name] = sha256_bytes(path.read_bytes())
    commit = _git_output("rev-parse", "HEAD").strip()
    dirty = bool(_git_output("status", "--porcelain").strip())
    return {"git_commit": commit, "dirty": dirty, "file_digests": digests}


def _git_output(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiagnosticPreparationError(f"cannot inspect git source identity: {exc}") from exc
    return result.stdout


def _load_package(raw: bytes, path: Path) -> IngestedPackage:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DiagnosticPreparationError(f"{path}: invalid snapshot JSON: {exc}") from exc
    try:
        return load_validated_package(payload)
    except Exception as exc:
        raise DiagnosticPreparationError(f"{path}: invalid canonical snapshot: {exc}") from exc


def _parse_experiment(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DiagnosticPreparationError(f"invalid experiment JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "audit-diagnostics-experiment-v1":
        raise DiagnosticPreparationError("unsupported or invalid experiment schema")
    for field in ("experiment_id", "variant_policy", "audit_policy", "materiality_policy", "limits"):
        if field not in value:
            raise DiagnosticPreparationError(f"experiment is missing {field!r}")
    return value


def _require_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise DiagnosticPreparationError(f"experiment field {key!r} must be a JSON object")
    return value


def _finite_unit(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise DiagnosticPreparationError(f"{name} must be finite and within [0, 1]")
    return float(value)


def _variant_specs_for_registry(
    registry: ResolvedChannelRegistry,
    limits: ResourceLimits,
) -> tuple[VariantSpec, ...]:
    audit_groups = tuple(sorted(
        (key for key in registry.group_channels if key.audit_eligible),
        key=_group_sort_key,
    ))
    if 1 + len(audit_groups) > limits.max_variants:
        raise DiagnosticLimitError("resolved group count exceeds the frozen variant budget")
    return (
        VariantSpec(variant_id="baseline", kind=VariantKind.BASELINE),
        *tuple(
            VariantSpec(
                variant_id=f"logo-{digest_json(group.model_dump(mode='json'))[:16]}",
                kind=VariantKind.LOGO,
                excluded_group=group,
            )
            for group in audit_groups
        ),
    )


def _scope_quality_flags(coverage: CoverageResult) -> tuple[ScopeQualityFlag, ...]:
    flags = []
    for row in coverage.channel_rows_all:
        assert row.channel_id is not None
        flags.append(ScopeQualityFlag(
            channel_id=row.channel_id,
            unknown_applicability_count=row.counts.unknown_applicability,
            unknown_applicability_share=row.ratios.unknown_scope_share,
            undefined_rule_count=row.primary_reason_counts.get("SCOPE_RULE_UNDEFINED", 0),
            reason_counts={
                key: value for key, value in row.primary_reason_counts.items()
                if key.startswith("SCOPE_")
            },
        ))
    return tuple(flags)


def _coverage_pair_examples(
    members: tuple[str, ...],
    values_by_pair: Mapping[tuple[str, str], tuple[ChannelValue, ...]],
    registry: ResolvedChannelRegistry,
    policy: ScopePolicy,
    *,
    limits: ResourceLimits,
) -> tuple[tuple[PairEvidenceExample, ...], int]:
    """Keep a deterministic issue-first sample without changing any aggregates."""
    cap = limits.max_example_pairs_per_section
    per_priority_cap = cap
    sampled: dict[PairEvidencePriority, list[PairEvidenceExample]] = {
        priority: [] for priority in PairEvidencePriority
    }
    pair_count = 0
    canonical_pairs = tuple(combinations(sorted(members), 2))
    values_lookup = {tuple(sorted(pair)): values for pair, values in values_by_pair.items()}
    for left, right in canonical_pairs:
        pair_count += 1
        key = (left, right)
        channel_by_id = {value.channel_id: value for value in values_lookup.get(key, ())}
        traces_with_priority: list[tuple[int, str, ChannelPairTrace]] = []
        unknown = False
        unavailable = False
        for channel_id in registry.channel_ids:
            value = channel_by_id.get(channel_id)
            invocation = InvocationStatus.EVALUATED if value is not None else InvocationStatus.NOT_EVALUATED
            decision = classify_scope(
                key,
                channel_id,
                policy,
                invocation=invocation,
                evidence_state=value.state if value is not None else None,
            )
            if decision.scope is ScopeState.UNKNOWN_APPLICABILITY:
                unknown = True
            if decision.scope is ScopeState.APPLICABLE and (
                value is None or not value.availability
            ):
                unavailable = True
            reason_code = decision.primary_reason.code if decision.primary_reason is not None else None
            if reason_code is None and value is None:
                reason_code = "CHANNEL_NOT_EVALUATED"
            elif reason_code is None and value is not None and not value.availability:
                reason_code = _evidence_reason_code(value)
            group_key = registry.channel_groups.get(channel_id)
            if group_key is None:
                raise DiagnosticInputError(f"resolved channel {channel_id!r} has no effective group key")
            trace = ChannelPairTrace(
                channel_id=channel_id,
                effective_group_key=group_key,
                scope=decision.scope,
                invocation=invocation,
                evidence_state=value.state if value is not None else None,
                primary_reason_code=reason_code,
            )
            trace_priority = (
                0 if decision.scope is ScopeState.UNKNOWN_APPLICABILITY else
                1 if decision.scope is ScopeState.APPLICABLE and (value is None or not value.availability) else
                2
            )
            traces_with_priority.append((trace_priority, channel_id, trace))
        priority = (
            PairEvidencePriority.UNKNOWN_APPLICABILITY if unknown else
            PairEvidencePriority.APPLICABLE_UNAVAILABLE if unavailable else
            PairEvidencePriority.OBSERVED
        )
        if len(sampled[priority]) >= per_priority_cap:
            continue
        traces_with_priority.sort(key=lambda item: (item[0], item[1]))
        selected_traces = tuple(item[2] for item in traces_with_priority[:limits.max_channel_traces_per_pair])
        sampled[priority].append(PairEvidenceExample(
            pair=PairKey(left=left, right=right),
            priority=priority,
            channel_traces=selected_traces,
            omitted_channel_trace_count=max(0, len(traces_with_priority) - len(selected_traces)),
        ))
    selected: list[PairEvidenceExample] = []
    for priority in (
        PairEvidencePriority.UNKNOWN_APPLICABILITY,
        PairEvidencePriority.APPLICABLE_UNAVAILABLE,
        PairEvidencePriority.OBSERVED,
    ):
        remaining = max(0, cap - len(selected))
        selected.extend(sampled[priority][:remaining])
    selected.sort(key=lambda item: (
        list(PairEvidencePriority).index(item.priority), item.pair.left, item.pair.right,
    ))
    return tuple(selected), max(0, pair_count - len(selected))


def _manifest_digest(manifest: FrozenManifest) -> str:
    return digest_json(manifest.model_dump(mode="json"))


def _digest_json(value: Any) -> str:
    return digest_json(value)


def _path_ref(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _group_sort_key(key: GroupKey) -> tuple[str, str, bool, bool, bool]:
    return (
        key.derivation_tag,
        key.provenance_class.value,
        key.explain_eligible,
        key.role_eligible,
        key.audit_eligible,
    )


def _coverage_sort_key(row) -> tuple[str, str, str, str]:
    identity = row.channel_id or digest_json(row.effective_group_key.model_dump(mode="json"))
    return (row.population_id, row.region.value, "channel" if row.channel_id else "group", identity)
