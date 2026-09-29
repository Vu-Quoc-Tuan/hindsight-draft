"""Deterministic JSON hashing and immutable diagnostic artifact writers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .contracts import DiagnosticReport


class OutputExistsError(FileExistsError):
    """An immutable diagnostic artifact already exists."""


def canonical_json_bytes(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def semantic_result_digest(report: DiagnosticReport) -> str:
    """Hash semantic results while excluding run time, output location and manifest time."""
    payload = report.model_dump(mode="json")
    payload.pop("semantic_result_digest", None)
    payload.pop("manifest_digest", None)
    payload.pop("timings_seconds", None)
    binding = payload.get("baseline_binding")
    if isinstance(binding, dict):
        binding.pop("snapshot_ref", None)
    return digest_json(payload)


def atomic_write_new(path: str | Path, content: bytes) -> None:
    """Publish one file atomically without replacing an existing artifact."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp = Path(temp_name)
    linked = False
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, target)
            linked = True
        except FileExistsError as exc:
            raise OutputExistsError(f"refusing to overwrite existing artifact {target}") from exc
        _fsync_directory(target.parent)
    except Exception:
        if linked:
            target.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)


def publish_report_pair(run_dir: str | Path, json_bytes: bytes, markdown_bytes: bytes) -> None:
    """Publish JSON and Markdown as a no-overwrite pair, rolling back on failure."""
    root = Path(run_dir)
    lock = root / ".report-publish.lock"
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise OutputExistsError(f"another run is publishing artifacts in {root}") from exc
    json_path, markdown_path = root / "report.json", root / "report.md"
    published: list[Path] = []
    try:
        os.close(lock_fd)
        if json_path.exists() or markdown_path.exists():
            raise OutputExistsError(f"refusing to overwrite reports in {root}")
        atomic_write_new(json_path, json_bytes)
        published.append(json_path)
        atomic_write_new(markdown_path, markdown_bytes)
        published.append(markdown_path)
        _fsync_directory(root)
    except Exception:
        for path in published:
            path.unlink(missing_ok=True)
        raise
    finally:
        lock.unlink(missing_ok=True)


