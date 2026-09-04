"""Layer 5 — contract and determinism tests (docs 13).

Determinism matters because the same fixture must produce byte-equivalent output
across runs and, later, across transports (ADR-MOCK-0007).
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from nocpro_mock.contract import (
    ContractUnavailable,
    QualityStatus,
    SourceKind,
    package_to_json,
)
from nocpro_mock.normalize import freshness_quality, normalize_topo_ip
from nocpro_mock.producer import DirectSnapshotProducer
from nocpro_mock.replay import build_golden_snapshot, build_real_replay_snapshot

FIXED_TIME = datetime(2026, 1, 1, 12, 0, 0)


def test_contract_is_loaded_from_the_canonical_repository():
    """The contract must come from nocpro-chain-explain, not a local copy."""
    from nocpro_mock import contract as bridge

    assert "nocpro-chain-explain" in bridge.contract.__file__
    assert bridge.SCHEMA_VERSION == "v1"


def test_contract_unavailable_is_an_explicit_error():
    assert issubclass(ContractUnavailable, RuntimeError)


def test_serialization_drops_none_and_is_stable():
    package = build_golden_snapshot(config=_config(), snapshot_time=FIXED_TIME)
    first = package_to_json(package)
    second = package_to_json(package)
    assert first == second
    payload = json.loads(first)
    # Absent optional fields are omitted rather than serialized as null.
    assert "topology_version" not in payload["snapshot"]


def _config():
    from nocpro_mock.config import load_config

    return load_config()


def test_golden_snapshot_is_deterministic_for_fixed_time(golden_dir):
    from nocpro_mock.fixtures import load_golden_fixture

    fixture = load_golden_fixture(golden_dir)
    producer = DirectSnapshotProducer()
    a = producer.render(
        build_golden_snapshot(
            config=_config(), fixture=fixture, snapshot_time=FIXED_TIME
        )
    )
    b = producer.render(
        build_golden_snapshot(
            config=_config(), fixture=fixture, snapshot_time=FIXED_TIME
        )
    )
    # produced_at is wall-clock, so compare everything else.
    payload_a = json.loads(a)
    payload_b = json.loads(b)
    payload_a["snapshot"].pop("produced_at")
    payload_b["snapshot"].pop("produced_at")
    assert payload_a == payload_b


def test_freshness_without_a_threshold_is_unknown():
    """docs 06: the mock does not invent a PASS threshold."""
    assert freshness_quality(10, None) is QualityStatus.UNKNOWN
    assert freshness_quality(None, 3600) is QualityStatus.UNKNOWN
    assert freshness_quality(10, 3600) is QualityStatus.PASS
    assert freshness_quality(7200, 3600) is QualityStatus.FAIL


def test_topo_ip_edges_are_undirected_adjacency():
    from nocpro_mock.loaders.topology_ip_csv import TopoIPRelation
    from nocpro_mock.contract import RelationType

    relations = [
        TopoIPRelation(
            relation_id="1",
            device_code="A",
            device_code_relation="B",
            raw={"update_time_vipa": "2026-01-01 11:00:00"},
            canonical_update_time=datetime(2026, 1, 1, 11, 0, 0),
        )
    ]
    nodes, edges = normalize_topo_ip(
        relations, source_id="topo_ip_csv", reference_time=FIXED_TIME
    )
    assert len(edges) == 1
    assert edges[0].relation_type is RelationType.IP_ADJACENCY
    assert edges[0].directed is False
    assert edges[0].freshness_age_seconds == 3600
    # Freshness is measured but quality stays UNKNOWN without a configured threshold.
    assert edges[0].quality_status is QualityStatus.UNKNOWN
    assert {n.resource_id for n in nodes} == {"A", "B"}


def test_topo_ip_chaining_usage_is_unknown():
    """ADR-0010: usage cannot be claimed without the executed config."""
    from nocpro_mock.loaders.topology_ip_csv import TopoIPRelation

    relations = [
        TopoIPRelation(
            relation_id="1", device_code="A", device_code_relation="B", raw={}
        )
    ]
    _, edges = normalize_topo_ip(
        relations, source_id="topo_ip_csv", reference_time=FIXED_TIME
    )
    assert edges[0].chaining_usage.usage == "UNKNOWN"


def test_self_adjacency_is_dropped():
    from nocpro_mock.loaders.topology_ip_csv import TopoIPRelation

    relations = [
        TopoIPRelation(
            relation_id="1", device_code="A", device_code_relation="A", raw={}
        )
    ]
    nodes, edges = normalize_topo_ip(
        relations, source_id="topo_ip_csv", reference_time=FIXED_TIME
    )
    assert edges == ()
    assert {n.resource_id for n in nodes} == {"A"}


@pytest.mark.realdata
def test_real_replay_subset_passes_contract(alarm_csv, config):
    package = build_real_replay_snapshot(
        alarm_csv_path=alarm_csv,
        config=config,
        snapshot_id="snap_subset",
        snapshot_time=FIXED_TIME,
        chain_ids={"2224334"},
        limit=200,
    )
    assert DirectSnapshotProducer().check(package).ok
    assert package.snapshot.source_kind is SourceKind.REAL_EXPORT_REPLAY


@pytest.mark.realdata
def test_largest_real_chain_replays_completely(alarm_csv, config):
    """The 1,072-member chain must round-trip without truncation."""
    package = build_real_replay_snapshot(
        alarm_csv_path=alarm_csv,
        config=config,
        snapshot_id="snap_big",
        snapshot_time=FIXED_TIME,
        chain_ids={"6907125"},
    )
    assert len(package.alarms) == 1072
    assert package.chains[0].member_count == 1072
    assert len(package.memberships) == 1072
    assert DirectSnapshotProducer().check(package).ok


@pytest.mark.realdata
def test_real_topology_replay_carries_a_content_source_version(alarm_csv, topo_ip_csv, config):
    """Real topoIP edges need immutable provenance before Explain can use them."""
    ip_alarm_csv = topo_ip_csv.parents[1] / "alarm" / "alarmIP.csv"
    if not ip_alarm_csv.is_file():
        pytest.skip(f"real IP alarm export not present: {ip_alarm_csv}")
    package = build_real_replay_snapshot(
        alarm_csv_path=ip_alarm_csv,
        topo_ip_path=topo_ip_csv,
        config=config,
        snapshot_id="snap_topology_version",
        snapshot_time=FIXED_TIME,
        chain_ids={"6912465"},
    )

    assert package.topology.edges
    versions = {edge.source_version for edge in package.topology.edges}
    assert len(versions) == 1
    assert next(iter(versions)).startswith("sha256:")
    assert {mapping.source_version for mapping in package.topology.mappings} == versions
