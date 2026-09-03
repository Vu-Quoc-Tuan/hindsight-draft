"""Executable boundary: Tier-1B is indexed/local and never runs full audit."""

from __future__ import annotations

import inspect

import pytest

import channels.evaluator as pairwise_evaluator
from groups import AuditGraphMode, RoleThresholds
from descriptor import MiningConfig
from libs.contracts import load_package
from tier1b import analyze_chain


def _package():
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
            "alarms": [
                {
                    "alarm_id": f"a{i}",
                    "snapshot_id": "s1",
                    "raw": {"location_code": "SITE-A"},
                    "alarm_name": "LINK DOWN",
                    "device_code": "D1",
                    "node_reference": "R1",
                    "canonical_start_time": f"2026-01-01T00:00:0{i}",
                }
                for i in range(3)
            ],
            "chains": [{"chain_id": "C1", "snapshot_id": "s1", "member_count": 3}],
            "memberships": [
                {"chain_id": "C1", "alarm_id": f"a{i}", "snapshot_id": "s1"}
                for i in range(3)
            ],
        }
    )


def test_tier1b_orchestrator_has_no_dense_or_full_audit_call():
    source = inspect.getsource(analyze_chain)
    assert "evaluate_chain_channels(" not in source
    assert "build_audit_graph(" not in source
    assert "_rival_statistics(" not in source


def test_tier1b_reports_audit_not_computed():
    result = analyze_chain(
        _package(),
        "C1",
        thresholds=RoleThresholds(config_version="boundary-v1"),
        mining_config=MiningConfig(config_version="boundary-mine-v1"),
        enable_contrastive=False,
    )
    assert result.audit_graph_mode is AuditGraphMode.NOT_COMPUTED
    assert all(member.structural is None for member in result.members.values())


def _large_package(member_count: int = 1072):
    """A real large-chain boundary fixture, deliberately without pair materialization."""
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "large-boundary",
                "snapshot_version": "1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "test",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": "2026-01-01T00:00:00",
            },
            "alarms": [
                {
                    "alarm_id": f"large-{index:04d}",
                    "snapshot_id": "large-boundary",
                    "raw": {"location_code": "SITE-A"},
                    "alarm_name": "LINK DOWN",
                    "device_code": "D1",
                    "node_reference": "R1",
                    "canonical_start_time": "2026-01-01T00:00:00Z",
                }
                for index in range(member_count)
            ],
            "chains": [
                {
                    "chain_id": "LARGE-1072",
                    "snapshot_id": "large-boundary",
                    "member_count": member_count,
                }
            ],
            "memberships": [
                {
                    "chain_id": "LARGE-1072",
                    "alarm_id": f"large-{index:04d}",
                    "snapshot_id": "large-boundary",
                }
                for index in range(member_count)
            ],
        }
    )


def test_chain_1072_tier1b_fails_if_dense_pair_path_is_reintroduced(monkeypatch):
    """Tier-1B must stay indexed/local even at the largest recorded workload.

    This is intentionally an executable fail-closed gate: a future dense
    ``evaluate_chain_channels`` fallback calls this module-local iterator and
    fails immediately rather than turning a 1072-member click into O(n²).
    """

    def _dense_pair_path_forbidden(*_args, **_kwargs):
        pytest.fail("dense Tier-1B pair materialization is forbidden")

    monkeypatch.setattr(pairwise_evaluator, "pair_iterator", _dense_pair_path_forbidden)
    result = analyze_chain(
        _large_package(),
        "LARGE-1072",
        thresholds=RoleThresholds(config_version="boundary-v1"),
        mining_config=MiningConfig(config_version="boundary-mine-v1"),
        enable_contrastive=False,
    )
    assert len(result.members) == 1072
    assert result.audit_graph_mode is AuditGraphMode.NOT_COMPUTED