def render_markdown(report: DiagnosticReport) -> str:
    """Render a compact reviewer report without converting nulls to zero."""
    lines = [
        "# Audit Coverage & Sensitivity Diagnostic",
        "",
        f"- Completeness: **{report.run_status.value}** (`complete={str(report.complete).lower()}`)",
        "- Execution mode: **offline, frozen snapshot**",
        f"- Snapshot / chain: `{report.baseline_binding.snapshot_id}` / `{report.baseline_binding.chain_id}`",
        f"- Candidate set: `{report.candidate_set_digest or 'unavailable'}`",
        f"- Audit epsilon_phi: `{report.audit_epsilon_phi}` from `{report.audit_epsilon_phi_source}`; materiality delta_phi: "
        f"`{report.materiality_policy.delta_phi}` ({'configured' if report.materiality_policy.delta_phi is not None else 'not configured'})",
        f"- Semantic result digest: `{report.semantic_result_digest or 'not available'}`",
        "",
        "## Scope definition quality",
        "",
    ]
    if report.scope_quality_flags:
        lines.extend([
            "| Channel | Unknown applicability | Share | Undefined rule | Reason counts |",
            "|---|---:|---:|---:|---|",
        ])
        for item in report.scope_quality_flags:
            lines.append(
                f"| `{item.channel_id}` | {item.unknown_applicability_count} "
                f"| {_format_ratio(item.unknown_applicability_share)} "
                f"| {item.undefined_rule_count} | `{_compact(item.reason_counts)}` |"
            )
    else:
        lines.append("No channel scope quality rows were computed.")
    lines.extend(["", "## Chain-wide coverage", ""])
    channel_rows = [row for row in report.coverage_all_pairs if row.channel_id is not None]
    group_rows = [row for row in report.coverage_all_pairs if row.effective_group_key is not None]
    lines.extend(["### Channels", "", "| Channel | Total | Applicable | Available | Coverage | Unknown | Status |", "|---|---:|---:|---:|---:|---:|---|"])
    for row in channel_rows:
        lines.append(
            f"| `{row.channel_id}` | {row.counts.total} | {row.counts.applicable} "
            f"| {row.counts.available} | {_format_ratio(row.ratios.coverage)} "
            f"| {_format_ratio(row.ratios.unknown_scope_share)} | {row.computation_status.value} |"
        )
    lines.extend(["", "### Effective groups", "", "| Group key | Total | Applicable | Available | Coverage | Unknown | Status |", "|---|---:|---:|---:|---:|---:|---|"])
    for row in group_rows:
        lines.append(
            f"| `{_compact(row.effective_group_key.model_dump(mode='json'))}` | {row.counts.total} "
            f"| {row.counts.applicable} | {row.counts.available} | {_format_ratio(row.ratios.coverage)} "
            f"| {_format_ratio(row.ratios.unknown_scope_share)} | {row.computation_status.value} |"
        )
    lines.extend(["", "## Bounded pair evidence examples", ""])
    lines.append(
        f"Showing {len(report.coverage_pair_examples)} pair examples; "
        f"{report.omitted_coverage_pair_example_count} pairs omitted by the frozen display cap. "
        "Example selection does not change coverage aggregates."
    )
    if report.coverage_pair_examples:
        for example in report.coverage_pair_examples:
            lines.append(
                f"- `{example.pair.left}`–`{example.pair.right}` — **{example.priority.value}**: "
                + "; ".join(
                    f"`{trace.channel_id}` [{trace.scope.value}/{trace.invocation.value}/"
                    f"{trace.evidence_state.value if trace.evidence_state else 'none'}]"
                    f" group `{trace.effective_group_key.derivation_tag}`"
                    f"{'; reason=' + trace.primary_reason_code if trace.primary_reason_code else ''}"
                    for trace in example.channel_traces
                )
                + (f"; {example.omitted_channel_trace_count} channel traces omitted." if example.omitted_channel_trace_count else ".")
            )
    else:
        lines.append("No pair evidence examples were available.")
    lines.extend(["", "## Candidate regions", ""])
    if report.coverage_by_candidate_region:
        for candidate_id, rows in report.coverage_by_candidate_region.items():
            lines.extend([f"### `{candidate_id}`", "", "| Region | Level | ID | N | Applicable | Available | Coverage | Unknown |", "|---|---|---|---:|---:|---:|---:|---:|"])
            for row in rows:
                level, identifier = ("channel", row.channel_id) if row.channel_id is not None else (
                    "group", _compact(row.effective_group_key.model_dump(mode="json"))
                )
                lines.append(
                    f"| {row.region.value} | {level} | `{identifier}` | {row.counts.total} "
                    f"| {row.counts.applicable} | {row.counts.available} "
                    f"| {_format_ratio(row.ratios.coverage)} | {_format_ratio(row.ratios.unknown_scope_share)} |"
                )
    else:
        lines.append("No candidate partitions were generated.")
    lines.extend(["", "## LOGO and candidate comparison", ""])
    for result in report.variants:
        lines.extend([f"### {result.variant.variant_id}", ""])
        if result.variant.excluded_group is not None:
            lines.append(f"- Removed full effective group: `{_compact(result.variant.excluded_group.model_dump(mode='json'))}`")
        lines.append(f"- Status: **{result.computation_status.value}**")
        if result.edge_transition_summary is not None:
            summary = result.edge_transition_summary
            lines.append(
                f"- Edges: `{_compact({key.value: value for key, value in summary.counts.items()})}`; "
                f"removed baseline weight `{summary.removed_baseline_weight}`; "
                f"retained weight increase `{summary.retained_positive_weight_delta}`; "
                f"retained weight decrease `{summary.retained_negative_weight_delta_absolute}`."
            )
            lines.append(
                f"- Boundary pairs with exactly two baseline supporting groups: "
                f"{summary.boundary_pair_count}/{summary.boundary_population_count}; dropped-group states "
                f"`{_compact({key.value: value for key, value in summary.boundary_removed_group_state_counts.items()})}`."
            )
        if result.comparison is not None:
            compare = result.comparison
            lines.append(
                f"- Winner: `{compare.production_baseline_winner_id or 'none'}` → "
                f"`{compare.variant_best_id or 'none'}`; status `{compare.winner_status.value}`; "
                f"regret `{compare.regret}`; materiality `{compare.materiality_status.value}`; "
                f"verdict flip `{compare.verdict_flip}`."
            )
        if result.candidate_scores:
            lines.extend(["", "| Rank | Candidate | Status | Phi | Cut | Volume A | Volume B | Edges | Isolates |", "|---:|---|---|---:|---:|---:|---:|---:|---:|"])
            for score in result.candidate_scores:
                lines.append(
                    f"| {score.rank if score.rank is not None else '—'} | `{score.partition_id}` "
                    f"| {score.status.value} | {score.phi if score.phi is not None else '—'} "
                    f"| {score.cut_weight if score.cut_weight is not None else '—'} "
                    f"| {score.volume_a if score.volume_a is not None else '—'} "
                    f"| {score.volume_b if score.volume_b is not None else '—'} "
                    f"| {score.edge_count if score.edge_count is not None else '—'} "
                    f"| {score.isolate_count if score.isolate_count is not None else '—'} |"
                )
        if result.candidate_region_summaries:
            lines.extend(["", "| Candidate | Region | Pairs | Boundary (2 supports) | Baseline edges | Variant edges | Baseline isolates | Variant isolates | Transitions |", "|---|---|---:|---:|---:|---:|---:|---:|---|"])
            for item in result.candidate_region_summaries:
                edge_changes = item.edge_transitions.counts
                lines.append(
                    f"| `{item.candidate_id}` | {item.region.value} | {item.population_pair_count} "
                    f"| {item.edge_transitions.boundary_pair_count}/{item.edge_transitions.boundary_population_count} "
                    f"| {item.baseline_region_edge_count} | {item.variant_region_edge_count} "
                    f"| {item.baseline_region_isolate_count} | {item.variant_region_isolate_count} "
                    f"| `{_compact({key.value: value for key, value in edge_changes.items()})}` |"
                )
        if result.bounded_pair_examples:
            lines.extend(["", "Boundary-first bounded edge examples:", ""])
            for item in result.bounded_pair_examples:
                lines.append(
                    f"- `{item.pair.left}`–`{item.pair.right}`: {item.transition.value}, "
                    f"support groups {item.baseline_support_group_count}→{item.variant_support_group_count}, "
                    f"removed group `{item.removed_group_state.value if item.removed_group_state else 'unknown'}`, "
                    f"weight {item.baseline_weight}→{item.variant_weight}."
                )
            lines.append(f"- Omitted examples: {result.omitted_example_count}.")
    lines.extend(["", "## Invariants and limitations", ""])
    for item in report.invariant_results:
        lines.append(f"- `{item.invariant_id}`: `{item.passed}`{': ' + item.detail if item.detail else ''}")
    for item in report.limitations:
        lines.append(f"- {item}")
    if not report.invariant_results and not report.limitations:
        lines.append("No additional limitations were recorded.")
    lines.append("")
    return "\n".join(lines)


def _format_ratio(ratio) -> str:
    return f"{ratio.value:.6g}" if ratio.value is not None else f"null ({ratio.status.value})"


def _compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
