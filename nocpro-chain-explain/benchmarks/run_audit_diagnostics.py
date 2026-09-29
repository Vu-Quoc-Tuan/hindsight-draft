"""Offline CLI for frozen Audit coverage and LOGO sensitivity diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for source_path in (REPO_ROOT, REPO_ROOT / "services/analysis-worker", REPO_ROOT / "services/api"):
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))

from audit_diagnostics.capture import DiagnosticInputError, DiagnosticLimitError
from audit_diagnostics.runner import (
    DEFAULT_EXPERIMENT,
    DEFAULT_SCOPE_POLICY,
    DiagnosticManifestMismatch,
    DiagnosticPreparationError,
    DiagnosticTimeoutError,
    DiagnosticWorkerError,
    prepare,
    run_manifest,
    run_manifest_inline,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline Audit coverage/LOGO diagnostics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="freeze snapshot, source, config, scope and variants")
    prepare_parser.add_argument("--snapshot-json", required=True)
    prepare_parser.add_argument("--chain-id", required=True)
    prepare_parser.add_argument("--analysis-config", required=True)
    prepare_parser.add_argument("--experiment", default=str(DEFAULT_EXPERIMENT))
    prepare_parser.add_argument("--scope-policy", default=str(DEFAULT_SCOPE_POLICY))
    prepare_parser.add_argument("--output-dir", default="/tmp/hindsight-audit-diagnostics")

    run_parser = subparsers.add_parser("run", help="verify and execute a frozen manifest")
    run_parser.add_argument("--manifest", required=True)

    worker_parser = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("--manifest", required=True)
    worker_parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        try:
            manifest, run_dir = prepare(
                args.snapshot_json,
                args.chain_id,
                args.analysis_config,
                args.experiment,
                args.output_dir,
                args.scope_policy,
            )
        except DiagnosticLimitError as exc:
            print(f"LIMIT: {exc}", file=sys.stderr)
            return 3
        except (DiagnosticPreparationError, ValueError, OSError) as exc:
            print(f"INVALID_INPUT: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({
            "status": "PREPARED",
            "run_id": manifest.run_id,
            "manifest": str(run_dir / "manifest.json"),
            "variants": len(manifest.variants),
            "dirty_source": manifest.source_binding.dirty,
        }, sort_keys=True))
        return 0
    if args.command == "run":
        try:
            report = run_manifest(args.manifest)
        except DiagnosticManifestMismatch as exc:
            print(f"HASH_MISMATCH: {exc}", file=sys.stderr)
            return 2
        except (DiagnosticLimitError, DiagnosticTimeoutError) as exc:
            print(f"LIMIT_OR_TIMEOUT: {exc}", file=sys.stderr)
            return 3
        except DiagnosticInputError as exc:
            print(f"UNAVAILABLE_INPUT: {exc}", file=sys.stderr)
            return 3
        except DiagnosticPreparationError as exc:
            print(f"INVALID_INPUT: {exc}", file=sys.stderr)
            return 2
        except DiagnosticWorkerError as exc:
            print(f"WORKER_FAILURE: {exc}", file=sys.stderr)
            return 4
        print(json.dumps({
            "status": report.run_status.value,
            "complete": report.complete,
            "manifest_digest": report.manifest_digest,
            "semantic_result_digest": report.semantic_result_digest,
            "report": str(Path(args.manifest).resolve().parent / "report.json"),
        }, sort_keys=True))
        return 0 if report.complete else 3
    if args.command == "_worker":
        try:
            report = run_manifest_inline(args.manifest, args.output_dir)
        except DiagnosticManifestMismatch as exc:
            print(f"HASH_MISMATCH: {exc}", file=sys.stderr)
            return 2
        except (DiagnosticLimitError, DiagnosticInputError) as exc:
            print(f"INCOMPLETE_INPUT: {exc}", file=sys.stderr)
            return 3
        except (DiagnosticPreparationError, ValueError, OSError) as exc:
            print(f"INVALID_INPUT: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"WORKER_FAILURE: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return 4
        return 0 if report.complete else 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
