"""Unit and contract tests for Topology-aware Alarm Entity Resolution."""

import pytest
from contracts.v1.enums import MappingMethod, MappingStatus
from contracts.v1.models import AlarmEntityResolution
from libs.contracts.loader import IngestedPackage, IngestedSnapshot
from nocpro_api.entity_resolver import (
    AlarmEntityResolver,
    ModuleCandidate,
    extract_base_module_token,
    normalize_token,
)
from channels.dependency import ResourceResolver


def test_token_normalization_and_extraction() -> None:
    assert normalize_token("neutron_openvswitch_agent") == "neutron-openvswitch-agent"
    assert normalize_token("Nova_Compute") == "nova-compute"
    assert extract_base_module_token("nova-compute_10.210.48.81") == "nova-compute"
    assert extract_base_module_token("kolla-toolbox_10.210.48.81") == "kolla-toolbox"
    assert extract_base_module_token("fluentd_10.210.48.81") == "fluentd"


def test_observed_host_resolution() -> None:
    resolver = AlarmEntityResolver(
        profile_id="IT_SERVICES",
        topology_version="v1",
        host_canonical_id_map={"10.210.48.81": "it:instance:724822"},
    )
    observed_id, resolutions = resolver.resolve_alarm(
        "ALM_1",
        device_code="10.210.48.81",
        raw_fields={"device_ip": "10.210.48.81/22"},
    )
    assert observed_id == "it:instance:724822"
    assert len(resolutions) == 1
    host_res = resolutions[0]
    assert host_res.entity_role == "OBSERVED_HOST"
    assert host_res.status == MappingStatus.EXACT
    assert host_res.method == MappingMethod.EXACT_IDENTITY
    assert host_res.resource_id == "it:instance:724822"
    assert host_res.confidence == 1.0


def test_structured_component_resolution() -> None:
    candidates = [
        ModuleCandidate(
            resource_id="it:module:93645",
            display_name="neutron-openvswitch-agent_10.210.48.81",
            base_token="neutron-openvswitch-agent",
        )
    ]
    resolver = AlarmEntityResolver(
        profile_id="IT_SERVICES",
        topology_version="v1",
        host_modules_map={"10.210.48.81": candidates},
        host_canonical_id_map={"10.210.48.81": "it:instance:724822"},
    )
    observed_id, resolutions = resolver.resolve_alarm(
        "ALM_2",
        device_code="10.210.48.81",
        raw_fields={"component": "neutron-openvswitch-agent"},
    )
    assert observed_id == "it:instance:724822"
    assert len(resolutions) == 2
    comp_res = [r for r in resolutions if r.entity_role == "AFFECTED_COMPONENT_CANDIDATE"][0]
    assert comp_res.status == MappingStatus.STRUCTURED_FIELD_UNIQUE
    assert comp_res.method == MappingMethod.STRUCTURED_FIELD_EXACT
    assert comp_res.resource_id == "it:module:93645"
    assert comp_res.confidence == 0.85


def test_raw_text_token_match_candidate() -> None:
    candidates = [
        ModuleCandidate(
            resource_id="it:module:91029",
            display_name="nova-compute_10.210.48.81",
            base_token="nova-compute",
        ),
        ModuleCandidate(
            resource_id="it:module:93079",
            display_name="fluentd_10.210.48.81",
            base_token="fluentd",
        ),
    ]
    resolver = AlarmEntityResolver(
        profile_id="IT_SERVICES",
        topology_version="v1",
        host_modules_map={"10.210.48.81": candidates},
        host_canonical_id_map={"10.210.48.81": "it:instance:724822"},
    )
    observed_id, resolutions = resolver.resolve_alarm(
        "ALM_3",
        alarm_name="Container is not running",
        raw_content="Container nova_compute on instance 10.210.48.81:9800 is exited",
        device_code="10.210.48.81",
    )
    assert observed_id == "it:instance:724822"
    comp_res = [r for r in resolutions if r.entity_role == "AFFECTED_COMPONENT_CANDIDATE"][0]
    assert comp_res.status == MappingStatus.TEXT_MATCH_CANDIDATE
    assert comp_res.method == MappingMethod.RAW_TEXT_EXACT_TOKEN
    assert comp_res.resource_id == "it:module:91029"
    assert comp_res.matched_text == "nova-compute"
    assert comp_res.confidence == 0.72


def test_ambiguous_candidate_resolution() -> None:
    candidates = [
        ModuleCandidate(
            resource_id="it:module:91029",
            display_name="nova-compute_10.210.48.81",
            base_token="nova-compute",
        ),
        ModuleCandidate(
            resource_id="it:module:90904",
            display_name="nova-ssh_10.210.48.81",
            base_token="nova-ssh",
        ),
    ]
    resolver = AlarmEntityResolver(
        profile_id="IT_SERVICES",
        topology_version="v1",
        host_modules_map={"10.210.48.81": candidates},
        host_canonical_id_map={"10.210.48.81": "it:instance:724822"},
    )
    # Content mentions both nova-compute and nova-ssh
    observed_id, resolutions = resolver.resolve_alarm(
        "ALM_4",
        alarm_name="Container error",
        raw_content="nova-compute failed to connect with nova-ssh",
        device_code="10.210.48.81",
    )
    comp_res = [r for r in resolutions if r.entity_role == "AFFECTED_COMPONENT_CANDIDATE"][0]
    assert comp_res.status == MappingStatus.AMBIGUOUS
    assert comp_res.resource_id is None
    assert comp_res.candidate_resource_ids == ("it:module:91029", "it:module:90904")
    assert comp_res.confidence == 0.40


