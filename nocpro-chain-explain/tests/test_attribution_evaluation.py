"""Deterministic exact deletion evaluation for Evidence Coverage Attribution."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from configuration import AttributionEvaluationConfig, ConfiguredValue, ParameterSource
from groups import IndexedChainStatistics, StatisticsMode, SupportIndexSemantics
from libs.provenance import ProvenanceClass, ProvenanceSubtype
from tier2.attribution_evaluation import (
    RANDOMIZATION_ALGORITHM,
    AttributionEvaluationReason,
    AttributionEvaluationStatus,
    _SplitMix64,
    _shuffle_in_place,
    evaluate_attribution_deletion,
)
from tier2.evidence_attribution import (
    AttributionExecutionPolicy,
    compute_evidence_coverage_attribution,
    build_exact_attribution_support,
)


def _config(*, seed: int = 42, repetitions: int = 100):
    return AttributionEvaluationConfig(
        randomization_algorithm=RANDOMIZATION_ALGORITHM,
        random_seed=ConfiguredValue(
            path="attribution_evaluation.randomization.seed",
            value=seed,
            source=ParameterSource.FROZEN_SPEC,
        ),
        random_repetitions=ConfiguredValue(
            path="attribution_evaluation.randomization.repetitions",
            value=repetitions,
            source=ParameterSource.FROZEN_SPEC,
        ),
    )


def _statistics() -> IndexedChainStatistics:
    members = ("a", "b", "c")
    stats = IndexedChainStatistics(
        chain_id="C1",
        members=members,
        statistics_mode=StatisticsMode.EXACT_INDEXED,
        support_index_semantics=SupportIndexSemantics.SYMMETRIC_UNORDERED_PAIRS_V1,
    )
    stats.channel_meta = {
        "identity": ("identity", ProvenanceClass.POST_HOC, None),
        "topology": (
            "topology",
            ProvenanceClass.EXTERNAL_OPERATIONAL,
            ProvenanceSubtype.TOPOLOGY_EXTERNAL,
        ),
        "behavior": ("behavior", ProvenanceClass.BEHAVIORAL, None),
    }
    # identity={ab,ac}; topology={ac,bc}; behavior={ab}
    stats.support_peer_bitmaps = {
        ("a", "identity"): 0b110,
        ("b", "identity"): 0b001,
        ("c", "identity"): 0b001,
        ("a", "topology"): 0b100,
        ("b", "topology"): 0b100,
        ("c", "topology"): 0b011,
        ("a", "behavior"): 0b010,
        ("b", "behavior"): 0b001,
        ("c", "behavior"): 0,
    }
    return stats


def _evaluate(*, config=None):
    stats = _statistics()
    attribution = compute_evidence_coverage_attribution(
        "C1",
        stats.members,
        stats,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )
    return evaluate_attribution_deletion(
        attribution,
        stats.members,
        stats,
        config=config if config is not None else _config(),
    )


def test_primary_and_reverse_recompute_exact_union_coverage():
    result = _evaluate(config=_config(repetitions=3))

    assert result.status is AttributionEvaluationStatus.AVAILABLE
    assert [item.split("|")[0] for item in result.primary.ordering] == [
        "topology",
        "identity",
        "behavior",
    ]
    assert result.primary.coverage_curve == pytest.approx((1.0, 2 / 3, 1 / 3, 0.0))
    assert result.primary.auc == pytest.approx(0.5)
    assert [item.split("|")[0] for item in result.reverse.ordering] == [
        "behavior",
        "identity",
        "topology",
    ]
    assert result.reverse.coverage_curve == pytest.approx((1.0, 1.0, 2 / 3, 0.0))
    assert result.reverse.auc == pytest.approx(13 / 18)
    # This explicitly differs from the forbidden 1-cumulative-phi shortcut.
    assert result.primary.coverage_curve[1] != pytest.approx(0.5)


def test_splitmix64_fisher_yates_has_a_cross_runtime_golden_sequence():
    rng = _SplitMix64(42)
    permutations = []
    for _ in range(4):
        values = ["a", "b", "c", "d", "e"]
        _shuffle_in_place(values, rng)
        permutations.append(tuple(values))

    assert permutations == [
        # Golden values define SPLITMIX64_FISHER_YATES_V1 semantics.
        ("b", "c", "a", "e", "d"),
        ("d", "e", "b", "c", "a"),
        ("b", "e", "d", "c", "a"),
        ("b", "a", "c", "e", "d"),
    ]


def test_random_baseline_uses_population_standard_deviation():
    result = _evaluate(config=_config(repetitions=4))

    assert result.random.algorithm == RANDOMIZATION_ALGORITHM
    assert result.random.seed == 42
    assert result.random.repetitions == 4
    assert result.random.repetitions_executed == 4
    # Fixed golden results also pin ddof=0 for pointwise curves and AUC.
    assert result.random.mean_curve == pytest.approx((1.0, 5 / 6, 7 / 12, 0.0))
    assert result.random.std_curve == pytest.approx(
        (0.0, 1 / 6, math.sqrt(3) / 12, 0.0)
    )
    assert result.random.mean_auc == pytest.approx(23 / 36)
    assert result.random.std_auc == pytest.approx(math.sqrt(3) / 36)


def test_equal_attribution_ties_use_stable_group_id_for_both_orders():
    stats = _statistics()
    stats.channel_meta = {
        "zeta": ("zeta", ProvenanceClass.POST_HOC, None),
        "alpha": ("alpha", ProvenanceClass.BEHAVIORAL, None),
    }
    all_peers = {"a": 0b110, "b": 0b101, "c": 0b011}
    stats.support_peer_bitmaps = {
        (alarm_id, channel_id): peers
        for alarm_id, peers in all_peers.items()
        for channel_id in stats.channel_meta
    }
    attribution = compute_evidence_coverage_attribution(
        "C1",
        stats.members,
        stats,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )

    result = evaluate_attribution_deletion(
        attribution,
        stats.members,
        stats,
        config=_config(repetitions=1),
    )

    expected = tuple(sorted(item.group_id for item in attribution.contributions))
    assert result.primary.ordering == expected
    assert result.reverse.ordering == expected


def test_missing_config_is_domain_unavailable():
    stats = _statistics()
    attribution = compute_evidence_coverage_attribution(
        "C1",
        stats.members,
        stats,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )
    result = evaluate_attribution_deletion(
        attribution,
        stats.members,
        stats,
        config=None,
    )
    assert result.status is AttributionEvaluationStatus.UNAVAILABLE
    assert result.reason is AttributionEvaluationReason.ATTRIBUTION_EVALUATION_CONFIG_INCOMPLETE


def test_unavailable_attribution_blocks_evaluation_before_randomization():
    stats = _statistics()
    attribution = compute_evidence_coverage_attribution(
        "C1",
        stats.members,
        None,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )

    result = evaluate_attribution_deletion(
        attribution,
        stats.members,
        stats,
        config=_config(),
    )

    assert result.status is AttributionEvaluationStatus.UNAVAILABLE
    assert result.reason is AttributionEvaluationReason.ATTRIBUTION_UNAVAILABLE
    assert result.random.repetitions_executed == 0


def test_mismatched_reused_support_fails_closed_instead_of_crashing_job():
    stats = _statistics()
    attribution = compute_evidence_coverage_attribution(
        "C1",
        stats.members,
        stats,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )
    support = build_exact_attribution_support(stats.members, stats)
    assert support is not None

    result = evaluate_attribution_deletion(
        attribution,
        stats.members,
        stats,
        config=_config(),
        exact_support=replace(support, total_pair_count=99),
    )

    assert result.status is AttributionEvaluationStatus.UNAVAILABLE
    assert result.reason is AttributionEvaluationReason.ATTRIBUTION_UNAVAILABLE


def test_deletion_curves_use_aggregated_signatures_not_member_rows():
    stats = _statistics()
    attribution = compute_evidence_coverage_attribution(
        "C1",
        stats.members,
        stats,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )
    support = build_exact_attribution_support(stats.members, stats)
    assert support is not None

    result = evaluate_attribution_deletion(
        attribution,
        stats.members,
        stats,
        config=_config(repetitions=4),
        exact_support=replace(support, group_peer_rows=()),
    )

    assert result.status is AttributionEvaluationStatus.AVAILABLE
    assert result.primary.coverage_curve == pytest.approx((1.0, 2 / 3, 1 / 3, 0.0))


def test_zero_groups_is_not_applicable_and_never_consumes_rng(monkeypatch):
    stats = _statistics()
    stats.channel_meta = {}
    stats.support_peer_bitmaps = {}
    attribution = compute_evidence_coverage_attribution(
        "C1",
        stats.members,
        stats,
        policy=AttributionExecutionPolicy(exact_max_members=3),
    )

    def forbidden_rng(*args, **kwargs):
        raise AssertionError("G=0 must not instantiate or consume RNG")

    monkeypatch.setattr("tier2.attribution_evaluation._SplitMix64", forbidden_rng)
    result = evaluate_attribution_deletion(
        attribution,
        stats.members,
        stats,
        config=_config(),
    )

    assert result.status is AttributionEvaluationStatus.NOT_APPLICABLE
    assert result.reason is AttributionEvaluationReason.NO_ELIGIBLE_GROUPS
    assert result.group_count == 0
    assert result.primary.coverage_curve == ()
    assert result.primary.auc is None
    assert result.random.mean_curve == ()
    assert result.random.mean_auc is None
    assert result.random.repetitions_executed == 0
