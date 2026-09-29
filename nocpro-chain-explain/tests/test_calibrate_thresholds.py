"""Tests for the threshold calibration benchmark module."""

from __future__ import annotations

from pathlib import Path

from benchmarks.calibrate_thresholds import (
    _quantile,
    run_calibration,
)
from configuration import load_analysis_config


def test_quantile_calculation() -> None:
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _quantile(data, 0.0) == 10.0
    assert _quantile(data, 1.0) == 50.0
    assert _quantile(data, 0.5) == 30.0


def test_calibration_applies_valid_families_without_report(tmp_path: Path, monkeypatch) -> None:
    from benchmarks import calibrate_thresholds
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(calibrate_thresholds, "calculate_temporal_gaps", lambda packages: [45.0] * 5)
    monkeypatch.setattr(calibrate_thresholds, "calculate_support_scores", lambda packages, config_path: [0.4] * 10)
    monkeypatch.setattr(calibrate_thresholds, "calculate_conductance_values", lambda packages, **kwargs: [0.2] * 20)

    out_yaml = tmp_path / "calibrated.yaml"
    report_json = tmp_path / "report.json"

    base_raw, _ = run_calibration(
        packages=[],
        base_config_yaml=repo_root / "config" / "thresholds" / "v1.yaml",
        output_yaml=out_yaml,
        report_json=report_json,
        database_url="postgresql+asyncpg://nocpro:nocpro@localhost:5432/nocpro",
    )

    assert out_yaml.exists()
    assert not report_json.exists()

    # Must be readable by load_analysis_config without schema errors
    config = load_analysis_config(out_yaml)
    assert config.config_version.startswith("v1-calibrated-")
    assert config.value("temporal.burst.gap_seconds") == 45
    assert config.value("role.s_min") >= config.value("role.s_weak")
    assert config.value("audit.global_weak_baseline") == 0.2
    assert base_raw["status"] == "baseline_requires_calibration"
