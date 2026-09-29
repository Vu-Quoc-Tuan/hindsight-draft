"""Layer 2 — normalization tests (docs 13).

Core rule: raw values are preserved and dirty data is flagged, never repaired.
"""

from __future__ import annotations

import csv

import pytest

from nocpro_mock.contract import QualityFlag, SourceKind
from nocpro_mock.loaders.alarm_csv import AlarmCsvLoader
from nocpro_mock.normalize import build_chains, normalize_alarm

HEADER = ["chaining_id", "cah.id", "cah.start_time", "end_time", "device_code", "node_reference", "alarm_name"]


def _write_csv(path, rows, *, bom: bool = True):
    encoding = "utf-8-sig" if bom else "utf-8"
    with open(path, "w", newline="", encoding=encoding) as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def test_future_timestamp_is_flagged_not_repaired(tmp_path):
    path = _write_csv(
        tmp_path / "a.csv",
        [["1", "a1", "2098-01-01 00:00:00", "", "D1", "N1", "X"]],
    )
    record = AlarmCsvLoader(path).load()[0]
    assert QualityFlag.TIMESTAMP_FUTURE_OUTLIER.value in record.quality_flags
    # Raw string stays intact, but a flagged endpoint cannot drive analysis.
    assert record.raw_start_time == "2098-01-01 00:00:00"
    assert record.canonical_start_time is None


def test_end_before_start_is_flagged(tmp_path):
    path = _write_csv(
        tmp_path / "a.csv",
        [["1", "a1", "2026-01-02 10:00:00", "2026-01-01 09:00:00", "D1", "N1", "X"]],
    )
    record = AlarmCsvLoader(path).load()[0]
    assert QualityFlag.END_BEFORE_START.value in record.quality_flags
    assert record.canonical_start_time is not None
    assert record.canonical_end_time is None
    assert record.raw_end_time == "2026-01-01 09:00:00"


def test_future_end_is_unavailable_without_discarding_valid_start(tmp_path):
    path = _write_csv(
        tmp_path / "a.csv",
        [["1", "a1", "2026-01-02 10:00:00", "2098-01-01 09:00:00", "D1", "N1", "X"]],
    )
    record = AlarmCsvLoader(path).load()[0]
    assert QualityFlag.TIMESTAMP_FUTURE_OUTLIER.value in record.quality_flags
    assert record.canonical_start_time is not None
    assert record.canonical_end_time is None
    assert record.raw_end_time == "2098-01-01 09:00:00"


def test_invalid_timestamp_is_excluded_from_chain_span(tmp_path):
    path = _write_csv(
        tmp_path / "a.csv",
        [
            ["1", "a1", "2026-01-02 10:00:00", "", "D1", "N1", "X"],
            ["1", "a2", "2098-01-01 10:00:00", "", "D2", "N2", "X"],
            ["1", "a3", "2026-01-02 10:00:05", "", "D3", "N3", "X"],
        ],
    )
    records = AlarmCsvLoader(path).load()
    chains, _ = build_chains(
        records, snapshot_id="s1", source_kind=SourceKind.REAL_EXPORT_REPLAY
    )
    assert chains[0].event_span_seconds == 5


def test_unparseable_timestamp_flagged_and_canonical_is_none(tmp_path):
    path = _write_csv(
        tmp_path / "a.csv", [["1", "a1", "garbage", "", "D1", "N1", "X"]]
    )
    record = AlarmCsvLoader(path).load()[0]
    assert QualityFlag.UNPARSEABLE_TIMESTAMP.value in record.quality_flags
    assert record.canonical_start_time is None
    assert record.raw_start_time == "garbage"


def test_missing_fields_become_explicit_flags(tmp_path):
    path = _write_csv(tmp_path / "a.csv", [["1", "", "", "", "", "", ""]])
    record = AlarmCsvLoader(path).load()[0]
    for flag in (
        QualityFlag.MISSING_REQUIRED_ID,
        QualityFlag.MISSING_DEVICE_CODE,
        QualityFlag.MISSING_NODE_REFERENCE,
    ):
        assert flag.value in record.quality_flags
    assert record.device_code is None


def test_normalized_alarm_preserves_every_raw_column(tmp_path):
    path = _write_csv(
        tmp_path / "a.csv",
        [["7", "a7", "2026-01-01 00:00:00", "2026-01-01 00:00:05", "D1", "N1", "NAME"]],
    )
    record = AlarmCsvLoader(path).load()[0]
    alarm = normalize_alarm(
        record, snapshot_id="s1", source_kind=SourceKind.REAL_EXPORT_REPLAY
    )
    for column in HEADER:
        assert column in alarm.raw
    assert alarm.alarm_name == "NAME"
    assert alarm.canonical_start_time == "2026-01-01T00:00:00"


def test_singleton_chain_is_replayed(tmp_path):
    """73.37% of real chains are singletons; the path must not be special-cased away."""
    path = _write_csv(
        tmp_path / "a.csv",
        [["99", "a1", "2026-01-01 00:00:00", "", "D1", "N1", "X"]],
    )
    records = AlarmCsvLoader(path).load()
    chains, memberships = build_chains(
        records, snapshot_id="s1", source_kind=SourceKind.REAL_EXPORT_REPLAY
    )
    assert len(chains) == 1
    assert chains[0].member_count == 1
    assert chains[0].event_span_seconds == 0
    assert len(memberships) == 1


def test_chain_membership_matches_observed_partition(tmp_path):
    path = _write_csv(
        tmp_path / "a.csv",
        [
            ["1", "a1", "2026-01-01 00:00:00", "", "D1", "N1", "X"],
            ["1", "a2", "2026-01-01 00:00:10", "", "D1", "N1", "X"],
            ["2", "a3", "2026-01-01 00:00:00", "", "D2", "N2", "Y"],
        ],
    )
    records = AlarmCsvLoader(path).load()
    chains, memberships = build_chains(
        records, snapshot_id="s1", source_kind=SourceKind.REAL_EXPORT_REPLAY
    )
    by_id = {c.chain_id: c for c in chains}
    assert by_id["1"].member_count == 2
    assert by_id["1"].event_span_seconds == 10
    assert by_id["2"].member_count == 1
    assert len(memberships) == 3


def test_bom_header_is_handled(tmp_path):
    """The real export is UTF-8 with BOM; the first column must still be named."""
    path = _write_csv(
        tmp_path / "a.csv",
        [["1", "a1", "2026-01-01 00:00:00", "", "D1", "N1", "X"]],
        bom=True,
    )
    assert AlarmCsvLoader(path).columns()[0] == "chaining_id"


@pytest.mark.realdata
def test_real_export_dirty_data_counts(alarm_csv):
    """The real export's dirty rows are surfaced, not silently fixed."""
    profile = AlarmCsvLoader(alarm_csv).profile()
    assert profile.flag_counts[QualityFlag.TIMESTAMP_FUTURE_OUTLIER.value] == 2
    assert profile.flag_counts[QualityFlag.END_BEFORE_START.value] == 360
    assert profile.flag_counts[QualityFlag.MULTILINE_CONTENT.value] > 0
