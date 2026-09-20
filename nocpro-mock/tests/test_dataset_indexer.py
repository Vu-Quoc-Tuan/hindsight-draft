"""Unit tests for SQLite DatasetIndexer in nocpro_mock."""

from __future__ import annotations

import tempfile
import csv
from pathlib import Path
import pytest

from nocpro_mock.storage.dataset_indexer import (
    DatasetIndexer,
    encode_cursor,
    decode_cursor,
)
from nocpro_mock.storage.active_alarm_fields import (
    ACTIVE_ALARM_FIELDS,
    project_active_alarm,
)


def test_active_alarm_registry_matches_approved_contract():
    keys = [field.key for field in ACTIVE_ALARM_FIELDS]
    assert keys == [
        "logical_row", "alarm_id", "chaining_id", "chaining_name",
        "raw_start_time", "canonical_start_time", "raw_end_time",
        "canonical_end_time", "create_time", "alarm_status", "alarm_name",
        "content", "severity_name", "fault_id", "alarm_type_name", "group_name",
        "network_class_name", "monitor_type_name", "device_code", "device_name",
        "node_reference", "component", "location_code", "remote_node",
        "device_type_name", "mapping_status", "resource_id", "quality_flags",
    ]
    assert not ({"addition_info", "cah_reason", "parent_id", "device_ip"} & set(keys))


def test_active_projection_uses_component_precedence_and_unknown_status():
    row = project_active_alarm(
        logical_row=7,
        alarm_id="A-7",
        chaining_id="C-1",
        canonical_start_time=None,
        canonical_end_time=None,
        severity_name="MAJOR",
        mapping_status="UNAVAILABLE",
        resource_id=None,
        raw={"component": "card-1", "port": "port-2"},
    )
    assert row["component"] == "card-1"
    assert row["alarm_status"] == "UNKNOWN"


@pytest.fixture
def temp_indexer():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield DatasetIndexer(state_dir=Path(tmp_dir))


def test_cursor_encoding_and_validation():
    token = encode_cursor("v1_abc", "hash_123", 0, "2026-01-02T03:04:05", 50)
    assert isinstance(token, str)

    position = decode_cursor(token, "v1_abc", "hash_123")
    assert position == {
        "time_missing": 0,
        "canonical_start_time": "2026-01-02T03:04:05",
        "logical_row": 50,
    }

    # Tampered version
    with pytest.raises(ValueError, match="dataset_version mismatch"):
        decode_cursor(token, "v2_xyz", "hash_123")

    # Changed filter hash
    with pytest.raises(ValueError, match="filter_hash mismatch"):
        decode_cursor(token, "v1_abc", "hash_999")
    with pytest.raises(ValueError, match="Invalid cursor"):
        decode_cursor("not-base64!", "v1_abc", "hash_123")


def _write_alarm_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "cah.id", "chaining_id", "chaining_name", "cah.start_time", "end_time",
        "cah.create_time", "alarm_status", "alarm_name", "severity_name",
        "fault_id", "alarm_type_name", "group_name", "network_class_name",
        "monitor_type_name", "device_code", "device_name", "node_reference",
        "component", "port", "location_code", "remote_node", "device_type_name",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_dataset_field_profile_and_chronological_cursor(tmp_path: Path):
    alarm_csv = tmp_path / "small.csv"
    _write_alarm_csv(alarm_csv, [
        {"cah.id": "A-3", "chaining_id": "C", "cah.start_time": "", "alarm_name": "third", "severity_name": "MINOR", "device_code": "D3"},
        {"cah.id": "A-2", "chaining_id": "C", "cah.start_time": "2026-01-02 00:00:00", "alarm_name": "second-a", "severity_name": "MAJOR", "device_code": "D2", "port": "P2"},
        {"cah.id": "A-1", "chaining_id": "C", "cah.start_time": "2026-01-01 00:00:00", "alarm_name": "first", "severity_name": "CRITICAL", "device_code": "D1"},
        {"cah.id": "A-2B", "chaining_id": "C", "cah.start_time": "2026-01-02 00:00:00", "alarm_name": "second-b", "severity_name": "INFO", "device_code": "D2"},
    ])
    indexer = DatasetIndexer(state_dir=tmp_path / "state")
    version, _ = indexer.build_index("ALARM_ONLY", alarm_csv)

    columns = indexer.get_active_columns("ALARM_ONLY", version)
    by_key = {column["key"]: column for column in columns}
    assert "logical_row" in by_key
    assert "canonical_start_time" in by_key
    assert "component" in by_key
    assert by_key["component"]["nonempty_count"] == 1
    assert by_key["component"]["coverage_ratio"] == pytest.approx(0.25)
    assert "remote_node" not in by_key

    page1 = indexer.query_alarms("ALARM_ONLY", version, limit=2)
    page2 = indexer.query_alarms(
        "ALARM_ONLY", version, cursor=page1["next_cursor"], limit=2
    )
    ordered = page1["items"] + page2["items"]
    assert [item["alarm_id"] for item in ordered] == ["A-1", "A-2", "A-2B", "A-3"]
    assert ordered[-1]["canonical_start_time"] is None
    assert ordered[-1]["alarm_status"] == "UNKNOWN"
    assert len({item["row_id"] for item in ordered}) == 4


