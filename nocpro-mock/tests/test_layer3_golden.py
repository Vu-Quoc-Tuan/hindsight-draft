"""Layer 3 — Golden fixture tests (docs 11/13, expected_assertions.yaml)."""

from __future__ import annotations

import pytest

from nocpro_mock.contract import CoverageScope, MappingStatus, SourceKind
from nocpro_mock.fixtures import load_golden_fixture
from nocpro_mock.producer import DirectSnapshotProducer
from nocpro_mock.replay import build_golden_snapshot


@pytest.fixture()
def golden(golden_dir):
    return load_golden_fixture(golden_dir)


def test_observed_facts(golden):
    assert golden.chain_id == "2214039"
    assert golden.member_count == 58
    assert golden.event_span_seconds == 22
    assert golden.merge_strategy == "OR"
    assert golden.source_kind is SourceKind.REAL_EXPORT_REPLAY


def test_rule_replay(golden):
    rules = {r.rule_name: r for r in golden.system_metadata.chain_rules}
    assert len(rules) == 3
    assert rules["CORE_CHAINING_REMOTE_NODE"].connector_count == 34
    assert rules["CORE_CHAINING_REMOTE_NODE"].extender_count == 6
    assert rules["CORE_CHAINING_REFERENCE_NODE"].connector_count == 58
    assert rules["CORE_CHAINING_DEFAULT"].connector_count == 18
    assert all(r.merge_strategy == "OR" for r in rules.values())


def test_characteristic_counts_and_coverage(golden):
    chars = golden.system_metadata.chain_characteristics
    time_char = next(c for c in chars if c.name == "TIME_LT_SECONDS")
    assert time_char.pair_count == 1653
    assert time_char.threshold_seconds == 600
    # C(58,2) = 1653 covers the full pair space.
    assert time_char.coverage_scope is CoverageScope.FULL_PAIR_SPACE

    refs = {c.value: c for c in chars if c.name == "NODE_REFERENCE_EQUAL"}
    assert refs["DEHL01"].pair_count == 435
    assert refs["DEHT01"].pair_count == 378
    # Aggregates without proven coverage stay UNKNOWN, not FULL_PAIR_SPACE.
    assert refs["DEHL01"].coverage_scope is CoverageScope.UNKNOWN
    assert refs["DEHT01"].coverage_scope is CoverageScope.UNKNOWN


def test_derived_sanity_checks_only(golden):
    """C(n,2) relations are consistency checks, not asserted system facts."""
    from math import comb

    chars = {(c.name, c.value): c.pair_count for c in golden.system_metadata.chain_characteristics}
    assert chars[("TIME_LT_SECONDS", None)] == comb(58, 2)
    assert chars[("NODE_REFERENCE_EQUAL", "DEHL01")] == comb(30, 2)
    assert chars[("NODE_REFERENCE_EQUAL", "DEHT01")] == comb(28, 2)
    assert 30 + 28 == 58


def test_no_pair_level_metadata_is_synthesized(golden):
    """Aggregate counts must never be expanded into concrete pair edges."""
    assert golden.system_metadata.pair_metadata == ()
    assert golden.system_metadata.attribute_configs == ()


def test_golden_snapshot_topology_stays_unmapped(config, golden, topo_ip_device_codes):
    """The real topoIP export has no exact match for the DEA resources."""
    package = build_golden_snapshot(
        config=config, fixture=golden, topo_ip_device_codes=topo_ip_device_codes
    )
    assert package.topology.mappings
    for mapping in package.topology.mappings:
        assert mapping.mapping_status is MappingStatus.UNMAPPED
        assert mapping.resource_id is None
    # No topology is attached to the Golden fixture.
    assert package.topology.edges == ()
    assert package.topology.nodes == ()


def test_golden_snapshot_passes_contract(config, golden):
    package = build_golden_snapshot(config=config, fixture=golden)
    assert DirectSnapshotProducer().check(package).ok


def test_golden_declares_unavailable_capabilities(config, golden):
    package = build_golden_snapshot(config=config, fixture=golden)
    unavailable = package.provenance_manifest.unavailable_capabilities
    assert "EXACT_PAIR_METADATA" in unavailable
    assert "ACTIVE_PATH" in unavailable


def test_loader_does_not_mutate_fixture_files(golden_dir, config):
    """ADR-MOCK-0004: replay must leave the Golden files byte-identical."""
    before = {p.name: p.read_bytes() for p in sorted(golden_dir.iterdir()) if p.is_file()}
    build_golden_snapshot(config=config, fixture=load_golden_fixture(golden_dir))
    after = {p.name: p.read_bytes() for p in sorted(golden_dir.iterdir()) if p.is_file()}
    assert before == after
