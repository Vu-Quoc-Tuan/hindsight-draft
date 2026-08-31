"""Explicit Tier-2 structural-audit execution boundary."""

from __future__ import annotations

import pytest

from audit import AuditVerdict
from descriptor import MiningConfig
from groups import AuditGraphMode
from libs.contracts import load_package
from nocpro_api.serializers import deep_dive_view
from tier2 import AuditExecutionPolicy, analyze_structural_audit
from tier2.evidence_attribution import (
    AttributionMode,
    AttributionReason,
    AttributionStatus,
)


MINING = MiningConfig(config_version="tier2-test-v1")


def _package(member_count: int):
    alarms = []
    memberships = []
    for index in range(member_count):
        alarm_id = f"a{index}"
        alarms.append(
            {
                "alarm_id": alarm_id,
                "snapshot_id": "s1",
                "raw": {"location_code": "SITE-A"},
                "alarm_name": "LINK DOWN",
                "device_code": "D1",
                "node_reference": "R1",
                "canonical_start_time": f"2026-01-01T00:00:{index:02d}",
            }
        )
        memberships.append(
            {"chain_id": "C1", "alarm_id": alarm_id, "snapshot_id": "s1"}
        )
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_version": "1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "test",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": "2026-01-01T00:00:00",
            },
            "alarms": alarms,
            "chains": [
                {"chain_id": "C1", "snapshot_id": "s1", "member_count": member_count}
            ],
            "memberships": memberships,
        }
    )


def test_small_chain_runs_exact_audit_in_tier2():
    result = analyze_structural_audit(
        _package(6),
        "C1",
        policy=AuditExecutionPolicy(exact_max_members=10),
        mining_config=MINING,
        epsilon=0.3,
    )
    assert result.audit_graph_mode is AuditGraphMode.EXACT_FULL
    assert result.graph is not None
    assert len(result.structural_roles) == 6
    assert result.structural_audit is not None
    assert result.over_merge is not None
    assert result.reason is None


def test_tier2_uses_explicit_audit_balance_parameters():
    result = analyze_structural_audit(
        _package(6),
        "C1",
        policy=AuditExecutionPolicy(exact_max_members=10),
        mining_config=MINING,
        epsilon=0.3,
        rho=0.1,
        min_side_size=2,
        small_chain_threshold=4,
    )

    assert result.structural_audit.verdict is not AuditVerdict.SKIPPED_SMALL_CHAIN


def test_large_chain_returns_partial_domain_results_without_dense_paths(monkeypatch):
    import tier2.audit_analysis as audit_module

    def forbidden(*args, **kwargs):
        raise AssertionError("large-chain partial result must not build pair evidence/graph")

    monkeypatch.setattr(audit_module, "evaluate_chain_channels", forbidden)
    monkeypatch.setattr(audit_module, "build_audit_graph", forbidden)
    result = analyze_structural_audit(
        _package(6),
        "C1",
        policy=AuditExecutionPolicy(exact_max_members=5),
        mining_config=MINING,
        epsilon=0.3,
    )

    assert result.audit_graph_mode is AuditGraphMode.NOT_COMPUTED
    assert result.graph is None
    assert result.structural_audit.verdict is AuditVerdict.UNAVAILABLE
    assert result.structural_audit.reason == "AUDIT_LIMIT_EXCEEDED"
    assert result.over_merge.strength.value == "UNAVAILABLE"
    assert result.evidence_attribution.status is AttributionStatus.UNAVAILABLE
    assert (
        result.evidence_attribution.reason
        is AttributionReason.ATTRIBUTION_LIMIT_EXCEEDED
    )
    # Independent components still return domain results.
    assert result.similarity_unavailable_reason == "LINEAGE_NOT_READY"
    assert result.topology_hypotheses is not None
    serialized = deep_dive_view(result).model_dump()
    assert serialized["structural_audit"]["verdict"] == "UNAVAILABLE"
    assert serialized["structural_audit"]["reason"] == "AUDIT_LIMIT_EXCEEDED"
    assert serialized["evidence_attribution"] == {
        "status": "UNAVAILABLE",
        "mode": "UNAVAILABLE",
        "reason": "ATTRIBUTION_LIMIT_EXCEEDED",
        "detail": None,
        "chain_size": 6,
        "exact_max_members": 5,
        "total_pair_count": 15,
        "covered_pair_count": None,
        "total_coverage": None,
        "contributions": [],
    }


def test_singleton_attribution_is_not_applicable_without_zero_value():
    result = analyze_structural_audit(
        _package(1),
        "C1",
        policy=AuditExecutionPolicy(exact_max_members=5),
        mining_config=MINING,
        epsilon=0.3,
    )

    attribution = result.evidence_attribution
    assert attribution.status is AttributionStatus.NOT_APPLICABLE
    assert attribution.mode is AttributionMode.UNAVAILABLE
    assert attribution.reason is AttributionReason.SINGLETON
    assert attribution.detail == "SINGLETON_CHAIN"
    assert attribution.total_pair_count == 0
    assert attribution.covered_pair_count is None
    assert attribution.total_coverage is None
    assert attribution.contributions == ()


def test_policy_bound_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        AuditExecutionPolicy(exact_max_members=0)


def test_policy_cannot_claim_exact_above_implemented_guard():
    with pytest.raises(ValueError, match="implemented exact audit guard"):
        AuditExecutionPolicy(exact_max_members=2_001)
