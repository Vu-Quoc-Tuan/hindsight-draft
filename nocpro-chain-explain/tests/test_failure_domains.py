"""H_domain stays a resource-backed hyperedge and can propose audit blocks."""

from __future__ import annotations

from audit import CandidateSource
from channels import failure_domains_for_chain, failure_domains_for_member
from descriptor import MiningConfig
from libs.contracts import load_package
from tier2 import AuditExecutionPolicy, analyze_structural_audit
from tier1b import analyze_chain
from groups import RoleThresholds


def _package():
    alarm_ids = [f"a{i}" for i in range(1, 11)]
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_version": "1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "test",
                "source_kind": "REAL_EXPORT_REPLAY",
                "produced_at": "2026-01-01T00:00:00",
            },
            "alarms": [
                {
                    "alarm_id": alarm_id,
                    "snapshot_id": "s1",
                    "raw": {"device_code": f"D{i}"},
                    "device_code": f"D{i}",
                    "alarm_name": "DOWN",
                }
                for i, alarm_id in enumerate(alarm_ids, 1)
            ],
            "chains": [{"chain_id": "C", "snapshot_id": "s1", "member_count": 10}],
            "memberships": [
                {"chain_id": "C", "alarm_id": alarm_id, "snapshot_id": "s1"}
                for alarm_id in alarm_ids
            ],
            "topology": {
                "mappings": [
                    {
                        "alarm_id": alarm_id,
                        "resource_id": f"R{i}",
                        "mapping_status": "EXACT",
                    }
                    for i, alarm_id in enumerate(alarm_ids, 1)
                ],
                "failure_domains": [
                    {
                        "failure_domain_id": "SRLG-1",
                        "domain_type": "SRLG",
                        "members": ["R1", "R2", "R3", "R4", "R5"],
                        "source_id": "inventory",
                        "source_kind": "REAL_EXPORT_REPLAY",
                        "provenance_class": "EXTERNAL_OPERATIONAL",
                        "provenance_subtype": "TOPOLOGY_EXTERNAL",
                        "quality_status": "PASS",
                    },
                    {
                        "failure_domain_id": "POWER-OTHER",
                        "domain_type": "POWER",
                        "members": ["R99"],
                        "source_id": "inventory",
                        "source_kind": "REAL_EXPORT_REPLAY",
                    },
                ],
            },
        }
    )


def test_chain_and_member_why_return_hyperedge_membership_not_pairs():
    package = _package()
    domains = failure_domains_for_chain(package, "C")

    assert len(domains) == 1
    domain = domains[0]
    assert domain.failure_domain_id == "SRLG-1"
    assert domain.member_alarm_ids == frozenset({"a1", "a2", "a3", "a4", "a5"})
    assert domain.member_resource_ids == frozenset({"R1", "R2", "R3", "R4", "R5"})
    assert not hasattr(domain, "pair_scores")
    assert failure_domains_for_member(package, "C", "a2") == domains
    assert failure_domains_for_member(package, "C", "a9") == ()


def test_tier2_automatically_uses_package_failure_domain_as_candidate_only():
    analysis = analyze_structural_audit(
        _package(),
        "C",
        policy=AuditExecutionPolicy(exact_max_members=10),
        mining_config=MiningConfig(config_version="test"),
        epsilon=0.3,
    )

    domain_candidates = [
        scored.candidate
        for scored in analysis.structural_audit.scored_candidates
        if scored.candidate.source is CandidateSource.FAILURE_DOMAIN
    ]
    assert domain_candidates
    assert domain_candidates[0].members == frozenset(
        {"a1", "a2", "a3", "a4", "a5"}
    )
    # H_domain proposes a set; audit graph edges still come only from K_pair.
    assert analysis.graph is not None
    assert set(analysis.graph.members) == {f"a{i}" for i in range(1, 11)}


def test_tier1b_chain_and_member_results_expose_domain_hyperedges():
    analysis = analyze_chain(
        _package(),
        "C",
        thresholds=RoleThresholds(config_version="test"),
        mining_config=MiningConfig(config_version="test"),
        enable_contrastive=False,
    )

    assert [domain.failure_domain_id for domain in analysis.failure_domains] == [
        "SRLG-1"
    ]
    assert analysis.members["a2"].failure_domains == analysis.failure_domains
    assert analysis.members["a9"].failure_domains == ()


