"""Layer 6 — negative tests (docs 13).

Each test pins a rule that MUST fail. These encode the forbidden shortcuts from
docs README "Không được làm" and the ADR invariants.
"""

from __future__ import annotations

import pytest

from nocpro_mock.config import MockConfig, Policy, load_config
from nocpro_mock.contract import (
    Alarm,
    AlarmResourceMapping,
    Chain,
    ChainMembership,
    FailureDomain,
    FailureDomainType,
    GenerationMetadata,
    MappingMethod,
    MappingStatus,
    MockSnapshotPackage,
    ProvenanceClass,
    RelationType,
    Snapshot,
    SnapshotStatus,
    SourceKind,
    Topology,
    TopologyEdge,
    is_validation_eligible,
    validate_package,
)
from nocpro_mock.normalize import AliasEntry, ResourceMapper
from nocpro_mock.producer import DirectSnapshotProducer


def _snapshot(**kwargs):
    defaults = dict(
        snapshot_id="s1",
        snapshot_version="1",
        snapshot_time="2026-01-01T00:00:00",
        status=SnapshotStatus.COMPLETE,
        source="nocpro-mock",
        source_kind=SourceKind.REAL_EXPORT_REPLAY,
        produced_at="2026-01-01T00:00:01+00:00",
    )
    defaults.update(kwargs)
    return Snapshot(**defaults)


def test_prefix_mapping_is_impossible():
    """DEHL01 must not map to HLC9102* by prefix (ADR-MOCK-0005)."""
    mapper = ResourceMapper({"HLC9102DEA02", "HHT9603XYZ01"})
    for identifier in ("DEHL01", "DEHT01", "HLC9102DEA01", "HHT9603DEA01"):
        resource_id, status, method, confidence = mapper.map_identifier(identifier)
        assert resource_id is None
        assert status is MappingStatus.UNMAPPED
        assert method is MappingMethod.NONE
        assert confidence is None


def test_mapper_exposes_no_fuzzy_api():
    """There must be no prefix/fuzzy entry point to misuse."""
    forbidden = {"map_prefix", "fuzzy_match", "closest", "map_similar"}
    assert forbidden.isdisjoint(set(dir(ResourceMapper)))


def test_alias_must_point_at_a_known_resource():
    """A dangling alias resolves nothing rather than inventing a resource."""
    mapper = ResourceMapper(
        {"REAL-1"},
        aliases={"OLD-NAME": AliasEntry("OLD-NAME", "MISSING-1", verified_by="ops")},
    )
    resource_id, status, _, _ = mapper.map_identifier("OLD-NAME")
    assert resource_id is None
    assert status is MappingStatus.UNMAPPED


def test_verified_alias_resolves():
    mapper = ResourceMapper(
        {"REAL-1"},
        aliases={"OLD-NAME": AliasEntry("OLD-NAME", "REAL-1", verified_by="ops")},
    )
    resource_id, status, method, _ = mapper.map_identifier("OLD-NAME")
    assert resource_id == "REAL-1"
    assert status is MappingStatus.VERIFIED_ALIAS
    assert method is MappingMethod.VERIFIED_ALIAS_TABLE


def test_conflicting_identifiers_are_ambiguous_not_guessed():
    mapper = ResourceMapper({"DEV-A", "NODE-B"})
    mapping = mapper.map_alarm("a1", device_code="DEV-A", node_reference="NODE-B")
    assert mapping.mapping_status is MappingStatus.AMBIGUOUS
    assert mapping.resource_id is None


def test_directed_ip_adjacency_is_rejected():
    """Undirected adjacency must not be emitted as a directed claim."""
    package = MockSnapshotPackage(
        snapshot=_snapshot(),
        topology=Topology(
            edges=(
                TopologyEdge(
                    edge_id="e1",
                    source_resource_id="A",
                    target_resource_id="B",
                    relation_type=RelationType.IP_ADJACENCY,
                    directed=True,
                    source_id="topo_ip_csv",
                    source_kind=SourceKind.REAL_EXPORT_REPLAY,
                ),
            )
        ),
    )
    result = validate_package(package)
    assert not result.ok
    assert any("IP_ADJACENCY cannot be directed" in e for e in result.errors)


def test_synthetic_object_without_generation_metadata_is_rejected():
    """ADR-0026: synthetic data needs a deterministic generation trace."""
    package = MockSnapshotPackage(
        snapshot=_snapshot(),
        topology=Topology(
            failure_domains=(
                FailureDomain(
                    failure_domain_id="SRLG-SYN-001",
                    domain_type=FailureDomainType.SRLG,
                    members=("SYN-A", "SYN-B"),
                    source_id="synthetic",
                    source_kind=SourceKind.SYNTHETIC_TEST,
                ),
            )
        ),
    )
    result = validate_package(package)
    assert not result.ok
    assert any("generation metadata" in e for e in result.errors)