def test_unmapped_no_false_positive() -> None:
    candidates = [
        ModuleCandidate(
            resource_id="it:module:91029",
            display_name="nova-compute_10.210.48.81",
            base_token="nova-compute",
        ),
    ]
    resolver = AlarmEntityResolver(
        profile_id="IT_SERVICES",
        topology_version="v1",
        host_modules_map={"10.210.48.81": candidates},
        host_canonical_id_map={"10.210.48.81": "it:instance:724822"},
    )
    observed_id, resolutions = resolver.resolve_alarm(
        "ALM_5",
        alarm_name="Network device speed decreased",
        raw_content="Device bond0 has been decreased to 10GB",
        device_code="10.210.48.81",
    )
    # Only observed host is emitted; bond0 is not falsely attached to nova-compute
    assert observed_id == "it:instance:724822"
    comp_res = [r for r in resolutions if r.entity_role == "AFFECTED_COMPONENT_CANDIDATE"]
    assert len(comp_res) == 0


def test_causal_channel_fail_closed_guarantee() -> None:
    """Ensure dependency channel ResourceResolver only resolves EXACT and VERIFIED_ALIAS."""
    mappings = [
        {"alarm_id": "A1", "resource_id": "it:instance:1", "mapping_status": "EXACT"},
        {"alarm_id": "A2", "resource_id": "it:module:2", "mapping_status": "VERIFIED_ALIAS"},
        {"alarm_id": "A3", "resource_id": "it:module:3", "mapping_status": "TEXT_MATCH_CANDIDATE"},
        {"alarm_id": "A4", "resource_id": None, "mapping_status": "AMBIGUOUS"},
        {"alarm_id": "A5", "resource_id": None, "mapping_status": "UNMAPPED"},
    ]
    pkg = IngestedPackage(
        snapshot=IngestedSnapshot(
            snapshot_id="s1",
            snapshot_version="v1",
            snapshot_time="2026-07-28T09:30:00Z",
            status="COMPLETE",
            source="test",
            source_kind="TEST",
            produced_at="2026-07-28T09:30:00Z",
            config_version="v1",
        ),
        topology={"mappings": mappings},
    )
    resolver = ResourceResolver.from_package(pkg)
    assert resolver.resolved == {
        "A1": "it:instance:1",
        "A2": "it:module:2",
    }
    # A3 (TEXT_MATCH_CANDIDATE) MUST NOT be present in causal graph resolution!
    assert "A3" not in resolver.resolved
    assert "A4" not in resolver.resolved
    assert "A5" not in resolver.resolved


def test_unknown_host_is_unmapped_no_synthetic_exact() -> None:
    """An IP not present in topology mapping MUST NOT be synthetically resolved as EXACT."""
    resolver = AlarmEntityResolver(
        profile_id="IT_SERVICES",
        topology_version="v1",
        host_canonical_id_map={"10.210.48.81": "it:instance:724822"},
    )
    observed_id, resolutions = resolver.resolve_alarm(
        "ALM_UNKNOWN",
        device_code="10.99.99.99",
        raw_fields={"device_ip": "10.99.99.99"},
    )
    assert observed_id is None
    assert len(resolutions) == 1
    host_res = resolutions[0]
    assert host_res.status == MappingStatus.UNMAPPED
    assert host_res.resource_id is None
    assert host_res.confidence == 0.0
    assert host_res.method == MappingMethod.NONE


def test_structured_port_field_and_substring_fallback() -> None:
    candidates = [
        ModuleCandidate(
            resource_id="it:module:888",
            display_name="eth0_link_service_10.210.48.81",
            base_token="eth0-link-service",
        )
    ]
    resolver = AlarmEntityResolver(
        profile_id="IT_SERVICES",
        topology_version="v1",
        host_modules_map={"10.210.48.81": candidates},
        host_canonical_id_map={"10.210.48.81": "it:instance:724822"},
    )
    # Port field used, matching display_name substring (not exact base_token)
    observed_id, resolutions = resolver.resolve_alarm(
        "ALM_PORT",
        device_code="10.210.48.81",
        raw_fields={"port": "eth0_link"},
    )
    assert observed_id == "it:instance:724822"
    comp_res = [r for r in resolutions if r.entity_role == "AFFECTED_COMPONENT_CANDIDATE"][0]
    assert comp_res.source_field == "port"
    assert comp_res.status == MappingStatus.TEXT_MATCH_CANDIDATE
    assert comp_res.confidence == 0.60