def test_dataset_indexer_atomic_lifecycle_and_pagination(temp_indexer: DatasetIndexer):
    alarm_csv = Path("datasets/raw/alarm/alarm_data.csv")
    if not alarm_csv.is_file():
        pytest.skip(f"raw alarm export missing: {alarm_csv}")

    # Build index
    version, db_path = temp_indexer.build_index("ALARM_ONLY", alarm_csv)
    assert db_path.is_file()
    assert not db_path.with_suffix(".db.tmp").exists()

    # Verify is_indexed returns True with matching version
    indexed, cached_ver = temp_indexer.is_indexed("ALARM_ONLY", alarm_csv)
    assert indexed is True
    assert cached_ver == version

    # Facets check
    facets = temp_indexer.query_facets("ALARM_ONLY", version)
    assert facets["record_count"] == 8714
    assert facets["chain_count"] == 2824
    assert "severities" in facets
    assert "mapping_statuses" in facets
    assert facets["mapping_statuses"].get("UNAVAILABLE", 0) == 8714  # ALARM_ONLY has no mapping

    # Pagination: first page (limit=100)
    page1 = temp_indexer.query_alarms("ALARM_ONLY", version, limit=100)
    assert len(page1["items"]) == 100
    assert page1["has_more"] is True
    assert page1["total_filtered"] == 8714
    assert page1["next_cursor"] is not None

    # Pagination: second page using cursor
    page2 = temp_indexer.query_alarms("ALARM_ONLY", version, cursor=page1["next_cursor"], limit=100)
    assert len(page2["items"]) == 100
    # No duplicate row IDs between page 1 and page 2
    p1_ids = {item["row_id"] for item in page1["items"]}
    p2_ids = {item["row_id"] for item in page2["items"]}
    assert len(p1_ids.intersection(p2_ids)) == 0

    # Detail check
    first_row = page1["items"][0]
    detail = temp_indexer.get_alarm_detail("ALARM_ONLY", version, first_row["row_id"])
    assert detail["canonical"]["alarm_id"] == first_row["alarm_id"]
    assert "raw" in detail
    assert isinstance(detail["raw"], dict)
    assert len(detail["raw"]) > 10  # 96 columns present

    # Filtering by severity
    if facets["severities"]:
        top_sev = next(iter(facets["severities"].keys()))
        filtered = temp_indexer.query_alarms("ALARM_ONLY", version, severity=top_sev, limit=50)
        assert len(filtered["items"]) <= 50
        for item in filtered["items"]:
            assert item["severity"] == top_sev


def test_row_id_dataset_version_mismatch(temp_indexer: DatasetIndexer):
    alarm_csv = Path("datasets/raw/alarm/alarm_data.csv")
    if not alarm_csv.is_file():
        pytest.skip("alarm_data.csv missing")

    version, _ = temp_indexer.build_index("ALARM_ONLY", alarm_csv)
    # Valid compound ID
    detail = temp_indexer.get_alarm_detail("ALARM_ONLY", version, f"{version}:1")
    assert detail["canonical"]["logical_row"] == 1

    # Mismatched version in compound ID
    with pytest.raises(ValueError, match="Dataset version mismatch"):
        temp_indexer.get_alarm_detail("ALARM_ONLY", version, "other_version_12345:1")