def test_synthetic_object_with_generation_metadata_passes():
    package = MockSnapshotPackage(
        snapshot=_snapshot(),
        topology=Topology(
            failure_domains=(
                FailureDomain(
                    failure_domain_id="SRLG-SYN-001",
                    domain_type=FailureDomainType.SRLG,
                    members=("SYN-A", "SYN-B"),
                    source_id="synthetic",
                    source_kind=SourceKind.SYNTHETIC_TEST,
                    generation=GenerationMetadata(
                        scenario_id="synthetic_failure_domain_v1",
                        seed=42,
                        generator_version="nocpro-mock-0.1.0",
                        generation_rule="explicit member set",
                    ),
                ),
            )
        ),
    )
    assert validate_package(package).ok


def test_synthetic_and_backfill_cannot_validate():
    """ADR-0010 stage-1 source-kind gate."""
    assert not is_validation_eligible(SourceKind.SYNTHETIC_TEST)
    assert not is_validation_eligible(SourceKind.BACKFILL)
    assert is_validation_eligible(SourceKind.REAL_LIVE)
    assert is_validation_eligible(SourceKind.REAL_EXPORT_REPLAY)


def test_unmapped_status_cannot_carry_a_resource_id():
    package = MockSnapshotPackage(
        snapshot=_snapshot(),
        topology=Topology(
            mappings=(
                AlarmResourceMapping(
                    alarm_id="a1",
                    resource_id="SOMETHING",
                    mapping_status=MappingStatus.UNMAPPED,
                    mapping_method=MappingMethod.NONE,
                ),
            )
        ),
    )
    result = validate_package(package)
    assert not result.ok
    assert any("still carries a resource_id" in e for e in result.errors)


def test_member_count_must_match_membership_rows():
    """A chain cannot claim more members than it lists."""
    package = MockSnapshotPackage(
        snapshot=_snapshot(),
        alarms=(
            Alarm(
                alarm_id="a1",
                snapshot_id="s1",
                source_kind=SourceKind.REAL_EXPORT_REPLAY,
                provenance_class=ProvenanceClass.SYSTEM_FACT,
                raw={},
            ),
        ),
        chains=(
            Chain(
                chain_id="c1",
                snapshot_id="s1",
                member_count=58,
                source_kind=SourceKind.REAL_EXPORT_REPLAY,
                provenance_class=ProvenanceClass.SYSTEM_FACT,
            ),
        ),
        memberships=(
            ChainMembership(
                chain_id="c1",
                alarm_id="a1",
                snapshot_id="s1",
                source_kind=SourceKind.REAL_EXPORT_REPLAY,
            ),
        ),
    )
    result = validate_package(package)
    assert not result.ok
    assert any("member_count=58" in e for e in result.errors)


def test_incompatible_schema_version_is_rejected():
    package = MockSnapshotPackage(snapshot=_snapshot(), schema_version="v2")
    result = validate_package(package)
    assert not result.ok
    assert any("incompatible schema_version" in e for e in result.errors)


def test_records_from_another_snapshot_are_rejected():
    """ADR-0005: records must be scoped to their snapshot."""
    package = MockSnapshotPackage(
        snapshot=_snapshot(snapshot_id="s1"),
        alarms=(
            Alarm(
                alarm_id="a1",
                snapshot_id="OTHER",
                source_kind=SourceKind.REAL_EXPORT_REPLAY,
                provenance_class=ProvenanceClass.SYSTEM_FACT,
                raw={},
            ),
        ),
    )
    result = validate_package(package)
    assert not result.ok
    assert any("does not match snapshot" in e for e in result.errors)


def test_producer_refuses_to_render_invalid_package():
    """Contract validation cannot be bypassed (ADR-0030)."""
    package = MockSnapshotPackage(snapshot=_snapshot(), schema_version="v9")
    with pytest.raises(Exception) as excinfo:
        DirectSnapshotProducer().render(package)
    assert "contract violation" in str(excinfo.value)


@pytest.mark.parametrize(
    "policy",
    [
        Policy(allow_fuzzy_topology_mapping=True),
        Policy(synthetic_can_validate=True),
        Policy(mutate_golden_fixture_in_place=True),
        Policy(missing_pair_metadata_defaults_to="NEUTRAL"),
    ],
)
def test_forbidden_policies_are_rejected(policy):
    """These invariants must not be configurable away."""
    with pytest.raises(ValueError):
        MockConfig(policy=policy).assert_policy_safe()


def test_example_config_is_policy_safe():
    from tests.conftest import CAPABILITY_CONFIG

    if not CAPABILITY_CONFIG.is_file():
        pytest.skip("example config not present")
    config = load_config(CAPABILITY_CONFIG)
    config.assert_policy_safe()
    assert config.topo_it_enabled is False
    assert config.topo_ip_capabilities.directed_dependency is False
    assert config.topo_ip_capabilities.active_path is False
