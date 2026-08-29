"""Exact delta predicate indexing and reconciliation guards (§11, P0)."""

from __future__ import annotations

import pytest

from descriptor import DescriptorKind, MiningConfig, bitmap_of_members, mine_descriptors
from audit.candidates import descriptor_candidates
from libs.contracts import load_package
from tier1a import (
    IncompleteSnapshotError,
    IncrementalPredicateIndex,
    ReconciliationPolicy,
    ReconciliationReason,
    precompute_snapshot,
    reconciliation_reasons,
)


MINING = MiningConfig(config_version="incremental-test")


def _package(snapshot_id: str, records: list[tuple[str, str, str]], *, complete=True):
    alarms = []
    memberships = []
    for alarm_id, device, name in records:
        alarms.append(
            {
                "alarm_id": alarm_id,
                "snapshot_id": snapshot_id,
                "raw": {"device_code": device, "alarm_name": name},
                "device_code": device,
                "alarm_name": name,
            }
        )
        memberships.append(
            {"chain_id": "C", "alarm_id": alarm_id, "snapshot_id": snapshot_id}
        )
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": snapshot_id,
                "snapshot_version": "1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE" if complete else "INCOMPLETE",
                "source": "test",
                "source_kind": "REAL_EXPORT_REPLAY",
                "produced_at": "2026-01-01T00:00:00",
            },
            "alarms": alarms,
            "chains": [
                {"chain_id": "C", "snapshot_id": snapshot_id, "member_count": len(alarms)}
            ],
            "memberships": memberships,
        }
    )


def _descriptor_labels(index, members: set[str]) -> list[str]:
    target = bitmap_of_members(index, members)
    return [
        descriptor.label
        for descriptor in mine_descriptors(
            index, target, config=MINING, kind=DescriptorKind.IDENTITY
        )
    ]


def test_delta_new_cleared_and_updated_matches_full_rebuild():
    first = _package(
        "s1",
        [("a1", "D1", "DOWN"), ("a2", "D1", "DOWN"), ("a3", "D2", "POWER")],
    )
    second = _package(
        "s2",
        [
            ("a1", "D1", "DOWN"),
            ("a2", "D3", "DOWN"),  # active alarm changed a predicate
            ("a4", "D3", "DOWN"),  # new; a3 cleared
        ],
    )
    incremental = IncrementalPredicateIndex.from_package(first)

    update = incremental.apply_snapshot(second)
    view = incremental.view()

    assert update.new_ids == frozenset({"a4"})
    assert update.cleared_ids == frozenset({"a3"})
    assert update.updated_ids == frozenset({"a2"})
    assert set(view.active_ids) == set(second.alarms)

    from descriptor import build_predicate_index

    rebuilt = build_predicate_index(list(second.alarms.values()))
    assert _descriptor_labels(view, {"a1", "a2", "a4"}) == _descriptor_labels(
        rebuilt, {"a1", "a2", "a4"}
    )


def test_delta_keeps_full_postings_so_a_non_top_value_can_be_promoted():
    first = _package("s1", [("a1", "A", "X"), ("a2", "B", "X")])
    incremental = IncrementalPredicateIndex.from_package(first, max_values_per_field=1)
    assert {predicate.value for predicate in incremental.view().predicates()} >= {"X", "A"}

    second = _package(
        "s2",
        [("a1", "A", "X"), ("a2", "B", "X"), ("a3", "B", "X")],
    )
    incremental.apply_snapshot(second)

    device_values = {
        predicate.value
        for predicate in incremental.view().predicates()
        if predicate.field == "device_code"
    }
    assert device_values == {"B"}


def test_incremental_index_refuses_incomplete_snapshot():
    incomplete = _package("s1", [("a1", "D1", "X")], complete=False)
    with pytest.raises(IncompleteSnapshotError, match="COMPLETE"):
        IncrementalPredicateIndex.from_package(incomplete)


def test_precompute_accepts_exact_incremental_view_and_rejects_stale_view():
    first = _package("s1", [("a1", "D1", "X"), ("a2", "D1", "X")])
    second = _package("s2", [("a1", "D1", "X"), ("a3", "D2", "Y")])
    incremental = IncrementalPredicateIndex.from_package(first)

    with pytest.raises(ValueError, match="does not match snapshot alarms"):
        precompute_snapshot(second, mining_config=MINING, predicate_index=incremental.view())

    incremental.apply_snapshot(second)
    result = precompute_snapshot(
        second, mining_config=MINING, predicate_index=incremental.view()
    )
    assert result.alarm_count == 2


def test_descriptor_candidate_reads_stable_slots_after_a_clear():
    first = _package(
        "s1", [("a1", "D", "X"), ("a2", "D", "X"), ("a3", "D", "X")]
    )
    second = _package("s2", [("a1", "D", "X"), ("a3", "D", "X")])
    incremental = IncrementalPredicateIndex.from_package(first)
    incremental.apply_snapshot(second)
    view = incremental.view()
    descriptors = mine_descriptors(
        view,
        bitmap_of_members(view, {"a1", "a3"}),
        config=MINING,
        kind=DescriptorKind.IDENTITY,
    )

    candidates = descriptor_candidates(tuple(descriptors), view)

    assert candidates
    assert candidates[0].members == frozenset({"a1", "a3"})


def test_reconciliation_triggers_are_explicit_and_caller_configured():
    first = _package("s1", [(f"a{i}", "D", "X") for i in range(10)])
    second = _package(
        "s2",
        [(f"a{i}", "D", "X") for i in range(5, 10)]
        + [(f"b{i}", "E", "Y") for i in range(5)],
    )
    incremental = IncrementalPredicateIndex.from_package(first)
    update = incremental.apply_snapshot(second)

    reasons = reconciliation_reasons(
        update,
        active_alarm_count=10,
        policy=ReconciliationPolicy(max_delta_ratio=0.5),
        cache_consistency_error=True,
        snapshot_version_gap=True,
        off_peak_due=True,
    )

    assert reasons == frozenset(
        {
            ReconciliationReason.DELTA_THRESHOLD_EXCEEDED,
            ReconciliationReason.CACHE_CONSISTENCY_ERROR,
            ReconciliationReason.SNAPSHOT_VERSION_GAP,
            ReconciliationReason.OFF_PEAK_SCHEDULE,
        }
    )
