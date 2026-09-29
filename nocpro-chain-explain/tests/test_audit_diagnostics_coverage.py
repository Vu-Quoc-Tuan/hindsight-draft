from __future__ import annotations

from itertools import combinations

from audit_diagnostics.contracts import (
    CandidateOrigin,
    ComputationStatus,
    FrozenCandidate,
    GroupKey,
    PopulationRegion,
    ScopeState,
)
from audit_diagnostics.coverage import aggregate_coverage
from audit_diagnostics.scope import load_scope_policy
from channels.base import ChannelValue
from libs.provenance import ProvenanceClass


def _policy(tmp_path, *, metadata_rule=False):
    path = tmp_path / "scope.yaml"
    na_rule = ""
    na_ids = "[]"
    required = "[]"
    if metadata_rule:
        na_rule = "  - rule_id: outside_scope\n    predicate: pair_metadata_equals\n    metadata_key: domain\n    equals: outside\n"
        na_ids = "[outside_scope]"
        required = "[domain]"
    path.write_text(
        "schema_version: audit-scope-policy-v1\n"
        "policy_id: coverage-test\n"
        "policy_version: '1'\n"
        "approval_status: UNAPPROVED_DIAGNOSTIC_POLICY\n"
        "scope_rules:\n"
        "  - rule_id: all_pairs\n    predicate: every_distinct_pair\n"
        + na_rule
        + "channels:\n"
        "  - channel_id: S\n"
        "    execution_binding: test\n"
        "    scope_rule_id: all_pairs\n"
        f"    required_scope_metadata: {required}\n"
        f"    not_applicable_rule_ids: {na_ids}\n"
        "    missing_input_policy: applicable_unavailable\n",
        encoding="utf-8",
    )
    return load_scope_policy(path)


def _candidate(members):
    all_members = tuple(sorted(members))
    side_a = tuple(all_members[:3])
    side_b = tuple(all_members[3:])
    return FrozenCandidate(
        partition_id="a" * 64,
        members=all_members,
        side_a=side_a,
        side_b=side_b,
        side_a_fingerprint="b" * 64,
        side_b_fingerprint="c" * 64,
        origins=(CandidateOrigin(source="ENTITY", label="fixture", baseline_order=0),),
    )


def _value(state: str, left: str, right: str) -> ChannelValue:
    available = state != "UNAVAILABLE"
    score = 1.0 if state == "SUPPORT" else 0.0
    return ChannelValue(
        channel_id="S",
        derivation_tag="semantic",
        provenance_class=ProvenanceClass.POST_HOC,
        availability=available,
        positive_score=score,
        threshold=0.6,
        detail=f"{left}:{right}",
    )


def test_coverage_uses_applicable_denominator_and_partitions_candidate_regions(tmp_path):
    members = tuple(f"a{i}" for i in range(5))
    pairs = list(combinations(sorted(members), 2))
    values = {}
    metadata = {}
    states = ["SUPPORT", "SUPPORT", "SUPPORT", "NEUTRAL", "UNAVAILABLE", "UNAVAILABLE", "SUPPORT", "NEUTRAL", "UNAVAILABLE", "UNAVAILABLE"]
    for index, pair in enumerate(pairs):
        values[pair] = [_value(states[index], *pair)]
        metadata[pair] = {"domain": "outside" if index in (8, 9) else "inside"} if index not in (6, 7) else {}

    result = aggregate_coverage(
        members,
        values,
        candidates=(_candidate(members),),
        policy=_policy(tmp_path, metadata_rule=True),
        expected_channel_ids=("S",),
        expected_group_channels={
            GroupKey(
                derivation_tag="semantic",
                provenance_class=ProvenanceClass.POST_HOC,
                explain_eligible=True,
                role_eligible=True,
                audit_eligible=True,
            ): ("S",)
        },
        pair_scope_metadata=metadata,
    )

    row = result.channel_rows_all[0]
    assert result.pair_matrix_complete and result.registry_complete
    assert row.counts.total == 10
    assert row.counts.applicable == 6
    assert row.counts.not_applicable == 2
    assert row.counts.unknown_applicability == 2
    assert row.counts.available == 4
    assert row.counts.support == 3
    assert row.counts.neutral == 1
    assert row.counts.unavailable == 2
    assert row.ratios.coverage.value == 4 / 6
    assert row.ratios.applicability_share.value == 6 / 10
    assert row.ratios.unknown_scope_share.value == 2 / 10
    assert row.ratios.not_applicable_share.value == 2 / 10
    regional = result.by_candidate_region["a" * 64]
    counts = {item.region: item.counts.total for item in regional if item.channel_id == "S"}
    assert counts == {
        PopulationRegion.ALL: 10,
        PopulationRegion.WITHIN_A: 3,
        PopulationRegion.WITHIN_B: 1,
        PopulationRegion.CROSS: 6,
    }
    group_row = next(item for item in result.group_rows_all if item.effective_group_key)
    assert group_row.counts == row.counts


