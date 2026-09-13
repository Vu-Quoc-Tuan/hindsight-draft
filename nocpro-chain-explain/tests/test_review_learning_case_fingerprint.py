from __future__ import annotations

from types import SimpleNamespace

from review_learning.case_fingerprint import extract_candidate_case_blocks


def _blocks(operation: str, before, after, source: str = "C"):
    return extract_candidate_case_blocks(
        candidate={
            "operation": operation,
            "source_chain_id": source,
            "partition_delta": {"before": before, "after": after},
        },
        chain_id=source,
        chain_alarms=[SimpleNamespace(device_code="D1", alarm_name="A")],
    )["operation_pattern"]


def test_operation_features_derive_from_canonical_partition_delta() -> None:
    remove = _blocks("REMOVE_MEMBER", [("C", ["a", "b"])], [("C", ["a"]), ("C::singleton::b", ["b"])])
    split = _blocks("SPLIT_CHAIN", [("C", ["a", "b", "c", "d"])], [("C", ["a", "b"]), ("C::split::1", ["c", "d"])])
    move = _blocks("MOVE_MEMBER", [("C", ["a", "b"]), ("T", ["x"])], [("C", ["a"]), ("T", ["b", "x"])])
    merge = _blocks("MERGE_CHAINS", [("C", ["a"]), ("T", ["b"])], [("CF-MERGE", ["a", "b"])])

    assert remove["removed_alarm_count"] == 1
    assert remove["created_chain_count"] == 1
    assert remove["relative_size_ratio"] == 0.5
    assert split["split_partition_count"] == 2
    assert split["created_chain_count"] == 1
    assert move["removed_alarm_count"] == 1
    assert move["moved_alarm_count"] == 1
    assert merge["removed_chain_count"] == 2
    assert merge["created_chain_count"] == 1
