"""Exact indexed Evidence Coverage Attribution contract."""

from __future__ import annotations

import math
from itertools import combinations
from math import factorial

import pytest

from groups import IndexedChainStatistics, StatisticsMode, SupportIndexSemantics
from libs.provenance import ProvenanceClass, ProvenanceSubtype
from tier2.evidence_attribution import (
    AttributionExecutionPolicy,
    AttributionMode,
    AttributionReason,
    AttributionStatus,
    compute_evidence_coverage_attribution,
)


def _statistics(*, duplicate_reference_channel: bool = False) -> IndexedChainStatistics:
    members = ("a", "b", "c")
    stats = IndexedChainStatistics(
        chain_id="C1",
        members=members,
        statistics_mode=StatisticsMode.EXACT_INDEXED,
        support_index_semantics=SupportIndexSemantics.SYMMETRIC_UNORDERED_PAIRS_V1,
    )
    stats.channel_meta = {
        "reference": ("identity", ProvenanceClass.POST_HOC, None),
        "topology": (
            "topology",
            ProvenanceClass.EXTERNAL_OPERATIONAL,
            ProvenanceSubtype.TOPOLOGY_EXTERNAL,
        ),
        "behavior": ("behavior", ProvenanceClass.BEHAVIORAL, None),
        "system": ("system", ProvenanceClass.SYSTEM_FACT, None),
    }
    # identity supports ab, ac; topology supports ac, bc; behavior supports ab.
    bitmaps = {
        ("a", "reference"): 0b110,
        ("b", "reference"): 0b001,
        ("c", "reference"): 0b001,
        ("a", "topology"): 0b100,
        ("b", "topology"): 0b100,
        ("c", "topology"): 0b011,
        ("a", "behavior"): 0b010,
        ("b", "behavior"): 0b001,
        ("c", "behavior"): 0,
        ("a", "system"): 0b110,
        ("b", "system"): 0b101,
        ("c", "system"): 0b011,
    }
    if duplicate_reference_channel:
        stats.channel_meta["reference_copy"] = (
            "identity",
            ProvenanceClass.POST_HOC,
            None,
        )
        for member in members:
            bitmaps[(member, "reference_copy")] = bitmaps[(member, "reference")]
    stats.support_peer_bitmaps = bitmaps
    return stats


def _compute(stats: IndexedChainStatistics):
    return compute_evidence_coverage_attribution(
        "C1",
        stats.members,
        stats,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )


def test_exact_closed_form_uses_explain_eligible_derivation_groups():
    result = _compute(_statistics())

    assert result.status is AttributionStatus.AVAILABLE
    assert result.mode is AttributionMode.EXACT
    assert result.covered_pair_count == 3
    assert result.total_coverage == 1.0
    by_tag = {item.derivation_tag: item for item in result.contributions}
    assert set(by_tag) == {"identity", "topology", "behavior"}
    assert math.isclose(by_tag["identity"].attribution, 1 / 3)
    assert math.isclose(by_tag["topology"].attribution, 1 / 2)
    assert math.isclose(by_tag["behavior"].attribution, 1 / 6)
    assert by_tag["behavior"].behavioral is True
    assert "system" not in by_tag


def test_duplicate_channel_inside_derivation_group_does_not_multiply_credit():
    baseline = _compute(_statistics())
    duplicated = _compute(_statistics(duplicate_reference_channel=True))

    assert duplicated.contributions == baseline.contributions


def test_effective_groups_with_same_tag_and_class_keep_distinct_stable_ids():
    stats = _statistics()
    stats.channel_meta["ticket"] = (
        "topology",
        ProvenanceClass.EXTERNAL_OPERATIONAL,
        ProvenanceSubtype.TICKET,
    )
    stats.support_peer_bitmaps.update(
        {
            ("a", "ticket"): 0b010,
            ("b", "ticket"): 0b001,
            ("c", "ticket"): 0,
        }
    )

    result = _compute(stats)
    topology_groups = [
        item for item in result.contributions if item.derivation_tag == "topology"
    ]

    assert len(topology_groups) == 2
    assert len({item.group_id for item in topology_groups}) == 2
    assert {item.audit_eligible for item in topology_groups} == {True, False}


def test_closed_form_matches_exhaustive_tiny_coverage_game():
    result = _compute(_statistics())
    supports = {
        "identity": {"ab", "ac"},
        "topology": {"ac", "bc"},
        "behavior": {"ab"},
    }
    players = tuple(supports)

    def value(coalition: tuple[str, ...]) -> float:
        covered = set().union(*(supports[player] for player in coalition)) if coalition else set()
        return len(covered) / 3

    exhaustive = {}
    for player in players:
        others = tuple(item for item in players if item != player)
        credit = 0.0
        for size in range(len(others) + 1):
            for coalition in combinations(others, size):
                weight = (
                    factorial(size)
                    * factorial(len(players) - size - 1)
                    / factorial(len(players))
                )
                credit += weight * (
                    value((*coalition, player)) - value(coalition)
                )
        exhaustive[player] = credit

    actual = {item.derivation_tag: item.attribution for item in result.contributions}
    assert actual == pytest.approx(exhaustive)


