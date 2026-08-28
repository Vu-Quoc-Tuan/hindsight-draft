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