def test_cache_invalidation_on_topology_change(temp_indexer: DatasetIndexer):
    alarm_csv = Path("datasets/raw/alarm/alarm_data.csv")
    if not alarm_csv.is_file():
        pytest.skip("alarm_data.csv missing")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_topo = Path(tmp_dir) / "topoIP.csv"
        tmp_topo.write_text("DEVICE_CODE,DEVICE_CODE_RELATION\nR-01,R-02\n", encoding="utf-8")

        # Index with initial topo
        v1, _ = temp_indexer.ensure_indexed(alarm_csv, profile_id="IP_NETWORK", topo_path=tmp_topo)
        indexed1, cached_v1 = temp_indexer.is_indexed("IP_NETWORK", alarm_csv, topo_path=tmp_topo)
        assert indexed1 is True
        assert cached_v1 == v1

        # Now change the topology file content
        tmp_topo.write_text("DEVICE_CODE,DEVICE_CODE_RELATION\nR-01,R-03\nR-02,R-04\n", encoding="utf-8")

        # is_indexed MUST return False because expected topo signature changed
        indexed2, cached_v2 = temp_indexer.is_indexed("IP_NETWORK", alarm_csv, topo_path=tmp_topo)
        assert indexed2 is False
        assert cached_v2 == ""

        # Re-indexing produces a new distinct version
        v2, _ = temp_indexer.ensure_indexed(alarm_csv, profile_id="IP_NETWORK", topo_path=tmp_topo)
        assert v2 != v1


def test_count_alarms(temp_indexer: DatasetIndexer):
    alarm_csv = Path("datasets/raw/alarm/alarm_data.csv")
    if not alarm_csv.is_file():
        pytest.skip("alarm_data.csv missing")

    version, _ = temp_indexer.ensure_indexed(alarm_csv, profile_id="ALARM_ONLY")
    count = temp_indexer.count_alarms("ALARM_ONLY", version)
    assert count == 8714


def test_filter_by_chaining_and_clean_flag(temp_indexer: DatasetIndexer):
    alarm_csv = Path("datasets/raw/alarm/alarm_data.csv")
    if not alarm_csv.is_file():
        pytest.skip("alarm_data.csv missing")

    version, _ = temp_indexer.ensure_indexed(alarm_csv, profile_id="ALARM_ONLY")

    # Get an existing chaining_id
    page_any = temp_indexer.query_alarms("ALARM_ONLY", version, limit=1)
    assert len(page_any["items"]) > 0
    target_chain = page_any["items"][0]["chaining_id"]
    assert target_chain is not None

    # Filter by chaining_id
    page_chain = temp_indexer.query_alarms("ALARM_ONLY", version, chaining_id=target_chain, limit=10)
    assert len(page_chain["items"]) > 0
    for item in page_chain["items"]:
        assert item["chaining_id"] == target_chain

    # Filter by CLEAN quality flag
    page_clean = temp_indexer.query_alarms("ALARM_ONLY", version, quality_flag="CLEAN", limit=50)
    assert len(page_clean["items"]) > 0
    # Verify none of the clean alarms have quality flags recorded
    for item in page_clean["items"]:
        detail = temp_indexer.get_alarm_detail("ALARM_ONLY", version, item["row_id"])
        assert detail["canonical"]["quality_flags"] == []


def test_active_fields_and_legacy_filters(temp_indexer: DatasetIndexer):
    alarm_csv = Path("datasets/raw/alarm/alarm_data.csv")
    if not alarm_csv.is_file():
        pytest.skip("alarm_data.csv missing")

    version, _ = temp_indexer.ensure_indexed(alarm_csv, profile_id="ALARM_ONLY")
    page = temp_indexer.query_alarms("ALARM_ONLY", version, limit=5)
    assert len(page["items"]) > 0
    first = page["items"][0]

    # Verify active fields exist while raw-only fields stay out of the list response.
    for key in ("device_type_name", "location_code", "alarm_status", "quality_flags", "content"):
        assert key in first
    for key in ("location_name", "trouble_code", "kedb_code", "parent_id"):
        assert key not in first

    # Verify detail canonical dict contains rich fields
    detail = temp_indexer.get_alarm_detail("ALARM_ONLY", version, first["row_id"])
    canonical = detail["canonical"]
    assert "content" in canonical
    assert "device_type_name" in canonical
    assert "location_name" in canonical

    # Test filtering by alarm_status
    page_active = temp_indexer.query_alarms("ALARM_ONLY", version, alarm_status="1", limit=10)
    for item in page_active["items"]:
        assert item["alarm_status"] == "1"
