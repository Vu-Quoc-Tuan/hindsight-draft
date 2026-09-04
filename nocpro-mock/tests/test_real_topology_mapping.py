"""Test exact mapping and display-only topology hierarchy helpers."""

from __future__ import annotations

from pathlib import Path
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