def test_large_chain_fails_closed_before_statistics_are_required():
    result = compute_evidence_coverage_attribution(
        "C1",
        tuple(f"a{i}" for i in range(4)),
        None,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )

    assert result.status is AttributionStatus.UNAVAILABLE
    assert result.mode is AttributionMode.UNAVAILABLE
    assert result.reason is AttributionReason.ATTRIBUTION_LIMIT_EXCEEDED
    assert result.chain_size == 4
    assert result.exact_max_members == 3
    assert result.contributions == ()


def test_ceiling_sized_exact_index_uses_bitmap_partitions_not_pair_matrix():
    member_count = 2_000
    members = tuple(f"a{index}" for index in range(member_count))
    stats = IndexedChainStatistics(
        chain_id="C1",
        members=members,
        statistics_mode=StatisticsMode.EXACT_INDEXED,
        support_index_semantics=SupportIndexSemantics.SYMMETRIC_UNORDERED_PAIRS_V1,
    )
    all_members = (1 << member_count) - 1
    for group_index in range(3):
        channel_id = f"channel-{group_index}"
        stats.channel_meta[channel_id] = (
            f"group-{group_index}",
            ProvenanceClass.POST_HOC,
            None,
        )
        for position, alarm_id in enumerate(members):
            stats.support_peer_bitmaps[(alarm_id, channel_id)] = (
                all_members & ~(1 << position)
            )

    result = compute_evidence_coverage_attribution(
        "C1",
        members,
        stats,
        policy=AttributionExecutionPolicy(exact_max_members=member_count),
    )

    assert result.status is AttributionStatus.AVAILABLE
    assert result.total_pair_count == 1_999_000
    assert result.covered_pair_count == result.total_pair_count
    assert result.total_coverage == 1.0
    assert [item.attribution for item in result.contributions] == pytest.approx(
        [1 / 3, 1 / 3, 1 / 3]
    )


def test_singleton_is_not_applicable_and_never_returns_zero_attribution():
    result = compute_evidence_coverage_attribution(
        "C1",
        ("a",),
        None,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )

    assert result.status is AttributionStatus.NOT_APPLICABLE
    assert result.mode is AttributionMode.UNAVAILABLE
    assert result.reason is AttributionReason.SINGLETON
    assert result.detail == "SINGLETON_CHAIN"
    assert result.total_coverage is None
    assert result.contributions == ()


def test_non_singleton_with_no_explain_eligible_groups_is_exact_zero_coverage():
    members = ("a", "b")
    stats = IndexedChainStatistics(
        chain_id="C1",
        members=members,
        statistics_mode=StatisticsMode.EXACT_INDEXED,
        support_index_semantics=SupportIndexSemantics.SYMMETRIC_UNORDERED_PAIRS_V1,
    )
    stats.channel_meta = {
        "system": ("system", ProvenanceClass.SYSTEM_FACT, None),
    }
    stats.support_peer_bitmaps = {
        ("a", "system"): 0b10,
        ("b", "system"): 0b01,
    }

    result = compute_evidence_coverage_attribution(
        "C1",
        members,
        stats,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )

    assert result.status is AttributionStatus.AVAILABLE
    assert result.mode is AttributionMode.EXACT
    assert result.total_pair_count == 1
    assert result.covered_pair_count == 0
    assert result.total_coverage == 0.0
    assert result.contributions == ()


def test_missing_exact_indexed_statistics_is_domain_unavailable():
    stats = _statistics()
    stats.statistics_mode = StatisticsMode.UNAVAILABLE

    result = _compute(stats)

    assert result.status is AttributionStatus.UNAVAILABLE
    assert result.reason is AttributionReason.EXACT_INDEXED_STATISTICS_UNAVAILABLE


def test_incomplete_or_malformed_support_index_fails_closed():
    missing = _statistics()
    del missing.support_peer_bitmaps[("a", "reference")]
    self_support = _statistics()
    self_support.support_peer_bitmaps[("a", "reference")] |= 0b001

    for stats in (missing, self_support):
        result = _compute(stats)
        assert result.status is AttributionStatus.UNAVAILABLE
        assert (
            result.reason
            is AttributionReason.EXACT_INDEXED_STATISTICS_UNAVAILABLE
        )
        assert result.contributions == ()


def test_uncertified_asymmetric_support_index_fails_closed():
    stats = _statistics()
    stats.support_index_semantics = SupportIndexSemantics.UNSPECIFIED
    stats.support_peer_bitmaps[("a", "reference")] = 0
    stats.support_peer_bitmaps[("b", "reference")] = 0b001

    result = _compute(stats)

    assert result.status is AttributionStatus.UNAVAILABLE
    assert result.reason is AttributionReason.EXACT_INDEXED_STATISTICS_UNAVAILABLE
