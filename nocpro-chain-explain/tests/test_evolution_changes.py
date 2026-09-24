"""The C4 pure facts layer uses supplied lineage and receipt evidence only."""

from __future__ import annotations

from copy import deepcopy

import pytest

from nocpro_api.evolution_changes import compare_evolution_facts


def edge(**changes):
    value = {
        "parent_snapshot_id": "s1", "parent_snapshot_version": "v1", "parent_chain_id": "c1",
        "child_snapshot_id": "s2", "child_snapshot_version": "v1", "child_chain_id": "c2",
        "event_type": "CONTINUE", "overlap_count": 2,
        "parent_snapshot_time": "2026-01-01T01:00:00+01:00",
        "child_snapshot_time": "2026-01-01T00:01:00Z",
        "parent_source_kind": "REAL_EXPORT_REPLAY", "child_source_kind": "REAL_EXPORT_REPLAY",
    }
    value.update(changes)
    return value


def receipt(snapshot_id, chain_id, receipt_id, **changes):
    value = {
        "receipt_id": receipt_id,
        "analysis_identity": {
            "snapshot_id": snapshot_id, "snapshot_version": "v1", "chain_id": chain_id,
            "topology_version": "topo-1", "analysis_config_version": "cfg-1",
            "review_config_version": "review-1", "pipeline_version": "pipe-1",
        },
        "assessment": {
            "status": "EVALUATED", "readiness": "READY", "method": "HEURISTIC_V1",
            "readiness_policy_version": "quality-readiness-v1", "score": 0.612345,
            "stars": 3,
        },
    }
    for key, change in changes.items():
        if key in value["analysis_identity"]:
            value["analysis_identity"][key] = change
        else:
            value["assessment"][key] = change
    return value


def compare(**changes):
    args = {
        "parent_members": {"a1", "a2", "a3"},
        "child_members": {"a2", "a3", "a4"},
        "parent_receipt": receipt("s1", "c1", "r1"),
        "child_receipt": receipt("s2", "c2", "r2", score=0.712345, stars=4),
        "lineage_edge": edge(),
    }
    args.update(changes)
    return compare_evolution_facts(**args)


def test_exact_membership_and_precise_delta():
    result = compare()
    assert result["status"] == "AVAILABLE"
    assert result["reason_codes"] == []
    assert result["membership"] == {
        "added_count": 1, "removed_count": 1, "retained_count": 2,
        "added_alarm_ids": ["a4"], "removed_alarm_ids": ["a1"], "truncated": False,
    }
    assert result["quality"]["delta"] == pytest.approx(0.1)
    assert result["quality"]["before_receipt_id"] == "r1"
    assert result["quality"]["after_receipt_id"] == "r2"
    assert {item["code"] for item in result["explanations"]} == {
        "MEMBERS_ENTERED_CHAIN", "MEMBERS_LEFT_CHAIN",
    }
    assert all("clear" not in item["text"].lower() for item in result["explanations"])


@pytest.mark.parametrize("event_type", ["SPLIT", "MERGE", "RECOMBINATION"])
def test_existing_split_merge_shape_is_preserved(event_type):
    result = compare(lineage_edge=edge(event_type=event_type))
    assert result["event_type"] == event_type
    assert result["membership"]["retained_count"] == 2
    assert all("audit" not in item["text"].lower() for item in result["explanations"])


def test_merge_predecessors_are_compared_as_separate_selected_edges():
    first = compare(lineage_edge=edge(event_type="MERGE"))
    second = compare(
        parent_members={"b1", "a2", "a3"},
        parent_receipt=receipt("s1", "other", "r-other"),
        lineage_edge=edge(parent_chain_id="other", event_type="MERGE"),
    )
    assert first["parent"]["chain_id"] == "c1"
    assert second["parent"]["chain_id"] == "other"
    assert second["membership"]["removed_alarm_ids"] == ["b1"]


def test_unverified_edge_or_missing_canonical_identity_fails_closed():
    missing = compare(lineage_edge=None)
    assert missing["status"] == "UNAVAILABLE"
    assert missing["membership"] is None
    assert "LINEAGE_EDGE_UNAVAILABLE" in missing["reason_codes"]
    assert compare(parent_members=None)["membership"] is None
    assert compare(parent_members=None)["reason_codes"] == ["CANONICAL_MEMBERSHIP_UNAVAILABLE"]
    assert compare(parent_members={""})["membership"] is None
    assert compare(parent_members=set(), child_members=set(), lineage_edge=edge(overlap_count=0))["membership"]["retained_count"] == 0


def test_overlap_mismatch_and_unrelated_reused_chain_id():
    assert "LINEAGE_OVERLAP_MISMATCH" in compare(lineage_edge=edge(overlap_count=3))["reason_codes"]
    unrelated = compare(lineage_edge=edge(parent_chain_id="c2", child_chain_id="c2", parent_snapshot_id=None))
    assert unrelated["membership"] is None
    assert unrelated["status"] == "UNAVAILABLE"


