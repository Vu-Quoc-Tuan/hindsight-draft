"""Calibrate analysis thresholds directly from historical data in PostgreSQL.

Connects to PostgreSQL, measures contextual gaps, canonical member support and
canonical Audit candidate conductance, then atomically applies eligible threshold
families to a versioned config. Distributional calibration does not validate
operational accuracy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import hashlib
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (
    REPO_ROOT,
    REPO_ROOT / "services" / "analysis-worker",
    REPO_ROOT / "services" / "api",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from libs.contracts import IngestedPackage, load_validated_package
from audit.conductance import calibrate_epsilon, is_chain_too_small_for_audit
from audit_diagnostics.capture import capture_exact_audit_inputs
from audit_diagnostics.contracts import CandidateScoreStatus, ResourceLimits
from audit_diagnostics.scope import load_scope_policy
from channels.indexed_evaluator import evaluate_chain_indexed
from channels.semantic import EMPTY_TAXONOMY
from channels.temporal import DEFAULT_CONTEXT_FIELDS, context_key
from configuration import AnalysisConfig, load_analysis_config
from groups.fit_from_index import membership_support_from_index

logger = logging.getLogger("calibrate_thresholds")

DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://nocpro:nocpro@localhost:5432/nocpro"
)
BASE_CONFIG_PATH = REPO_ROOT / "config" / "thresholds" / "v1.yaml"
DEFAULT_OUTPUT_YAML = REPO_ROOT / "config" / "thresholds" / "calibrated.yaml"


@dataclass(frozen=True)
class ParameterCalibration:
    path: str
    previous_value: float | int
    calibrated_value: float | int
    source: str
    sample_count: int
    metric_details: dict[str, Any]


@dataclass(frozen=True)
class CalibrationReport:
    timestamp: str
    database_url_masked: str
    snapshots_loaded: int
    chains_evaluated: int
    alarms_evaluated: int
    calibrated_parameters: list[ParameterCalibration]
    output_config_path: str
    status: str
    chains_loaded: int = 0
    chains_skipped_large: int = 0
    chains_failed: int = 0


def _mask_url(url: str) -> str:
    if "@" in url:
        prefix, host_part = url.split("@", 1)
        scheme_user = prefix.split(":", 2)
        if len(scheme_user) >= 3:
            return f"{scheme_user[0]}:{scheme_user[1]}:****@{host_part}"
    return url


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("Cannot calculate quantile of empty list")
    ordered = sorted(values)
    idx = (len(ordered) - 1) * q
    lower = int(idx)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = idx - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _canonical_payload_value(value: Any) -> Any:
    """Convert an ingested package to deterministic JSON-compatible values."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _canonical_payload_value(asdict(value))
    if isinstance(value, dict):
        return {
            str(key): _canonical_payload_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_payload_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_canonical_payload_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported snapshot payload value: {type(value).__name__}")


def deduplicate_snapshot_packages(
    packages: list[IngestedPackage],
) -> list[IngestedPackage]:
    """Remove identical snapshot repeats and reject conflicting snapshot identities."""
    unique: dict[tuple[str, str], tuple[str, IngestedPackage]] = {}
    for package in packages:
        snapshot_id = str(getattr(package.snapshot, "snapshot_id", "") or "")
        snapshot_version = str(getattr(package.snapshot, "snapshot_version", "") or "")
        if not snapshot_id or not snapshot_version:
            raise ValueError(
                "Calibration requires a stable snapshot_id and snapshot_version"
            )
        identity = (snapshot_id, snapshot_version)
        canonical = _canonical_payload_value(package)
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        previous = unique.get(identity)
        if previous is None:
            unique[identity] = (digest, package)
        elif previous[0] != digest:
            raise ValueError(
                "Conflicting calibration payloads share snapshot identity "
                f"{snapshot_id!r}/{snapshot_version!r}"
            )
    return [package for _, package in unique.values()]


async def fetch_packages_from_db(
    database_url: str,
    filter_real_only: bool = True,
) -> list[IngestedPackage]:
    """Load canonical snapshot packages stored in PostgreSQL, filtering for verified production sources."""
    engine = create_async_engine(database_url)
    packages: list[IngestedPackage] = []
    try:
        async with engine.connect() as conn:
            # First try snapshot_ingest canonical_payload
            try:
                query = (
                    "SELECT canonical_payload FROM snapshot_ingest "
                    "WHERE canonical_payload IS NOT NULL "
                )
                if filter_real_only:
                    query += "AND source_kind IN ('REAL_LIVE', 'REAL_EXPORT_REPLAY') "
                query += "ORDER BY completed_at DESC NULLS LAST LIMIT 50;"

                result = await conn.execute(text(query))
                rows = result.fetchall()
                for row in rows:
                    if row[0]:
                        try:
                            pkg = load_validated_package(row[0])
                            if filter_real_only and getattr(pkg.snapshot, "source_kind", None) not in {"REAL_LIVE", "REAL_EXPORT_REPLAY"}:
                                continue
                            packages.append(pkg)
                        except Exception as exc:
                            logger.warning("Failed parsing snapshot_ingest package: %s", exc)
            except Exception as exc:
                logger.info("snapshot_ingest query skipped: %s", exc)

            # Fallback / supplement with snapshots.raw_payload
            if not packages:
                try:
                    fallback_query = (
                        "SELECT raw_payload FROM snapshots "
                        "WHERE raw_payload IS NOT NULL "
                    )
                    if filter_real_only:
                        fallback_query += "AND source_kind IN ('REAL_LIVE', 'REAL_EXPORT_REPLAY') "
                    fallback_query += "ORDER BY produced_at DESC LIMIT 50;"

                    result = await conn.execute(text(fallback_query))
                    rows = result.fetchall()
                    for row in rows:
                        if row[0]:
                            try:
                                pkg = load_validated_package(row[0])
                                if filter_real_only and getattr(pkg.snapshot, "source_kind", None) not in {"REAL_LIVE", "REAL_EXPORT_REPLAY"}:
                                    continue
                                packages.append(pkg)
                            except Exception as exc:
                                logger.warning("Failed parsing snapshot raw_payload: %s", exc)
                except Exception as exc:
                    logger.info("snapshots query skipped: %s", exc)
    finally:
        await engine.dispose()

    return packages


def load_packages_from_directory(dir_path: Path) -> list[IngestedPackage]:
    """Load seed fixture packages from disk as a fallback or bootstrap."""
    packages: list[IngestedPackage] = []
    if not dir_path.is_dir():
        return packages
    for json_file in sorted(dir_path.glob("**/*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "snapshot" in data and "chains" in data:
                packages.append(load_validated_package(data))
        except Exception:
            continue
    return packages


def parse_alarm_timestamp(ts_str: str | None) -> float | None:
    if not ts_str:
        return None
    try:
        # Normalize ISO formats
        clean = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.timestamp()
    except Exception:
        return None


def calculate_temporal_gaps(packages: list[IngestedPackage]) -> list[float]:
    """Compute adjacent inter-alarm gaps within the same T_burst context."""
    gaps: list[float] = []
    for package in packages:
        for chain in package.chains.values():
            try:
                alarm_ids = package.members_of(chain.chain_id)
                if len(alarm_ids) < 2:
                    continue
                timestamps_by_context: dict[str, list[float]] = {}
                for aid in alarm_ids:
                    alarm = package.alarms.get(aid)
                    if alarm:
                        context = context_key(alarm, DEFAULT_CONTEXT_FIELDS)
                        t = parse_alarm_timestamp(
                            getattr(alarm, "canonical_start_time", None)
                            or getattr(alarm, "start_time", None)
                        )
                        if context is not None and t is not None:
                            timestamps_by_context.setdefault(context, []).append(t)
                for timestamps in timestamps_by_context.values():
                    timestamps.sort()
                    for i in range(len(timestamps) - 1):
                        delta = timestamps[i + 1] - timestamps[i]
                        if delta > 0:
                            gaps.append(delta)
            except Exception as exc:
                logger.warning(
                    "Temporal calibration skipped snapshot=%s/%s chain=%s: %s",
                    package.snapshot.snapshot_id,
                    package.snapshot.snapshot_version,
                    chain.chain_id,
                    exc,
                )
    return gaps


def calculate_support_scores(
    packages: list[IngestedPackage],
    config_path: Path = BASE_CONFIG_PATH,
    *,
    analysis_config: AnalysisConfig | None = None,
) -> list[float]:
    """Sample the actual member MembershipSupport used by Role, including zero."""
    config = analysis_config or load_analysis_config(config_path)
    scores: list[float] = []
    for package in packages:
        for chain in package.chains.values():
            try:
                members = package.members_of(chain.chain_id)
                if len(members) < 2:
                    continue
                evidence = evaluate_chain_indexed(
                    package,
                    chain.chain_id,
                    taxonomy=EMPTY_TAXONOMY,
                    silent_gap_seconds=int(
                        config.value("temporal.burst.gap_seconds")
                    ),
                    d_max=int(config.value("dependency.max_hop")),
                )
                for member in evidence.members:
                    support = membership_support_from_index(
                        member, evidence.statistics
                    ).support
                    if support is not None:
                        scores.append(float(support))
            except Exception as exc:
                logger.warning(
                    "MembershipSupport calibration skipped snapshot=%s/%s chain=%s: %s",
                    package.snapshot.snapshot_id,
                    package.snapshot.snapshot_version,
                    chain.chain_id,
                    exc,
                )
    return scores


MAX_AUDIT_CALIBRATION_MEMBERS = 200


def calculate_conductance_values(
    packages: list[IngestedPackage],
    *,
    config_path: Path = BASE_CONFIG_PATH,
    analysis_config: AnalysisConfig | None = None,
    max_members: int = MAX_AUDIT_CALIBRATION_MEMBERS,
    skipped_large_chains: list[dict[str, Any]] | None = None,
    failed_chains: list[dict[str, Any]] | None = None,
) -> list[float]:
    """Sample scorable canonical Audit candidates; never score arbitrary member prefixes."""
    config = analysis_config or load_analysis_config(config_path)
    scope = load_scope_policy(REPO_ROOT / "config" / "audit_diagnostics" / "scope-v1.yaml")
    conductances: list[float] = []
    for package in packages:
        for chain in package.chains.values():
            members = package.members_of(chain.chain_id)
            if is_chain_too_small_for_audit(len(members), small_chain_threshold=10):
                continue
            if len(members) > max_members:
                if skipped_large_chains is not None:
                    skipped_large_chains.append({
                        "chain_id": chain.chain_id,
                        "member_count": len(members),
                        "reason": f"EXCEEDS_MAX_AUDIT_CALIBRATION_MEMBERS ({max_members})",
                    })
                continue
            try:
                captured = capture_exact_audit_inputs(
                    package, chain.chain_id, analysis_config=config, scope_policy=scope,
                    limits=ResourceLimits(max_members=max_members),
                    epsilon_phi=float(config.value("audit.global_weak_baseline")),
                )
                scored = [score.phi for score in captured.baseline_scores
                          if score.status is CandidateScoreStatus.SCORABLE and score.phi is not None]
                if scored:
                    conductances.append(min(scored))
            except Exception as exc:
                if failed_chains is not None:
                    failed_chains.append({
                        "chain_id": chain.chain_id,
                        "error": str(exc),
                    })
                logger.warning("Audit calibration skipped chain %s: %s", chain.chain_id, exc)
    return conductances


def run_calibration(
    packages: list[IngestedPackage],
    base_config_yaml: Path = BASE_CONFIG_PATH,
    output_yaml: Path = DEFAULT_OUTPUT_YAML,
    report_json: Path | None = None,
    database_url: str = DEFAULT_DATABASE_URL,
    active_config: AnalysisConfig | None = None,
) -> tuple[dict[str, Any], CalibrationReport]:
    """Apply only measurable threshold families; validate before atomic replacement."""
    packages = deduplicate_snapshot_packages(packages)
    base_raw = yaml.safe_load(base_config_yaml.read_text(encoding="utf-8"))
    measurement_config = active_config or load_analysis_config(base_config_yaml)
    # Calibration runs against the workspace's actual in-memory values, which
    # can include operator edits not yet persisted to the startup YAML.
    for parameter_path, configured in measurement_config.parameters.items():
        target: dict[str, Any] = base_raw
        path_parts = parameter_path.split(".")
        for part in path_parts[:-1]:
            nested = target.get(part)
            if not isinstance(nested, dict):
                nested = {}
                target[part] = nested
            target = nested
        target[path_parts[-1]] = {
            "value": configured.value,
            "source": configured.source.value,
        }
    base_raw["status"] = measurement_config.status
    calibrated_params: list[ParameterCalibration] = []

    total_chains = sum(len(p.chains) for p in packages)
    total_alarms = sum(len(p.alarms) for p in packages)

    # 1. Temporal gap calibration
    gaps = calculate_temporal_gaps(packages)
    prev_gap = base_raw.get("temporal", {}).get("burst", {}).get("gap_seconds", {}).get("value", 120)
    if len(gaps) >= 5:
        p95_gap = _quantile(gaps, 0.95)
        chosen_gap = max(30, min(600, int(round(p95_gap))))
        sample_count_gap = len(gaps)
        p_details_gap = {
            "p50": round(_quantile(gaps, 0.50), 2),
            "p90": round(_quantile(gaps, 0.90), 2),
            "p95": round(p95_gap, 2),
            "min": round(min(gaps), 2),
            "max": round(max(gaps), 2),
        }
        source_gap = "DATA_DRIVEN"
    else:
        chosen_gap = prev_gap
        sample_count_gap = len(gaps)
        p_details_gap = {"reason": "insufficient_gap_samples", "fallback": prev_gap}
        source_gap = "DOCUMENTED_DEFAULT"

    if source_gap == "DATA_DRIVEN":
        base_raw.setdefault("temporal", {}).setdefault("burst", {})["gap_seconds"] = {
            "value": chosen_gap, "source": source_gap,
        }
    calibrated_params.append(
        ParameterCalibration(
            path="temporal.burst.gap_seconds",
            previous_value=prev_gap,
            calibrated_value=chosen_gap,
            source=source_gap,
            sample_count=sample_count_gap,
            metric_details=p_details_gap,
        )
    )

    # 2. Pair support scores calibration (role.s_min, role.s_weak)
    try:
        supports = calculate_support_scores(
            packages, base_config_yaml, analysis_config=measurement_config
        )
    except Exception as exc:
        logger.warning("MembershipSupport calibration unavailable: %s", exc)
        supports = []
    prev_s_min = base_raw.get("role", {}).get("s_min", {}).get("value", 0.60)
    prev_s_weak = base_raw.get("role", {}).get("s_weak", {}).get("value", 0.30)
    if len(supports) >= 10:
        p25_sup = _quantile(supports, 0.25)
        p50_sup = _quantile(supports, 0.50)
        chosen_s_weak = max(0.15, min(0.45, round(p25_sup, 2)))
        chosen_s_min = max(chosen_s_weak + 0.15, min(0.85, round(p50_sup, 2)))
        source_sup = "DATA_DRIVEN"
        p_details_s = {
            "p25": round(p25_sup, 3),
            "p50": round(p50_sup, 3),
            "p75": round(_quantile(supports, 0.75), 3),
        }
    else:
        chosen_s_min = prev_s_min
        chosen_s_weak = prev_s_weak
        source_sup = "DOCUMENTED_DEFAULT"
        p_details_s = {"reason": "insufficient_support_samples", "fallback": [prev_s_min, prev_s_weak]}

    if source_sup == "DATA_DRIVEN":
        base_raw.setdefault("role", {})["s_min"] = {
            "value": chosen_s_min, "source": source_sup,
        }
        base_raw.setdefault("role", {})["s_weak"] = {
            "value": chosen_s_weak, "source": source_sup,
        }
    calibrated_params.append(
        ParameterCalibration(
            path="role.s_min",
            previous_value=prev_s_min,
            calibrated_value=chosen_s_min,
            source=source_sup,
            sample_count=len(supports),
            metric_details=p_details_s,
        )
    )
    calibrated_params.append(
        ParameterCalibration(
            path="role.s_weak",
            previous_value=prev_s_weak,
            calibrated_value=chosen_s_weak,
            source=source_sup,
            sample_count=len(supports),
            metric_details=p_details_s,
        )
    )

    # 3. Conductance & epsilon calibration (audit.global_weak_baseline, audit.rho)
    skipped_large_chains: list[dict[str, Any]] = []
    failed_chains: list[dict[str, Any]] = []
    try:
        phis = calculate_conductance_values(
            packages,
            config_path=base_config_yaml,
            analysis_config=measurement_config,
            skipped_large_chains=skipped_large_chains,
            failed_chains=failed_chains,
        )
    except Exception as exc:
        logger.warning("Audit calibration unavailable: %s", exc)
        phis = []
    prev_baseline = base_raw.get("audit", {}).get("global_weak_baseline", {}).get("value", 0.30)
    prev_rho = base_raw.get("audit", {}).get("rho", {}).get("value", 0.20)
    audit_config = measurement_config
    audit_n_min = int(audit_config.value("audit.calibration_n_min"))
    audit_quantile = float(audit_config.value("audit.calibration_quantile"))
    if len(phis) >= audit_n_min:
        eps_result = calibrate_epsilon(full_bin=phis, coarse_bin=None, n_min=audit_n_min, quantile=audit_quantile)
        chosen_baseline = round(eps_result.epsilon, 3)
        source_phi = "DATA_DRIVEN"
        p_details_phi = {
            "level": eps_result.level,
            "sample_count": eps_result.sample_count,
            "low_confidence": eps_result.low_confidence,
            "quantile": audit_quantile,
            "quantile_value": round(_quantile(phis, audit_quantile), 3),
            "p50": round(_quantile(phis, 0.50), 3),
        }
    else:
        chosen_baseline = prev_baseline
        source_phi = "DOCUMENTED_DEFAULT"
        p_details_phi = {"reason": "insufficient_conductance_samples", "fallback": prev_baseline, "sample_count": len(phis)}

    if skipped_large_chains:
        p_details_phi["skipped_large_chains"] = skipped_large_chains
    if failed_chains:
        p_details_phi["failed_chains"] = failed_chains

    if source_phi == "DATA_DRIVEN":
        base_raw.setdefault("audit", {})["global_weak_baseline"] = {
            "value": chosen_baseline, "source": source_phi,
        }
    calibrated_params.append(
        ParameterCalibration(
            path="audit.global_weak_baseline",
            previous_value=prev_baseline,
            calibrated_value=chosen_baseline,
            source=source_phi,
            sample_count=len(phis),
            metric_details=p_details_phi,
        )
    )
    calibrated_params.append(
        ParameterCalibration(
            path="audit.rho",
            previous_value=prev_rho,
            calibrated_value=prev_rho,
            source="DOCUMENTED_DEFAULT",
            sample_count=0,
            metric_details={"reason": "documented_default_not_data_driven", "fallback": prev_rho},
        )
    )

    applied = [item for item in calibrated_params if item.source == "DATA_DRIVEN"]
    if not applied:
        raise ValueError("No threshold family has enough valid samples to apply calibration")
    # Distribution quantiles alone do not establish operational quality.
    base_raw["status"] = "baseline_requires_calibration"

    # Counterfactual policy:
    # Counterfactual triggers (membership_support_below, minimum_*_improvement, etc.)
    # require operator ground-truth correction labels (split/merge/remove ground truth)
    # which are not yet available.
    # Therefore, counterfactual policy MUST remain SYNTHETIC_ONLY (heuristic baseline)
    # and MUST NOT claim PRODUCTION_CALIBRATED without empirical operator correction data.
    # Preserve counterfactual policy verbatim: this operation has no correction labels.

    # These sections belonged to the removed directed-topology analyzers.
    # Also drop them when an older base config is supplied to this command.
    base_raw.pop("propagation", None)
    base_raw.pop("dependency_scope", None)
    digest = hashlib.sha256(yaml.safe_dump(base_raw, sort_keys=True).encode()).hexdigest()[:12]
    base_raw["config_version"] = f"v1-calibrated-{digest}"

    chains_loaded = sum(len(p.chains) for p in packages)
    evaluated_chain_ids = set()
    for package in packages:
        for chain in package.chains.values():
            members = package.members_of(chain.chain_id)
            if len(members) >= 2:
                evaluated_chain_ids.add((getattr(package.snapshot, "snapshot_id", ""), chain.chain_id))
    chains_evaluated_count = len(evaluated_chain_ids)
    chains_skipped_large_count = len(skipped_large_chains)
    chains_failed_count = len(failed_chains)

    # Validate the complete candidate before replacing the active artifact.
    output_yaml.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_yaml.parent,
                                         prefix=f".{output_yaml.name}.", suffix=".tmp", delete=False) as file:
            temp_path = Path(file.name)
            yaml.safe_dump(base_raw, file, sort_keys=False)
            file.flush()
            os.fsync(file.fileno())
        load_analysis_config(temp_path)
        os.replace(temp_path, output_yaml)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    report = CalibrationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        database_url_masked=_mask_url(database_url),
        snapshots_loaded=len(packages),
        chains_loaded=chains_loaded,
        chains_evaluated=chains_evaluated_count,
        alarms_evaluated=total_alarms,
        calibrated_parameters=calibrated_params,
        output_config_path=str(output_yaml),
        status=base_raw["status"],
        chains_skipped_large=chains_skipped_large_count,
        chains_failed=chains_failed_count,
    )

    return base_raw, report


async def calibrate_from_postgres(
    database_url: str | None = None,
    base_config_path: Path | None = None,
    output_yaml: Path | None = None,
    report_json: Path | None = None,
    include_fixtures: bool = False,
    fallback_dir: Path | None = None,
    active_config: AnalysisConfig | None = None,
) -> CalibrationReport:
    """Entry point for programmatic calibration from backend services."""
    target_db_url = database_url or DEFAULT_DATABASE_URL
    packages = await fetch_packages_from_db(target_db_url)
    
    if (not packages or include_fixtures) and fallback_dir:
        extra = load_packages_from_directory(fallback_dir)
        packages.extend(extra)

    _, report = await asyncio.to_thread(
        run_calibration,
        packages=packages,
        base_config_yaml=base_config_path or BASE_CONFIG_PATH,
        output_yaml=output_yaml or DEFAULT_OUTPUT_YAML,
        report_json=report_json,
        database_url=target_db_url,
        active_config=active_config,
    )
    return report


async def async_main(args: argparse.Namespace) -> None:
    if args.fallback_dir and Path(args.output).resolve() == DEFAULT_OUTPUT_YAML.resolve():
        raise ValueError("Fixture calibration requires an explicit --output path")
    print(f"Connecting to PostgreSQL database at {_mask_url(args.database_url)}...")
    packages = await fetch_packages_from_db(args.database_url)
    print(f"Loaded {len(packages)} snapshot packages from PostgreSQL.")

    if (not packages or args.include_fixtures) and args.fallback_dir:
        fallback_path = Path(args.fallback_dir)
        print(f"Reading fixture packages from {fallback_path}...")
        fixtures = load_packages_from_directory(fallback_path)
        print(f"Loaded {len(fixtures)} fixture packages.")
        packages.extend(fixtures)

    if not packages:
        print("No snapshot packages found; no threshold will be changed.")

    base_raw, report = run_calibration(
        packages=packages,
        base_config_yaml=Path(args.base_config),
        output_yaml=Path(args.output),
        database_url=args.database_url,
    )

    print("\nCalibration Completed Successfully!")
    print(f"Output Config: {report.output_config_path}")
    print(f"Status: {report.status}")
    print(f"Snapshots: {report.snapshots_loaded} | Chains: {report.chains_evaluated} | Alarms: {report.alarms_evaluated}")
    print("Calibrated Parameters:")
    for p in report.calibrated_parameters:
        print(f"  - {p.path}: {p.previous_value} -> {p.calibrated_value} ({p.source}, n={p.sample_count})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate NocPro thresholds from PostgreSQL data.")
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
        help="PostgreSQL connection string (default: DATABASE_URL env var)",
    )
    parser.add_argument(
        "--include-fixtures",
        action="store_true",
        help="Include fallback fixture snapshots alongside DB data",
    )
    parser.add_argument(
        "--base-config",
        default=str(BASE_CONFIG_PATH),
        help="Base configuration YAML to calibrate from",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_YAML),
        help="Path to write calibrated YAML",
    )
    parser.add_argument(
        "--fallback-dir",
        default=None,
        help="Optional fixture directory; requires an explicit --output path",
    )
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
