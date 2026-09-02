"""Exact Cross-Chain Evidence Statistics regression tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from audit.graph import _channel_representatives
from channels import evaluate_chain_channels, exact_cross_chain_evidence
from libs.contracts import IngestedChain, load_package
from libs.provenance import build_derivation_groups


def _package():
    alarms = []
    memberships = []
    # All pairs share reference/device/name, while site is deliberately mixed:
    # it must remain available-but-neutral for the cross pairs with b2.
    fields = {
        "a1": {"location_code": "SITE_A", "component": "CARD_A"},
        "a2": {"location_code": "SITE_A", "component": "CARD_A"},
        "b1": {"location_code": "SITE_A", "component": "CARD_A"},
        "b2": {"location_code": "SITE_B", "component": None},
    }
    for alarm_id, values in fields.items():
        chain_id = "C1" if alarm_id.startswith("a") else "C2"
        raw = {
            "node_reference": "R1",
            "device_code": "D1",
            "alarm_name": "LINK DOWN",
            "canonical_start_time": "2026-01-01T00:00:00",
        }
        raw.update({key: value for key, value in values.items() if value is not None})
        alarms.append(
            {
                "alarm_id": alarm_id,
                "snapshot_id": "s1",
                "raw": raw,
                "alarm_name": "LINK DOWN",
                "device_code": "D1",
                "node_reference": "R1",
                "canonical_start_time": "2026-01-01T00:00:00",
            }
        )
        memberships.append(
            {"chain_id": chain_id, "alarm_id": alarm_id, "snapshot_id": "s1"}
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
                {"chain_id": "C1", "snapshot_id": "s1", "member_count": 2},
                {"chain_id": "C2", "snapshot_id": "s1", "member_count": 2},
            ],
            "memberships": memberships,
        }
    )


def _pairwise_oracle(package):
    """Slow oracle: evaluate the merged chain then filter C1 x C2 pairs."""
    oracle_package = deepcopy(package)
    oracle_package.chains["C_ORACLE"] = IngestedChain(
        chain_id="C_ORACLE", snapshot_id="s1", member_count=4
    )
    oracle_package.memberships["C_ORACLE"] = ["a1", "a2", "b1", "b2"]
    evidence = evaluate_chain_channels(
        oracle_package, "C_ORACLE", pair_detail_limit=100
    )

    available: dict[object, int] = {}
    support: dict[object, int] = {}
    edge_count = 0
    union_count = 0
    for left in ("a1", "a2"):
        for right in ("b1", "b2"):
            values = evidence.matrix.get(left, right)
            groups = [
                group
                for group in build_derivation_groups(_channel_representatives(values))
                if group.audit_eligible
            ]
            supporting = [group for group in groups if group.supports]
            for group in groups:
                available.setdefault(group.key, 0)
                support.setdefault(group.key, 0)
                if group.availability:
                    available[group.key] += 1
                if group.supports:
                    support[group.key] += 1
            union_count += bool(supporting)
            edge_count += len(supporting) >= 2
    return available, support, edge_count, union_count


def _by_tag(result):
    return {group.key.derivation_tag: group for group in result.groups}


def test_exact_cross_chain_statistics_preserve_available_neutral_and_unavailable():
    result = exact_cross_chain_evidence(_package(), "C2", "C1")
    by_tag = _by_tag(result)

    assert (result.left_chain_id, result.right_chain_id) == ("C1", "C2")
    assert result.cross_pair_count == 4
    assert by_tag["reference"].available_count == 4
    assert by_tag["reference"].support_count == 4
    assert by_tag["reference"].cross_fit == 1.0
    # SITE_B creates two computed non-supporting pairs; it is not unavailable.
    assert by_tag["site"].available_count == 4
    assert by_tag["site"].support_count == 2
    assert by_tag["site"].cross_fit == 0.5
    # b2 has no component.  Card evidence remains computable only for b1.
    assert by_tag["card"].available_count == 2
    assert by_tag["card"].support_count == 2
    # Remote endpoint is absent from every input: bottom, never a zero fit.
    assert by_tag["remote"].available_count == 0
    assert by_tag["remote"].support_count == 0
    assert by_tag["remote"].cross_fit is None

    assert result.cross_audit_edge_count == 4
    assert result.cross_audit_edge_coverage == 1.0
    assert result.cross_evidence_union_pair_count == 4
    assert result.cross_evidence_union_coverage == 1.0


def test_exact_cross_chain_statistics_match_pairwise_merged_chain_oracle():
    package = _package()
    result = exact_cross_chain_evidence(package, "C1", "C2")
    available, support, edge_count, union_count = _pairwise_oracle(package)

    assert result.cross_available_counts_by_group == available
    assert result.cross_support_counts_by_group == support
    assert result.cross_audit_edge_count == edge_count
    assert result.cross_evidence_union_pair_count == union_count
    for group in result.groups:
        expected = None if available[group.key] == 0 else support[group.key] / available[group.key]
        assert group.cross_fit == expected


def test_cross_chain_evidence_rejects_overlapping_memberships():
    package = _package()
    package.memberships["C2"].append("a1")

    with pytest.raises(ValueError, match="disjoint memberships"):
        exact_cross_chain_evidence(package, "C1", "C2")
