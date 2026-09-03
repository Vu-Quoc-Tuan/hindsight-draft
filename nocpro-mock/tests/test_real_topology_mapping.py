"""Test exact mapping and display-only topology hierarchy helpers."""

from __future__ import annotations

from pathlib import Path
from nocpro_mock.normalize.resource_mapping import ResourceMapper
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