def test_same_snapshot_id_different_versions_remain_distinct():
    transition = edge(child_snapshot_id="s1", child_snapshot_version="v2")
    child = receipt("s1", "c2", "r2", score=0.712345)
    child["analysis_identity"]["snapshot_version"] = "v2"
    result = compare(lineage_edge=transition, child_receipt=child)
    assert result["parent"] != result["child"]
    assert result["quality"]["comparable"] is True


@pytest.mark.parametrize("time,expected", [
    ("2025-12-31T23:59:00Z", "SNAPSHOT_TIME_OUT_OF_ORDER"),
    ("2026-01-01T00:02:00", "SNAPSHOT_TIME_UNAVAILABLE"),
    ("not-a-time", "SNAPSHOT_TIME_UNAVAILABLE"),
])
def test_time_requires_valid_ordered_instants(time, expected):
    result = compare(lineage_edge=edge(child_snapshot_time=time))
    assert result["status"] == "PARTIAL"
    assert expected in result["reason_codes"]


def test_source_kind_remains_explicit_and_neutral():
    result = compare(lineage_edge=edge(parent_source_kind="SIMULATOR", child_source_kind="REAL_LIVE"))
    assert result["context_changes"] == [{
        "field": "source_kind", "before": "SIMULATOR", "after": "REAL_LIVE",
    }]
    assert "production" not in str(result["explanations"]).lower()


def test_missing_receipt_preserves_available_side_and_blocks_delta():
    result = compare(parent_receipt=None)
    assert result["membership"] is not None
    assert result["quality"]["after_stars"] == 4
    assert result["quality"]["before_stars"] is None
    assert result["quality"]["after_score"] == 0.712345
    assert result["quality"]["delta"] is None
    assert "QUALITY_RECEIPT_UNAVAILABLE" in result["quality"]["reason_codes"]


@pytest.mark.parametrize("change,reason", [
    ({"readiness": "NOT_READY"}, "QUALITY_NOT_READY"),
    ({"status": "UNAVAILABLE"}, "QUALITY_NOT_READY"),
    ({"method": "OTHER"}, "QUALITY_METHOD_MISMATCH"),
    ({"readiness_policy_version": "v2"}, "READINESS_POLICY_MISMATCH"),
    ({"analysis_config_version": "cfg-2"}, "ANALYSIS_CONFIG_MISMATCH"),
    ({"review_config_version": "review-2"}, "REVIEW_CONFIG_MISMATCH"),
    ({"pipeline_version": "pipe-2"}, "PIPELINE_MISMATCH"),
    ({"topology_version": "topo-2"}, "TOPOLOGY_VERSION_MISMATCH"),
    ({"score": float("nan")}, "PRECISE_SCORE_UNAVAILABLE"),
])
def test_comparability_gates(change, reason):
    result = compare(child_receipt=receipt("s2", "c2", "r2", **{"score": 0.712345, "stars": 4, **change}))
    assert result["quality"]["delta"] is None
    assert reason in result["quality"]["reason_codes"]
    assert result["quality"]["before_stars"] == 3
    assert result["quality"]["after_stars"] == 4


def test_topology_version_change_does_not_claim_physical_edge_delta():
    result = compare(child_receipt=receipt("s2", "c2", "r2", topology_version="topo-2"))
    assert result["context_changes"] == [{
        "field": "topology_version", "before": "topo-1", "after": "topo-2",
    }]
    assert result["quality"]["delta"] is None
    assert "physical" not in str(result["explanations"]).lower()


def test_input_fingerprint_can_change_with_membership():
    parent = receipt("s1", "c1", "r1")
    child = receipt("s2", "c2", "r2", score=0.712345)
    parent["analysis_identity"]["input_fingerprint"] = "a" * 64
    child["analysis_identity"]["input_fingerprint"] = "b" * 64
    result = compare(parent_receipt=parent, child_receipt=child)
    assert result["quality"]["comparable"] is True


def test_receipt_must_match_selected_version_and_chain():
    result = compare(child_receipt=receipt("unrelated", "c2", "r2"))
    assert "RECEIPT_IDENTITY_MISMATCH" in result["quality"]["reason_codes"]
    assert result["quality"]["delta"] is None


def test_bounded_sorted_ids_keep_exact_counts():
    before = {f"a{i:03}" for i in range(120)}
    after = {f"b{i:03}" for i in range(130)}
    result = compare(parent_members=before, child_members=after, lineage_edge=edge(overlap_count=0))
    membership = result["membership"]
    assert membership["added_count"] == 130
    assert membership["removed_count"] == 120
    assert membership["retained_count"] == 0
    assert membership["added_alarm_ids"] == sorted(after)[:100]
    assert membership["removed_alarm_ids"] == sorted(before)[:100]
    assert membership["truncated"] is True


def test_inputs_are_not_mutated():
    source = edge()
    original = deepcopy(source)
    compare(lineage_edge=source)
    assert source == original
