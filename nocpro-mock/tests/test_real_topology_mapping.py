"""Test real topology mapping and hierarchy orientation."""

from __future__ import annotations

from pathlib import Path
from nocpro_mock.normalize.resource_mapping import ResourceMapper
from nocpro_mock.normalize.topology_hierarchy import (
    ip_device_rank,
    it_resource_rank,
    orient_ip_edge,
)
from nocpro_mock.contract import MappingStatus, MappingMethod


def test_ip_device_rank_and_edge_orientation() -> None:
    assert ip_device_rank("CORE") == 0
    assert ip_device_rank("IP_CORE") == 0
    assert ip_device_rank("AGG_DISTRICT") == 1
    assert ip_device_rank("SITE_ROUTER") == 2

    # Core -> Aggregation
    upstream, downstream, is_hier = orient_ip_edge(
        "CORE_R1", "IP_CORE",
        "AGG_R1", "AGG_DISTRICT"
    )
    assert upstream == "CORE_R1"
    assert downstream == "AGG_R1"
    assert is_hier is True

    # Reversed order: Aggregation -> Core
    upstream2, downstream2, is_hier2 = orient_ip_edge(
        "AGG_R1", "AGG_DISTRICT",
        "CORE_R1", "IP_CORE"
    )
    assert upstream2 == "CORE_R1"
    assert downstream2 == "AGG_R1"
    assert is_hier2 is True

    # Peer: Aggregation <-> Aggregation
    _, _, is_hier_peer = orient_ip_edge(
        "AGG_1", "AGG_DISTRICT",
        "AGG_2", "AGG_DISTRICT"
    )
    assert is_hier_peer is False


def test_it_resource_rank() -> None:
    assert it_resource_rank("SERVICE") == 0
    assert it_resource_rank("MODULE") == 1
    assert it_resource_rank("INSTANCE") == 2
    assert it_resource_rank("DATABASE") == 3
    assert it_resource_rank("STORAGE") == 3


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
