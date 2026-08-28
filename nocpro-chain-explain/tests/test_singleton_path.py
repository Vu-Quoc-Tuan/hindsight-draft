"""Singleton path tests (MVP, ADR-0029; spec_sanity cases 30-31).

The trap: absence of pair evidence must yield NOT_APPLICABLE, never WEAK and
never ERROR. Singletons are 73.37% of observed chains.
"""

from __future__ import annotations

import pytest

from graybox import (
    PAIR_DEPENDENT_OPERATIONS,
    SINGLETON_SUPPORTED_OPERATIONS,
    MembershipVerdict,
    OperationStatus,
    build_singleton_report,
    operation_status,
    singleton_membership_verdict,
)
from libs.contracts import load_package


def _package(member_count: int):
    alarms = [
        {"alarm_id": f"a{i}", "snapshot_id": "s1", "raw": {}}
        for i in range(member_count)
    ]
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "nocpro-mock",
                "source_kind": "REAL_EXPORT_REPLAY",
                "produced_at": "2026-01-01T00:00:01+00:00",
                "schema_version": "v1",
            },
            "alarms": alarms,
            "chains": [
                {"chain_id": "c1", "snapshot_id": "s1", "member_count": member_count}
            ],
            "memberships": [
                {"chain_id": "c1", "alarm_id": f"a{i}", "snapshot_id": "s1"}
                for i in range(member_count)
            ],
        }
    )


def test_singleton_is_detected():
    package = _package(1)
    assert package.chains["c1"].is_singleton is True
    assert _package(2).chains["c1"].is_singleton is False


def test_singleton_is_never_weak():
    """spec_sanity 30: unavailable pair evidence must not produce WEAK."""
    chain = _package(1).chains["c1"]
    verdict = singleton_membership_verdict(chain)
    assert verdict is MembershipVerdict.NOT_APPLICABLE
    assert verdict is not MembershipVerdict.WEAK


def test_singleton_report_is_not_weak():
    report = build_singleton_report(_package(1), "c1")
    assert report.is_weak is False
    assert report.membership_verdict is MembershipVerdict.NOT_APPLICABLE


@pytest.mark.parametrize("operation", sorted(PAIR_DEPENDENT_OPERATIONS))
def test_pair_operations_return_not_applicable(operation):
    """spec_sanity 31: NOT_APPLICABLE, not ERROR and not a false 'stable'."""
    result = operation_status(operation, _package(1).chains["c1"])
    assert result.status is OperationStatus.NOT_APPLICABLE
    assert result.is_error is False
    assert "at least two members" in result.reason


@pytest.mark.parametrize("operation", sorted(SINGLETON_SUPPORTED_OPERATIONS))
def test_supported_operations_still_run_for_singletons(operation):
    """Chain overview / System Fact / descriptor / evolution keep working."""
    result = operation_status(operation, _package(1).chains["c1"])
    assert result.status is OperationStatus.AVAILABLE


def test_multi_member_chain_allows_pair_operations():
    chain = _package(5).chains["c1"]
    for operation in PAIR_DEPENDENT_OPERATIONS:
        assert operation_status(operation, chain).status is OperationStatus.AVAILABLE


def test_not_applicable_is_distinct_from_unavailable():
    """Structurally meaningless differs from missing input (⊥)."""
    assert OperationStatus.NOT_APPLICABLE is not OperationStatus.UNAVAILABLE
    assert MembershipVerdict.INSUFFICIENT_DATA is not MembershipVerdict.WEAK


def test_report_lists_both_sides():
    report = build_singleton_report(_package(1), "c1")
    assert {r.operation for r in report.supported} == SINGLETON_SUPPORTED_OPERATIONS
    assert {r.operation for r in report.not_applicable} == PAIR_DEPENDENT_OPERATIONS
    assert report.member_count == 1


def test_report_rejects_non_singleton():
    with pytest.raises(ValueError, match="not a singleton"):
        build_singleton_report(_package(3), "c1")


def test_unknown_chain_raises():
    with pytest.raises(KeyError):
        build_singleton_report(_package(1), "missing")
