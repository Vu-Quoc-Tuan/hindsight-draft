"""Test exact mapping and display-only topology hierarchy helpers."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from nocpro_mock.normalize.resource_mapping import AliasEntry, ResourceMapper
from nocpro_mock.normalize.topology_hierarchy import (
    ip_display_level,
    it_display_level,
)
from nocpro_mock.contract import MappingStatus, MappingMethod


def test_ip_display_level_has_no_orientation_api() -> None:
    assert ip_display_level("CORE") == 0
    assert ip_display_level("IP_CORE") == 0
    assert ip_display_level("AGG_DISTRICT") == 1
    assert ip_display_level("SITE_ROUTER") == 2


def test_it_display_level_has_no_dependency_semantics() -> None:
    assert it_display_level("SERVICE") == 0
    assert it_display_level("MODULE") == 1
    assert it_display_level("INSTANCE") == 2
    assert it_display_level("DATABASE") == 3
    assert it_display_level("STORAGE") == 3


def test_resource_mapper_map_real_alarm() -> None:
    known_resources = {
        "QNM0002AGG01",
        "10.254.246.11",
        "it:service:VTN_CNTT_MSS_049",
    }
    mapper = ResourceMapper(known_resources=known_resources, topology_layer="IP")

    # IP match via device_code
    res1 = mapper.map_real_alarm("ALM_1", device_code="QNM0002AGG01")
    assert res1.mapping_status == MappingStatus.EXACT
    assert res1.resource_id == "QNM0002AGG01"

    # IT match via IP
    res2 = mapper.map_real_alarm("ALM_2", device_ip="10.254.246.11/24")
    assert res2.mapping_status == MappingStatus.EXACT
    assert res2.resource_id == "10.254.246.11"

    # IT match via component
    res3 = mapper.map_real_alarm("ALM_3", component="VTN_CNTT_MSS_049")
    assert res3.mapping_status == MappingStatus.EXACT
    assert res3.resource_id == "it:service:VTN_CNTT_MSS_049"

    # Unmapped
    res4 = mapper.map_real_alarm("ALM_4", device_code="UNKNOWN_DEV")
    assert res4.mapping_status == MappingStatus.UNMAPPED
    assert res4.resource_id is None


def test_build_it_resource_mapper_does_not_promote_structural_aliases() -> None:
    from nocpro_mock.normalize.resource_mapping import build_it_resource_mapper

    topo_it_dir = Path("datasets/raw/topo/topoIT")
    if not topo_it_dir.is_dir():
        return

    mapper = build_it_resource_mapper(topo_it_dir)
    assert mapper.aliases == {}

    # topoIT source-table joins remain structural navigation data.  They do not
    # establish a verified production alarm-resource mapping.
    res_ip = mapper.map_real_alarm("ALM_IP", device_ip="10.30.143.68/26")
    assert res_ip.mapping_status == MappingStatus.UNMAPPED
    assert res_ip.mapping_method == MappingMethod.NONE
    assert res_ip.resource_id is None

    res_svc = mapper.map_real_alarm("ALM_SVC", device_code="VTN_CNTT_VAS_094")
    assert res_svc.mapping_status == MappingStatus.UNMAPPED
    assert res_svc.resource_id is None


def test_build_ip_resource_mapper_attaches_content_source_version() -> None:
    from nocpro_mock.normalize.resource_mapping import build_ip_resource_mapper

    topo_ip = Path("datasets/raw/topo/topoIP.csv")
    if not topo_ip.is_file():
        return

    mapper = build_ip_resource_mapper(topo_ip)

    assert mapper.source_version is not None
    assert mapper.source_version.startswith("sha256:")


def test_conflicting_source_alias_is_ambiguous_not_first_row_wins() -> None:
    mapper = ResourceMapper(
        known_resources={"it:database:1", "it:database:2"},
        aliases={
            "UNIQUE": AliasEntry("UNIQUE", "it:database:1", verified_by="fixture"),
        },
        ambiguous_aliases={"SHARED"},
        topology_layer="IT",
    )

    result = mapper.map_real_alarm("ALM-CONFLICT", component="SHARED")

    assert result.mapping_status is MappingStatus.AMBIGUOUS
    assert result.resource_id is None


def _write_topo_it_sources(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    tables = {
        "service_module_server.csv": (
            [
                "service_id", "service_name", "service_code", "module_id",
                "module_name", "module_code", "instance_id", "instance_ip",
            ],
            [
                ["S1", "Service One", "svc-one", "M1", "Module One", "mod-one", "I1", "10.0.0.1"],
                ["S2", "Service Two", "SHARED", "M2", "Module Two", "mod-two", "I2", "10.0.0.2"],
                ["S3", "Service Three", "SHARED", "M3", "Module Three", "mod-three", "I3", "10.0.0.3"],
            ],
        ),
        "module_database.csv": (
            ["module_id", "database_id"],
            [["M1", "DB1"]],
        ),
        "database.csv": (
            ["database_id", "service_id", "instance_id", "database_name", "service_name", "instance_ip"],
            [["DB1", "S1", "I1", "db-one", "Service One", "10.0.0.1"]],
        ),
        "storage.csv": (
            ["storage_name", "instance_id", "instance_ip", "ip_address"],
            [["ST1", "I1", "10.0.0.1", "10.0.0.9"]],
        ),
    }
    for name, (header, rows) in tables.items():
        with (directory / name).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
    return directory


def test_it_navigation_mapper_uses_structured_unique_status_not_verified_alias(tmp_path):
    from nocpro_mock.normalize.resource_mapping import (
        build_it_navigation_mapper,
        build_it_resource_mapper,
    )

    topo_it_dir = _write_topo_it_sources(tmp_path / "topoIT")
    fail_closed_mapper = build_it_resource_mapper(topo_it_dir)
    navigation_mapper = build_it_navigation_mapper(topo_it_dir)

    assert fail_closed_mapper.aliases == {}
    assert fail_closed_mapper.map_real_alarm("a1", device_code="svc-one").mapping_status is MappingStatus.UNMAPPED

    unique = navigation_mapper.map_real_alarm("a1", device_code="svc-one")
    assert unique.resource_id == "it:service:S1"
    assert unique.mapping_status is MappingStatus.STRUCTURED_FIELD_UNIQUE
    assert unique.mapping_method is MappingMethod.STRUCTURED_FIELD_EXACT
    assert unique.mapping_confidence is None

    ambiguous = navigation_mapper.map_real_alarm("a2", device_code="SHARED")
    assert ambiguous.mapping_status is MappingStatus.AMBIGUOUS
    assert ambiguous.resource_id is None

    exact = navigation_mapper.map_real_alarm("a3", device_code="it:service:S1")
    assert exact.mapping_status is MappingStatus.EXACT
    assert exact.mapping_method is MappingMethod.EXACT_IDENTITY


def test_it_source_relation_projection_is_bounded_and_validated(tmp_path):
    from datetime import datetime

    from nocpro_mock.config import MockConfig
    from nocpro_mock.contract import QualityStatus, RelationType
    from nocpro_mock.producer import DirectSnapshotProducer
    from nocpro_mock.replay import build_real_replay_snapshot

    alarm_csv = tmp_path / "alarmIT.csv"
    with alarm_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["chaining_id", "cah.id", "cah.start_time", "end_time", "device_code", "node_reference", "alarm_name", "component"])
        writer.writerow(["C1", "a1", "2026-01-01 00:00:00", "", "svc-one", "", "Down", ""])
    topo_it_dir = _write_topo_it_sources(tmp_path / "topoIT")

    package = build_real_replay_snapshot(
        alarm_csv_path=alarm_csv,
        config=MockConfig(topo_it_enabled=True),
        snapshot_id="it-nav-test",
        snapshot_version="1",
        snapshot_time=datetime(2026, 1, 1),
        topo_it_dir=topo_it_dir,
        include_it_source_relations=True,
    )

    assert DirectSnapshotProducer().check(package).ok
    assert package.provenance_manifest.sources[0].source_id == "alarm_it_csv"
    assert package.provenance_manifest.sources[1].source_id == "topo_it_dir"
    assert package.topology.mappings[0].mapping_status is MappingStatus.STRUCTURED_FIELD_UNIQUE
    relation_types = {edge.relation_type for edge in package.topology.edges}
    assert RelationType.SERVICE_HAS_MODULE in relation_types
    assert RelationType.DATABASE_LINKS_SERVICE in relation_types
    assert RelationType.MODULE_LINKS_DATABASE in relation_types
    assert all(
        edge.relation_type is not RelationType.SERVICE_DEPENDS_ON
        for edge in package.topology.edges
    )
    assert all(edge.directed for edge in package.topology.edges)
    assert all(edge.quality_status is QualityStatus.UNKNOWN for edge in package.topology.edges)
    node_ids = {node.resource_id for node in package.topology.nodes}
    assert {"it:service:S1", "it:module:M1", "it:database:DB1"} <= node_ids
    assert "it:service:S2" not in node_ids


def test_replay_cli_forwards_alarm_selection_and_it_navigation_flag(monkeypatch):
    from nocpro_mock import cli
    from nocpro_mock.config import MockConfig

    captured = {}
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda _path: MockConfig(topo_it_enabled=True),
    )
    monkeypatch.setattr(
        cli,
        "build_real_replay_snapshot",
        lambda **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(cli, "_emit", lambda _package, _args: 0)

    result = cli.main(
        [
            "replay",
            "--alarm-csv",
            "alarmIT.csv",
            "--topo-it-dir",
            "topoIT",
            "--snapshot-id",
            "selected-it",
            "--alarm-id",
            "a1",
            "--alarm-id",
            "a2",
            "--include-it-source-relations",
        ]
    )

    assert result == 0
    assert captured["alarm_ids"] == {"a1", "a2"}
    assert captured["include_it_source_relations"] is True


def test_replay_cli_rejects_unavailable_it_projection_inputs(monkeypatch, capsys):
    from nocpro_mock import cli
    from nocpro_mock.config import MockConfig

    monkeypatch.setattr(cli, "load_config", lambda _path: MockConfig())
    monkeypatch.setattr(
        cli,
        "build_real_replay_snapshot",
        lambda **_kwargs: pytest.fail("builder must not run for an unavailable request"),
    )

    result = cli.main(["replay", "--include-it-source-relations"])

    assert result == 2
    assert "requires --topo-it-dir" in capsys.readouterr().err


def test_snapshot_builder_rejects_silently_disabled_it_projection(tmp_path):
    from nocpro_mock.config import MockConfig
    from nocpro_mock.replay.snapshot import build_real_replay_snapshot

    with pytest.raises(ValueError, match="requires topo_it_enabled=true"):
        build_real_replay_snapshot(
            alarm_csv_path=tmp_path / "not-read.csv",
            config=MockConfig(),
            snapshot_id="it-nav-disabled",
            topo_it_dir=tmp_path,
            include_it_source_relations=True,
        )
