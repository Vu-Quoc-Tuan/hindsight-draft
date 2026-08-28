"""Layer 1 — parser tests (docs 13).

The exact counts are frozen in SOURCE_MANIFEST.md. They are asserted literally:
if a parser change moves any of them, that is a regression, not a new baseline.
"""

from __future__ import annotations

import pytest

from nocpro_mock.loaders import AlarmCsvLoader, TopoIPLoader
from nocpro_mock.loaders.alarm_csv import parse_timestamp

pytestmark = pytest.mark.realdata


def test_alarm_csv_parses_frozen_record_count(alarm_csv):
    profile = AlarmCsvLoader(alarm_csv).profile()
    assert profile.record_count == 8714
    assert profile.column_count == 96


def test_alarm_csv_physical_lines_exceed_record_count(alarm_csv):
    """26,508 physical lines vs 8,714 records proves multiline fields are joined."""
    with alarm_csv.open("r", encoding="utf-8-sig", errors="replace") as fh:
        physical_lines = sum(1 for _ in fh)
    assert physical_lines == 26508
    assert AlarmCsvLoader(alarm_csv).profile().record_count == 8714


def test_alarm_csv_chain_distribution(alarm_csv):
    profile = AlarmCsvLoader(alarm_csv).profile()
    assert profile.unique_chaining_ids == 2824
    assert profile.singleton_chains == 2072
    assert round(profile.singleton_pct, 4) == 73.3711
    assert profile.max_chain_size == 1072
    assert profile.max_chain_id == "6907125"
    assert profile.unique_device_codes == 309
    assert round(profile.node_reference_fill_pct, 4) == 98.0606


def test_alarm_csv_preserves_multiline_content(alarm_csv):
    """A quoted newline must survive in the raw value, not be stripped."""
    loader = AlarmCsvLoader(alarm_csv)
    for record in loader.iter_records():
        if "MULTILINE_CONTENT" in record.quality_flags:
            assert any("\n" in value or "\r" in value for value in record.raw.values())
            return
    pytest.fail("expected at least one multiline record in the real export")


def test_topo_ip_parses_frozen_row_count(topo_ip_csv):
    profile = TopoIPLoader(topo_ip_csv).profile()
    assert profile.row_count == 201977
    assert profile.column_count == 16
    assert round(profile.source_class_pct("SITE_ROUTER"), 4) == 90.3860


def test_topo_ip_parses_update_time(topo_ip_csv):
    loader = TopoIPLoader(topo_ip_csv)
    for relation in loader.iter_relations():
        if relation.canonical_update_time is not None:
            assert relation.raw_update_time
            return
    pytest.fail("expected at least one parseable update_time_vipa")


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not-a-date", "0000-00-00 00:00:00"],
)
def test_unparseable_timestamps_return_none(raw):
    """Unparseable input yields None rather than a guessed value."""
    assert parse_timestamp(raw) is None