def test_structured_source_mapping_only_resolves_shared_storage_context():
    """Navigation-only alarm matches may expose storage context, not H_domain/Dep_hop."""
    from channels.dependency import ResourceResolver, build_topology_graph

    package = _package()
    package.topology["mappings"] = [
        {
            "alarm_id": "a1",
            "resource_id": "it:instance:I1",
            "mapping_status": "STRUCTURED_FIELD_UNIQUE",
            "mapping_method": "STRUCTURED_FIELD_EXACT",
            "topology_layer": "IT",
            "source_version": "sha256:topology-v1",
        },
        {
            "alarm_id": "a2",
            "resource_id": "it:instance:I2",
            "mapping_status": "STRUCTURED_FIELD_UNIQUE",
            "mapping_method": "STRUCTURED_FIELD_EXACT",
            "topology_layer": "IT",
            "source_version": "sha256:topology-v1",
        },
    ]
    package.topology["edges"] = [
        {
            "edge_id": "I1-storage",
            "source_resource_id": "it:instance:I1",
            "target_resource_id": "it:storage:S1",
            "relation_type": "INSTANCE_LINKS_STORAGE",
            "directed": True,
            "source_id": "storage.csv",
            "source_kind": "REAL_EXPORT_REPLAY",
            "source_version": "sha256:topology-v1",
            "provenance_class": "EXTERNAL_OPERATIONAL",
            "provenance_subtype": "TOPOLOGY_EXTERNAL",
            "quality_status": "UNKNOWN",
        },
        {
            "edge_id": "I2-storage",
            "source_resource_id": "it:instance:I2",
            "target_resource_id": "it:storage:S1",
            "relation_type": "INSTANCE_LINKS_STORAGE",
            "directed": True,
            "source_id": "storage.csv",
            "source_kind": "REAL_EXPORT_REPLAY",
            "source_version": "sha256:topology-v1",
            "provenance_class": "EXTERNAL_OPERATIONAL",
            "provenance_subtype": "TOPOLOGY_EXTERNAL",
            "quality_status": "UNKNOWN",
        },
    ]
    package.topology["failure_domains"] = [
        {
            "failure_domain_id": "UNVERIFIED-SRLG",
            "domain_type": "SRLG",
            "members": ["it:instance:I1", "it:instance:I2"],
            "source_id": "inventory.csv",
            "source_kind": "REAL_EXPORT_REPLAY",
            "provenance_class": "EXTERNAL_OPERATIONAL",
            "provenance_subtype": "TOPOLOGY_EXTERNAL",
            "quality_status": "UNKNOWN",
        }
    ]

    # The general topology/dependency resolver intentionally rejects this weaker
    # mapping status. Only the source-context adapter below may use it.
    assert ResourceResolver.from_package(package).resolved == {}
    assert build_topology_graph(
        package, relation_types=frozenset({"SERVICE_DEPENDS_ON"})
    ).adjacency == {}
    contexts = failure_domains_for_chain(package, "C")
    assert len(contexts) == 1
    assert contexts[0].domain_type == "SHARED_STORAGE_CONTEXT"
    assert contexts[0].member_alarm_ids == frozenset({"a1", "a2"})
    assert contexts[0].quality_status == "UNKNOWN"
    assert contexts[0].failure_domain_id != "UNVERIFIED-SRLG"


