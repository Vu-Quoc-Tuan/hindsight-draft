"""Calibrate analysis thresholds directly from historical data in PostgreSQL.

Connects to PostgreSQL (the system of record), queries historical snapshot
packages (SnapshotIngest.canonical_payload / Snapshot.raw_payload), computes empirical
distributions (temporal gaps, pair support, conductance on candidate cuts),
and writes a versioned DATA_DRIVEN threshold artifact (config/thresholds/calibrated.yaml)
accompanied by a machine-readable calibration report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
from audit.graph import build_audit_graph
from channels.evaluator import evaluate_pair_channels
from configuration import load_analysis_config

logger = logging.getLogger("calibrate_thresholds")

DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://nocpro:nocpro@localhost:5432/nocpro"
)
BASE_CONFIG_PATH = REPO_ROOT / "config" / "thresholds" / "v1.yaml"
DEFAULT_OUTPUT_YAML = REPO_ROOT / "config" / "thresholds" / "calibrated.yaml"
DEFAULT_REPORT_JSON = REPO_ROOT / "benchmarks" / "results" / "calibration_report.json"


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
                    query += "AND (source_kind IN ('REAL_LIVE', 'REAL_EXPORT_REPLAY') OR source_kind IS NULL) "
                query += "ORDER BY completed_at DESC NULLS LAST LIMIT 50;"

                result = await conn.execute(text(query))
                rows = result.fetchall()
                for row in rows:
                    if row[0]:
                        try:
                            pkg = load_validated_package(row[0])
                            if filter_real_only and getattr(pkg.snapshot, "source_kind", None) == "SYNTHETIC_TEST":
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
                        fallback_query += "AND (source_kind IN ('REAL_LIVE', 'REAL_EXPORT_REPLAY') OR source_kind IS NULL) "
                    fallback_query += "ORDER BY produced_at DESC LIMIT 50;"

                    result = await conn.execute(text(fallback_query))
                    rows = result.fetchall()
                    for row in rows:
                        if row[0]:
                            try:
                                pkg = load_validated_package(row[0])
                                if filter_real_only and getattr(pkg.snapshot, "source_kind", None) == "SYNTHETIC_TEST":
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
    """Compute intra-chain inter-alarm time intervals in seconds."""
    gaps: list[float] = []
    for package in packages:
        for chain in package.chains.values():
            alarm_ids = package.members_of(chain.chain_id)
            if len(alarm_ids) < 2:
                continue
            timestamps: list[float] = []
            for aid in alarm_ids:
                alarm = package.alarms.get(aid)
                if alarm:
                    t = parse_alarm_timestamp(
                        getattr(alarm, "canonical_start_time", None)
                        or getattr(alarm, "start_time", None)
                    )
                    if t is not None:
                        timestamps.append(t)
            if len(timestamps) >= 2:
                timestamps.sort()
                for i in range(len(timestamps) - 1):
                    delta = timestamps[i + 1] - timestamps[i]
                    if delta > 0:
                        gaps.append(delta)
    return gaps


def calculate_support_scores(packages: list[IngestedPackage]) -> list[float]:
    """Compute empirical pair channel support scores across members using temporal sampling."""
    scores: list[float] = []
    for package in packages:
        for chain in package.chains.values():
            members = package.members_of(chain.chain_id)
            if len(members) < 2:
                continue
            # Sort members by temporal order for representative sampling across chain duration
            alarm_objs = [(m, package.alarms.get(m)) for m in members]
            alarm_objs.sort(
                key=lambda item: parse_alarm_timestamp(
                    getattr(item[1], "canonical_start_time", None)
                    or getattr(item[1], "start_time", None)
                )
                or 0.0
            )
            sorted_members = [m for m, _ in alarm_objs]
            n = len(sorted_members)
            if n <= 15:
                sample_pairs = [
                    (sorted_members[i], sorted_members[j])
                    for i in range(n)
                    for j in range(i + 1, n)
                ]
            else:
                step = max(1, n // 10)
                selected = sorted_members[::step][:10]
                sample_pairs = [
                    (selected[i], selected[j])
                    for i in range(len(selected))
                    for j in range(i + 1, len(selected))
                ]
            for a, b in sample_pairs:
                try:
                    channels = evaluate_pair_channels(
                        package,
                        chain.chain_id,
                        a,
                        b,
                        delay_threshold=0.5,
                        d_max=3,
                        lambda_dep=2.0,
                        common_dependency_threshold=0.3,
                        silent_gap_seconds=120,
                    )
                    for c in channels:
                        if c.support_score is not None and c.support_score > 0:
                            scores.append(float(c.support_score))
                except Exception:
                    continue
    return scores


def calculate_conductance_values(packages: list[IngestedPackage]) -> list[float]:
    """Compute conductance across chains with >= 10 members using multi-cut approximation."""
    conductances: list[float] = []
    for package in packages:
        for chain in package.chains.values():
            members = package.members_of(chain.chain_id)
            if is_chain_too_small_for_audit(len(members), small_chain_threshold=10):
                continue
            try:
                # Build audit graph
                pair_channel_values = {}
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        a, b = members[i], members[j]
                        pair_channel_values[(a, b)] = evaluate_pair_channels(
                            package,
                            chain.chain_id,
                            a,
                            b,
                            delay_threshold=0.5,
                            d_max=3,
                            lambda_dep=2.0,
                            common_dependency_threshold=0.3,
                            silent_gap_seconds=120,
                        )
                audit_graph = build_audit_graph(members, pair_channel_values)
                # Compute conductance of multiple candidate sweep cuts
                n = len(members)
                best_phi: float | None = None
                cut_fractions = (0.25, 0.33, 0.50, 0.67, 0.75)
                for frac in cut_fractions:
                    k = max(1, min(n - 1, int(n * frac)))
                    subset = set(members[:k])
                    comp = set(members[k:])
                    vol_s = sum(audit_graph.degree(u) for u in subset)
                    vol_c = sum(audit_graph.degree(v) for v in comp)
                    denom = min(vol_s, vol_c)
                    if denom > 0:
                        cut_weight = sum(
                            audit_graph.edge_weight(u, v)
                            for u in subset
                            for v in comp
                        )
                        phi = cut_weight / denom
                        if best_phi is None or phi < best_phi:
                            best_phi = phi
                if best_phi is not None:
                    conductances.append(best_phi)
            except Exception:
                continue
    return conductances


def run_calibration(
    packages: list[IngestedPackage],
    base_config_yaml: Path = BASE_CONFIG_PATH,
    output_yaml: Path = DEFAULT_OUTPUT_YAML,
    report_json: Path = DEFAULT_REPORT_JSON,
    database_url: str = DEFAULT_DATABASE_URL,
) -> tuple[dict[str, Any], CalibrationReport]:
    """Execute calibration math and write calibrated YAML and report."""
    base_raw = yaml.safe_load(base_config_yaml.read_text(encoding="utf-8"))
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

    base_raw.setdefault("temporal", {}).setdefault("burst", {})["gap_seconds"] = {
        "value": chosen_gap,
        "source": source_gap,
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
    supports = calculate_support_scores(packages)
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

    base_raw.setdefault("role", {})["s_min"] = {
        "value": chosen_s_min,
        "source": source_sup,
    }
    base_raw.setdefault("role", {})["s_weak"] = {
        "value": chosen_s_weak,
        "source": source_sup,
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
    phis = calculate_conductance_values(packages)
    prev_baseline = base_raw.get("audit", {}).get("global_weak_baseline", {}).get("value", 0.30)
    prev_rho = base_raw.get("audit", {}).get("rho", {}).get("value", 0.20)
    if len(phis) >= 5:
        eps_result = calibrate_epsilon(full_bin=phis, coarse_bin=None, n_min=5, quantile=0.05)
        chosen_baseline = round(eps_result.epsilon, 3)
        source_phi = "DATA_DRIVEN"
        p_details_phi = {
            "level": eps_result.level,
            "sample_count": eps_result.sample_count,
            "low_confidence": eps_result.low_confidence,
            "p05": round(_quantile(phis, 0.05), 3),
            "p50": round(_quantile(phis, 0.50), 3),
        }
    else:
        chosen_baseline = prev_baseline
        source_phi = "DOCUMENTED_DEFAULT"
        p_details_phi = {"reason": "insufficient_conductance_samples", "fallback": prev_baseline}

    base_raw.setdefault("audit", {})["global_weak_baseline"] = {
        "value": chosen_baseline,
        "source": source_phi,
    }
    base_raw.setdefault("audit", {})["rho"] = {
        "value": prev_rho,
        "source": "DOCUMENTED_DEFAULT",
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

    # Update metadata
    base_raw["config_version"] = "v1-calibrated"
    core_paths = {
        "temporal.burst.gap_seconds",
        "role.s_min",
        "role.s_weak",
        "audit.global_weak_baseline",
    }
    core_params = [p for p in calibrated_params if p.path in core_paths]
    has_real_data = bool(packages) and all(
        getattr(pkg.snapshot, "source_kind", None) not in {"SYNTHETIC_TEST"}
        for pkg in packages
    )
    all_core_data_driven = (
        len(core_params) == 4
        and all(p.source == "DATA_DRIVEN" for p in core_params)
        and all(p.sample_count >= 10 for p in core_params)
    )
    is_prod_calibrated = has_real_data and all_core_data_driven
    base_raw["status"] = (
        "PRODUCTION_CALIBRATED"
        if is_prod_calibrated
        else "baseline_requires_calibration"
    )

    # Counterfactual policy:
    # Counterfactual triggers (membership_support_below, minimum_*_improvement, etc.)
    # require operator ground-truth correction labels (split/merge/remove ground truth)
    # which are not yet available.
    # Therefore, counterfactual policy MUST remain SYNTHETIC_ONLY (heuristic baseline)
    # and MUST NOT claim PRODUCTION_CALIBRATED without empirical operator correction data.
    if "counterfactual" not in base_raw:
        base_raw["counterfactual"] = {
            "config_version": "v1-calibrated-counterfactual",
            "calibration_status": "SYNTHETIC_ONLY",
            "limits": {
                "max_chain_members": 200,
                "max_remove_candidates": 10,
                "max_split_candidates": 10,
                "max_recommendations": 5,
            },
            "move": {
                "max_candidates": 10,
            },
            "merge": {
                "max_candidates": 10,
            },
            "remove_triggers": {
                "membership_support_below": 0.3,
                "representativeness_below": 0.3,
                "adverse_margin_below": 0.0,
            },
            "improvement": {
                "minimum_membership_improvement": 0.05,
                "minimum_coverage_improvement": 0.05,
                "minimum_conductance_improvement": 0.05,
                "pareto_tolerance": 0.0,
            },
        }
    elif isinstance(base_raw["counterfactual"], dict):
        base_raw["counterfactual"]["calibration_status"] = base_raw["counterfactual"].get("calibration_status", "SYNTHETIC_ONLY")

    base_raw["notes"] = [
        f"Calibrated at {datetime.now(timezone.utc).isoformat()} from PostgreSQL system of record.",
        f"Evaluated {len(packages)} snapshots, {total_chains} chains, {total_alarms} alarms.",
        "Calibrated DATA_DRIVEN values preserve empirical distribution evidence; DOCUMENTED_DEFAULT indicates fallback.",
        "audit.rho and counterfactual thresholds remain heuristic DOCUMENTED_DEFAULT / SYNTHETIC_ONLY until operator correction ground-truth is available.",
    ]

    # Save output YAML
    output_yaml.parent.mkdir(parents=True, exist_ok=True)
    with output_yaml.open("w", encoding="utf-8") as f:
        yaml.dump(base_raw, f, sort_keys=False)

    report = CalibrationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        database_url_masked=_mask_url(database_url),
        snapshots_loaded=len(packages),
        chains_evaluated=total_chains,
        alarms_evaluated=total_alarms,
        calibrated_parameters=calibrated_params,
        output_config_path=str(output_yaml),
        status=base_raw["status"],
    )

    # Save report JSON
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    return base_raw, report


async def calibrate_from_postgres(
    database_url: str | None = None,
    base_config_path: Path | None = None,
    output_yaml: Path | None = None,
    report_json: Path | None = None,
    include_fixtures: bool = False,
    fallback_dir: Path | None = None,
) -> CalibrationReport:
    """Entry point for programmatic calibration from backend services."""
    target_db_url = database_url or DEFAULT_DATABASE_URL
    packages = await fetch_packages_from_db(target_db_url)
    
    if (not packages or include_fixtures) and fallback_dir:
        extra = load_packages_from_directory(fallback_dir)
        packages.extend(extra)

    _, report = run_calibration(
        packages=packages,
        base_config_yaml=base_config_path or BASE_CONFIG_PATH,
        output_yaml=output_yaml or DEFAULT_OUTPUT_YAML,
        report_json=report_json or DEFAULT_REPORT_JSON,
        database_url=target_db_url,
    )
    return report


async def async_main(args: argparse.Namespace) -> None:
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
        print("Warning: No snapshot packages found in PostgreSQL or fallback directory.")
        print("Proceeding with baseline config structure.")

    base_raw, report = run_calibration(
        packages=packages,
        base_config_yaml=Path(args.base_config),
        output_yaml=Path(args.output),
        report_json=Path(args.report),
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
        "--report",
        default=str(DEFAULT_REPORT_JSON),
        help="Path to write JSON calibration report",
    )
    parser.add_argument(
        "--fallback-dir",
        default=str(REPO_ROOT.parent / "nocpro-mock" / "docs" / "examples" / "synthetic"),
        help="Fallback directory if DB has no packages",
    )
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
