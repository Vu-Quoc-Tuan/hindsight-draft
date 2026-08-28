"""Tier-1 indexed evidence and explicit pair-on-click behavior."""

from __future__ import annotations

import pytest

from channels import (
    evaluate_chain_channels,
    evaluate_chain_indexed,
    evaluate_pair_channels,
)
from groups import AuditGraphMode, PairMaterializationMode, StatisticsMode
from libs.contracts import load_package


@pytest.fixture()
def package():
    alarms = []
    memberships = []
    for index in range(4):
        alarm_id = f"a{index}"
        raw = {
            "location_code": "SITE-A",
            "component": "CARD-1" if index < 3 else "CARD-2",
        }
        alarms.append(
            {
                "alarm_id": alarm_id,
                "snapshot_id": "s1",
                "raw": raw,
                "alarm_name": "LINK DOWN" if index < 3 else "POWER FAIL",
                "device_code": "D1" if index < 3 else "D2",
                "node_reference": "R1" if index < 3 else "R2",
                "canonical_start_time": f"2026-01-01T00:00:0{index}",
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
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "test",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": "2026-01-01T00:00:00",
            },
            "alarms": alarms,
            "chains": [{"chain_id": "C1", "snapshot_id": "s1", "member_count": 4}],
            "memberships": memberships,
        }
    )


def test_indexed_chain_evaluation_has_explicit_modes(package, monkeypatch):
    import channels.evaluator as reference

    monkeypatch.setattr(
        reference,
        "pair_iterator",
        lambda members: (_ for _ in ()).throw(AssertionError("dense pair scan")),
    )
    evidence = evaluate_chain_indexed(package, "C1")
    assert evidence.statistics_mode is StatisticsMode.EXACT_INDEXED
    assert evidence.audit_graph_mode is AuditGraphMode.NOT_COMPUTED
    assert evidence.pair_materialization is PairMaterializationMode.ON_DEMAND
    assert evidence.detail_pairs == 0
    assert evidence.detail_truncated is False
    assert evidence.full_pair_space == 6


def test_pair_on_click_matches_reference_matrix(package):
    reference = evaluate_chain_channels(package, "C1")
    actual = evaluate_pair_channels(package, "C1", "a0", "a3")
    expected = reference.matrix.get("a0", "a3")
    assert [(v.channel_id, v.availability, v.supports) for v in actual] == [
        (v.channel_id, v.availability, v.supports) for v in expected
    ]


def test_pair_on_click_rejects_non_member(package):
    with pytest.raises(KeyError, match="not a member"):
        evaluate_pair_channels(package, "C1", "a0", "missing")


def test_indexed_unavailable_channels_remain_explicit(package):
    evidence = evaluate_chain_indexed(package, "C1")
    for alarm_id in evidence.members:
        assert evidence.statistics.fit_of(alarm_id, "T_delay").fit is None
        assert evidence.statistics.fit_of(alarm_id, "Dep_hop").fit is None
