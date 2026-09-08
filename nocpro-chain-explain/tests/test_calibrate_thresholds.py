"""Tests for the threshold calibration benchmark module."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from benchmarks.calibrate_thresholds import (
    _quantile,
    calculate_temporal_gaps,
    load_packages_from_directory,
    run_calibration,
)
from configuration import load_analysis_config


def test_quantile_calculation() -> None:
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _quantile(data, 0.0) == 10.0
    assert _quantile(data, 1.0) == 50.0
    assert _quantile(data, 0.5) == 30.0


def test_calibration_generates_valid_yaml_and_report(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    synthetic_dir = repo_root.parent / "nocpro-mock" / "docs" / "examples" / "synthetic"
    
    packages = []
    if synthetic_dir.is_dir():
        packages = load_packages_from_directory(synthetic_dir)

    out_yaml = tmp_path / "calibrated.yaml"
    report_json = tmp_path / "report.json"

    base_raw, report = run_calibration(
        packages=packages,
        base_config_yaml=repo_root / "config" / "thresholds" / "v1.yaml",
        output_yaml=out_yaml,
        report_json=report_json,
        database_url="postgresql+asyncpg://nocpro:nocpro@localhost:5432/nocpro",
    )

    assert out_yaml.exists()
    assert report_json.exists()

    # Must be readable by load_analysis_config without schema errors
    config = load_analysis_config(out_yaml)
    assert config.config_version == "v1-calibrated"
    assert config.value("temporal.burst.gap_seconds") > 0
    assert config.value("role.s_min") >= config.value("role.s_weak")

    # Verify report structure
    report_data = json.loads(report_json.read_text(encoding="utf-8"))
    assert report_data["output_config_path"] == str(out_yaml)
    assert len(report_data["calibrated_parameters"]) > 0
    assert "postgresql+asyncpg://nocpro:****@localhost:5432/nocpro" in report_data["database_url_masked"]
    assert "chains_loaded" in report_data
    assert "chains_evaluated" in report_data
    assert "chains_skipped_large" in report_data
    assert "chains_failed" in report_data
    assert report.chains_loaded >= report.chains_evaluated