def test_incomplete_matrix_keeps_full_population_and_marks_invocation_gap(tmp_path):
    members = tuple(f"a{i}" for i in range(5))
    pairs = list(combinations(sorted(members), 2))
    values = {pair: [_value("SUPPORT", *pair)] for pair in pairs[:-1]}
    result = aggregate_coverage(
        members,
        values,
        candidates=(),
        policy=_policy(tmp_path),
        expected_channel_ids=("S",),
    )

    assert len(result.pair_universe.pairs) == 10
    assert result.pair_universe.computation_status is ComputationStatus.PARTIAL
    row = result.channel_rows_all[0]
    assert row.counts.total == 10
    assert row.invocation_status_counts[next(key for key in row.invocation_status_counts if key.value == "NOT_EVALUATED")] == 1
    assert row.computation_status is ComputationStatus.PARTIAL
    assert not result.pair_matrix_complete


def test_scope_evaluator_inconsistency_rejects_available_value_outside_scope(tmp_path):
    members = ("a", "b")
    pair = ("a", "b")
    result_policy = _policy(tmp_path, metadata_rule=True)
    values = {pair: [_value("SUPPORT", *pair)]}

    import pytest

    from audit_diagnostics.coverage import ScopeEvaluatorInconsistency

    with pytest.raises(ScopeEvaluatorInconsistency, match="outside registered scope"):
        aggregate_coverage(
            members,
            values,
            candidates=(),
            policy=result_policy,
            expected_channel_ids=("S",),
            pair_scope_metadata={pair: {"domain": "outside"}},
        )


def test_group_rollup_uses_registered_group_scope_and_preserves_canonical_support(tmp_path):
    policy_path = tmp_path / "group-scope.yaml"
    policy_path.write_text(
        "schema_version: audit-scope-policy-v1\n"
        "policy_id: group-scope\n"
        "policy_version: '1'\n"
        "approval_status: UNAPPROVED_DIAGNOSTIC_POLICY\n"
        "scope_rules:\n"
        "  - rule_id: all_pairs\n    predicate: every_distinct_pair\n"
        "channels:\n"
        "  - channel_id: S\n    execution_binding: test\n    scope_rule_id: all_pairs\n"
        "    required_scope_metadata: []\n    not_applicable_rule_ids: []\n"
        "    missing_input_policy: applicable_unavailable\n"
        "  - channel_id: S_alt\n    execution_binding: test\n    scope_rule_id: all_pairs\n"
        "    required_scope_metadata: [layer]\n    not_applicable_rule_ids: []\n"
        "    missing_input_policy: applicable_unavailable\n",
        encoding="utf-8",
    )
    values = {
        ("a", "b"): [
            _value("UNAVAILABLE", "a", "b"),
            ChannelValue(
                channel_id="S_alt",
                derivation_tag="semantic",
                provenance_class=ProvenanceClass.POST_HOC,
                availability=True,
                positive_score=1.0,
                threshold=0.6,
                detail="support from unknown-scope channel",
            ),
        ]
    }
    key = GroupKey(
        derivation_tag="semantic",
        provenance_class=ProvenanceClass.POST_HOC,
        explain_eligible=True,
        role_eligible=True,
        audit_eligible=True,
    )
    result = aggregate_coverage(
        ("a", "b"),
        values,
        candidates=(),
        policy=load_scope_policy(policy_path),
        expected_channel_ids=("S", "S_alt"),
        expected_group_channels={key: ("S", "S_alt")},
    )
    alternate = next(row for row in result.channel_rows_all if row.channel_id == "S_alt")
    group = result.group_rows_all[0]
    assert alternate.counts.unknown_applicability == 1
    assert alternate.counts.available == 0
    assert group.counts.applicable == 1
    assert group.counts.support == 1
    assert group.counts.available == 1
