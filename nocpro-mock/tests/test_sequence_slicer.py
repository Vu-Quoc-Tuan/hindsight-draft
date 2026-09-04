"""Unit tests for time-window sequential snapshot slicer."""

from __future__ import annotations

import json
from pathlib import Path
import yaml
import pytest

from nocpro_mock.cli import main
from nocpro_mock.replay.sequence_slicer import DERIVED_REPLAY_SOURCE, slice_alarm_sequence
from nocpro_mock.contract import parse_package


@pytest.fixture
def sample_alarm_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "sample_alarms.csv"
    csv_file.write_text(
        'cah.id,chaining_id,alarm_name,fault_id,group_name,cah.start_time,cah.create_time,end_time\n'
        '1,100,Interface down,47933128,Core Event,2026-08-01 10:00:00,2026-08-01 10:00:00,2026-08-01 10:20:00\n'
        '2,100,CBS. Power Warning,715054,Core Power,2026-08-01 10:05:00,2026-08-01 10:05:00,2026-08-01 10:25:00\n'
        '3,101,BGP Down,47933081,Core Event,2026-08-01 10:10:00,2026-08-01 10:10:00,2026-08-01 10:30:00\n'
        '4,102,High Temperature,500000009,Environment,2026-08-01 10:15:00,2026-08-01 10:15:00,2026-08-01 10:45:00\n'
        '5,100,Loop VSI,716891,Syslog,2026-08-01 10:22:00,2026-08-01 10:22:00,2026-08-01 10:50:00\n',
        encoding="utf-8",
    )
    return csv_file


def test_slice_alarm_sequence_creates_valid_sequence(tmp_path: Path, sample_alarm_csv: Path) -> None:
    out_dir = tmp_path / "seq_out"
    summary = slice_alarm_sequence(
        alarm_csv_path=sample_alarm_csv,
        output_dir=out_dir,
        scenario_id="test_slice_v1",
        num_snapshots=4,
        step_minutes=5,
        window_minutes=10,
    )

    assert summary.snapshot_count == 4
    assert (out_dir / "sequence.yaml").exists()
    assert (out_dir / "snapshot_000.json").exists()
    assert (out_dir / "snapshot_001.json").exists()
    assert (out_dir / "snapshot_002.json").exists()
    assert (out_dir / "snapshot_003.json").exists()

    with (out_dir / "sequence.yaml").open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    assert manifest["scenario_id"] == "test_slice_v1"
    assert manifest["sequence_type"] == "EVOLUTION"
    assert manifest["derivation_kind"] == "DERIVED_REPLAY"
    assert manifest["production_validation"] == "NOT_ESTABLISHED"
    assert len(manifest["snapshots"]) == 4

    package = parse_package(json.loads((out_dir / "snapshot_000.json").read_text(encoding="utf-8")))
    assert package.snapshot.source == DERIVED_REPLAY_SOURCE
    assert package.snapshot.source_kind.value == "REAL_EXPORT_REPLAY"
    assert "PRODUCTION_EVOLUTION_VALIDATION_NOT_ESTABLISHED" in package.provenance_manifest.notes


def test_cli_slice_sequence(tmp_path: Path, sample_alarm_csv: Path) -> None:
    out_dir = tmp_path / "cli_seq_out"
    exit_code = main([
        "slice-sequence",
        "--alarm-csv", str(sample_alarm_csv),
        "--output-dir", str(out_dir),
        "--snapshots", "3",
        "--step-minutes", "5",
        "--window-minutes", "10",
    ])
    assert exit_code == 0
    assert (out_dir / "sequence.yaml").exists()
    assert (out_dir / "snapshot_002.json").exists()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"num_snapshots": 0}, "num_snapshots"),
        ({"step_minutes": 0}, "step_minutes"),
        ({"window_minutes": 0}, "window_minutes"),
        ({"max_chains_per_snapshot": 0}, "max_chains_per_snapshot"),
    ],
)
def test_slice_alarm_sequence_rejects_invalid_bounds(
    tmp_path: Path,
    sample_alarm_csv: Path,
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        slice_alarm_sequence(
            alarm_csv_path=sample_alarm_csv,
            output_dir=tmp_path / "invalid",
            **kwargs,
        )


def test_slice_alarm_sequence_is_deterministic_when_chains_are_bounded(
    tmp_path: Path,
    sample_alarm_csv: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    kwargs = {
        "alarm_csv_path": sample_alarm_csv,
        "scenario_id": "deterministic",
        "num_snapshots": 2,
        "step_minutes": 5,
        "window_minutes": 20,
        "max_chains_per_snapshot": 2,
    }
    slice_alarm_sequence(output_dir=first, **kwargs)
    slice_alarm_sequence(output_dir=second, **kwargs)

    assert (first / "sequence.yaml").read_bytes() == (second / "sequence.yaml").read_bytes()
    assert (first / "snapshot_000.json").read_bytes() == (second / "snapshot_000.json").read_bytes()


def test_slice_alarm_sequence_sanitizes_dirty_and_future_timestamps(tmp_path: Path) -> None:
    csv_file = tmp_path / "dirty_alarms.csv"
    csv_file.write_text(
        'cah.id,chaining_id,alarm_name,fault_id,group_name,cah.start_time,cah.create_time,end_time\n'
        '1,100,Valid Alarm,47933128,Core Event,2026-08-01 10:00:00,2026-08-01 10:00:00,2026-08-01 10:20:00\n'
        '2,100,Future 2098 Outlier,715054,Core Power,2098-08-01 10:05:00,2098-08-01 10:05:00,2098-08-01 10:25:00\n'
        '3,101,End Before Start,47933081,Core Event,2026-08-01 10:10:00,2026-08-01 10:10:00,2026-08-01 09:00:00\n',
        encoding="utf-8",
    )
    out_dir = tmp_path / "dirty_out"
    summary = slice_alarm_sequence(
        alarm_csv_path=csv_file,
        output_dir=out_dir,
        scenario_id="dirty_test",
        num_snapshots=3,
        step_minutes=5,
        window_minutes=15,
    )
    # The year 2098 alarm should be completely omitted from distinct alarms
    assert summary.total_distinct_alarms == 2
    package = parse_package(json.loads((out_dir / "snapshot_002.json").read_text(encoding="utf-8")))
    alarm_ids = {a.alarm_id for a in package.alarms}
    assert "2" not in alarm_ids
    assert "3" in alarm_ids