def test_shared_storage_context_with_two_alarms_on_one_instance_is_not_audit_candidate():
    """Duplicate alarms on one resource do not prove a shared-resource block."""
    from channels.dependency import ResourceResolver

    package = _package()
    package.topology["mappings"] = [
        {
            "alarm_id": "a1",
            "resource_id": "it:instance:I1",
            "mapping_status": "STRUCTURED_FIELD_UNIQUE",
            "mapping_method": "STRUCTURED_FIELD_EXACT",
            "topology_layer": "IT",
            "source_version": "sha256:topology-v1",
        },
        {
            "alarm_id": "a2",
            "resource_id": "it:instance:I1",
            "mapping_status": "STRUCTURED_FIELD_UNIQUE",
            "mapping_method": "STRUCTURED_FIELD_EXACT",
            "topology_layer": "IT",
            "source_version": "sha256:topology-v1",
        },
    ]
    package.topology["failure_domains"] = []
    package.topology["edges"] = [
        {
            "edge_id": f"{instance}-storage",
            "source_resource_id": f"it:instance:{instance}",
            "target_resource_id": "it:storage:S1",
            "relation_type": "INSTANCE_LINKS_STORAGE",
            "directed": True,
            "source_id": "storage.csv",
            "source_kind": "REAL_EXPORT_REPLAY",
            "source_version": "sha256:topology-v1",
            "provenance_class": "EXTERNAL_OPERATIONAL",
            "provenance_subtype": "TOPOLOGY_EXTERNAL",
            "quality_status": "UNKNOWN",
        }
        for instance in ("I1", "I2")
    ]

    assert ResourceResolver.from_package(package).resolved == {}
    contexts = failure_domains_for_chain(package, "C")
    assert len(contexts) == 1
    context = contexts[0]
    assert context.member_alarm_ids == frozenset({"a1", "a2"})
    assert context.member_resource_ids == frozenset({"it:instance:I1"})
    assert context.eligible_for_candidate is False


def test_failed_storage_source_edge_does_not_create_shared_context_candidate():
    """A FAIL edge remains visible as FAIL but cannot propose an Audit block."""
    package = _package()
    package.topology["mappings"] = [
        {
            "alarm_id": "a1",
            "resource_id": "it:instance:I1",
            "mapping_status": "STRUCTURED_FIELD_UNIQUE",
            "mapping_method": "STRUCTURED_FIELD_EXACT",
            "topology_layer": "IT",
            "source_version": "sha256:topology-v1",
        },
        {
            "alarm_id": "a2",
            "resource_id": "it:instance:I2",
            "mapping_status": "STRUCTURED_FIELD_UNIQUE",
            "mapping_method": "STRUCTURED_FIELD_EXACT",
            "topology_layer": "IT",
            "source_version": "sha256:topology-v1",
        },
    ]
    package.topology["failure_domains"] = []
    package.topology["edges"] = [
        {
            "edge_id": "I1-storage",
            "source_resource_id": "it:instance:I1",
            "target_resource_id": "it:storage:S1",
            "relation_type": "INSTANCE_LINKS_STORAGE",
            "directed": True,
            "source_id": "storage.csv",
            "source_kind": "REAL_EXPORT_REPLAY",
            "source_version": "sha256:topology-v1",
            "provenance_class": "EXTERNAL_OPERATIONAL",
            "provenance_subtype": "TOPOLOGY_EXTERNAL",
            "quality_status": "FAIL",
        },
        {
            "edge_id": "I2-storage",
            "source_resource_id": "it:instance:I2",
            "target_resource_id": "it:storage:S1",
            "relation_type": "INSTANCE_LINKS_STORAGE",
            "directed": True,
            "source_id": "storage.csv",
            "source_kind": "REAL_EXPORT_REPLAY",
            "source_version": "sha256:topology-v1",
            "provenance_class": "EXTERNAL_OPERATIONAL",
            "provenance_subtype": "TOPOLOGY_EXTERNAL",
            "quality_status": "UNKNOWN",
        },
    ]

    contexts = failure_domains_for_chain(package, "C")
    assert len(contexts) == 1
    assert contexts[0].quality_status == "FAIL"
    assert contexts[0].member_alarm_ids == frozenset({"a1", "a2"})
    assert contexts[0].eligible_for_candidate is False

    analysis = analyze_structural_audit(
        package,
        "C",
        policy=AuditExecutionPolicy(exact_max_members=10),
        mining_config=MiningConfig(config_version="test"),
        epsilon=0.3,
    )
    assert not any(
        item.candidate.source is CandidateSource.SHARED_RESOURCE_CONTEXT
        for item in analysis.structural_audit.scored_candidates
    )
