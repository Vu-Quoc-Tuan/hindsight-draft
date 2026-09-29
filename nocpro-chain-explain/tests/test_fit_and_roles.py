"""Fit, MembershipSupport and role classification tests (§4B, ADR-0028).

Key invariants:
  - ``|D_k| = 0`` yields ⊥, not 0.0
  - one derivation group votes once regardless of channel count
  - the gate needs >= 2 distinct computable role-eligible groups
  - missing evidence gives INSUFFICIENT DATA, never WEAK
"""

from __future__ import annotations

import pytest

from channels.base import ChannelValue
from graybox.singleton import MembershipVerdict
from groups import (
    MIN_COMPUTABLE_GROUPS,
    SMALL_CHAIN_THRESHOLD,
    ChannelStatistics,
    RoleThresholds,
    availability_coverage,
    channel_fit,
    classify_membership,
    evaluate_gate,
    group_fits,
    membership_support,
)
from libs.provenance import ProvenanceClass

THRESHOLDS = RoleThresholds(config_version="test-v1")


def value(
    channel_id: str,
    derivation_tag: str,
    *,
    available: bool = True,
    score: float = 1.0,
    threshold: float = 1.0,
    provenance: ProvenanceClass = ProvenanceClass.POST_HOC,
) -> ChannelValue:
    return ChannelValue(
        channel_id=channel_id,
        derivation_tag=derivation_tag,
        provenance_class=provenance,
        availability=available,
        positive_score=score if available else 0.0,
        threshold=threshold,
    )


def stats(members: list[str], pairs: dict[tuple[str, str], list[ChannelValue]]):
    """Build exact statistics from explicit pair verdicts."""
    statistics = ChannelStatistics(chain_id="c1", members=tuple(members))
    for (alarm_a, alarm_b), values in pairs.items():
        statistics.record(alarm_a, alarm_b, values)
        statistics.pairs_counted += 1
    return statistics


# --------------------------------------------------------------------------
# Fit_k
# --------------------------------------------------------------------------


def test_fit_k_counts_only_available_partners():
    statistics = stats(
        ["x", "y", "z"],
        {
            ("x", "y"): [value("E_reference", "reference", score=1.0)],
            ("x", "z"): [value("E_reference", "reference", available=False)],
        },
    )
    fit = channel_fit("x", "E_reference", statistics)
    # |D_k| = 1 (only y), so Fit = 1/1 rather than 1/2.
    assert fit.domain_size == 1
    assert fit.fit == pytest.approx(1.0)


def test_fit_k_is_unavailable_when_domain_empty():
    """``|D_k| = 0 => Fit_k = ⊥``, which is not the same as 0.0."""
    statistics = stats(
        ["x", "y"],
        {("x", "y"): [value("E_reference", "reference", available=False)]},
    )
    fit = channel_fit("x", "E_reference", statistics)
    assert fit.fit is None
    assert fit.is_unavailable is True


def test_fit_k_neutral_partner_lowers_fit_but_stays_computable():
    statistics = stats(
        ["x", "y", "z"],
        {
            ("x", "y"): [value("E_reference", "reference", score=1.0)],
            ("x", "z"): [value("E_reference", "reference", score=0.0)],
        },
    )
    fit = channel_fit("x", "E_reference", statistics)
    assert fit.domain_size == 2
    assert fit.fit == pytest.approx(0.5)


# --------------------------------------------------------------------------
# Fit_g
# --------------------------------------------------------------------------


def test_group_fit_takes_max_over_channels():
    statistics = stats(
        ["x", "y"],
        {
            ("x", "y"): [
                value("E_reference", "reference", score=1.0),
                value("E_reference_alt", "reference", score=0.0),
            ]
        },
    )
    fits = {gf.derivation_tag: gf for gf in group_fits("x", statistics)}
    assert fits["reference"].fit == pytest.approx(1.0)


def test_three_channels_from_one_field_count_as_one_group():
    """ADR-0009 dedup: one derivation, one vote."""
    statistics = stats(
        ["x", "y"],
        {
            ("x", "y"): [
                value("E_ref_a", "reference", score=1.0),
                value("E_ref_b", "reference", score=1.0),
                value("E_ref_c", "reference", score=1.0),
                value("S", "semantic", score=1.0),
            ]
        },
    )
    support = membership_support("x", statistics)
    # Four channels, two groups.
    assert len(support.group_fits) == 2
    assert support.computable_group_count == 2
    assert support.support == pytest.approx(1.0)


def test_group_fit_unavailable_when_all_channels_unavailable():
    statistics = stats(
        ["x", "y"],
        {
            ("x", "y"): [
                value("Dep_hop", "dependency_hop", available=False),
                value("S", "semantic", score=1.0),
            ]
        },
    )
    fits = {gf.derivation_tag: gf for gf in group_fits("x", statistics)}
    assert fits["dependency_hop"].is_unavailable is True
    assert fits["semantic"].fit == pytest.approx(1.0)


def test_membership_support_averages_role_eligible_groups_only():
    statistics = stats(
        ["x", "y"],
        {
            ("x", "y"): [
                value("S", "semantic", score=1.0),
                value("E_reference", "reference", score=0.0),
                # BEHAVIORAL is not role-eligible, so it must not enter the mean.
                value(
                    "H",
                    "grouping_history",
                    score=1.0,
                    provenance=ProvenanceClass.BEHAVIORAL,
                ),
            ]
        },
    )
    support = membership_support("x", statistics)
    assert support.support == pytest.approx(0.5)
    assert support.computable_group_count == 2


def test_membership_support_does_not_weight_groups_by_domain_size():
    """Group fits get equal weight even when their available-peer counts differ."""
    statistics = stats(
        ["x", "y", "z", "w"],
        {
            ("x", "y"): [
                value("wide", "wide", score=1.0),
                value("small", "small", score=0.0),
            ],
            ("x", "z"): [
                value("wide", "wide", score=1.0),
                value("small", "small", available=False),
            ],
            ("x", "w"): [
                value("wide", "wide", score=1.0),
                value("small", "small", available=False),
            ],
        },
    )

    support = membership_support("x", statistics)

    # Fit_wide=3/3, Fit_small=0/1; equal group averaging gives 0.5.
    # Weighting by domain_size would instead give 0.75.
    assert support.support == pytest.approx(0.5)
    fits = {fit.derivation_tag: fit for fit in support.role_group_fits}
    assert fits["wide"].fit == pytest.approx(1.0)
    assert fits["wide"].channel_fits[0].domain_size == 3
    assert fits["small"].fit == pytest.approx(0.0)
    assert fits["small"].channel_fits[0].domain_size == 1


def test_system_fact_channel_never_enters_support():
    statistics = stats(
        ["x", "y"],
        {
            ("x", "y"): [
                value("S", "semantic", score=1.0),
                value("E_reference", "reference", score=1.0),
                value(
                    "M_pair",
                    "system_pair",
                    score=1.0,
                    provenance=ProvenanceClass.SYSTEM_FACT,
                ),
            ]
        },
    )
    support = membership_support("x", statistics)
    assert support.computable_group_count == 2
    assert support.support == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Gate
# --------------------------------------------------------------------------


def test_gate_requires_two_distinct_computable_groups():
    statistics = stats(["x", "y"], {("x", "y"): [value("S", "semantic", score=1.0)]})
    support = membership_support("x", statistics)
    gate = evaluate_gate(support, THRESHOLDS)
    assert gate.passed is False
    assert gate.computable_groups == 1
    assert f">= {MIN_COMPUTABLE_GROUPS}" in gate.reason


def test_gate_passes_with_two_groups():
    statistics = stats(
        ["x", "y"],
        {
            ("x", "y"): [
                value("S", "semantic", score=1.0),
                value("E_reference", "reference", score=1.0),
            ]
        },
    )
    support = membership_support("x", statistics)
    assert evaluate_gate(support, THRESHOLDS).passed is True


def test_availability_coverage_counts_computable_over_possible():
    statistics = stats(
        ["x", "y"],
        {
            ("x", "y"): [
                value("S", "semantic", score=1.0),
                value("E_reference", "reference", score=1.0),
                value("Dep_hop", "dependency_hop", available=False),
                value("T_delay", "temporal_delay", available=False),
            ]
        },
    )
    support = membership_support("x", statistics)
    assert availability_coverage(support) == pytest.approx(0.5)


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


def _support(score_a: float, score_b: float):
    statistics = stats(
        ["x", "y"],
        {
            ("x", "y"): [
                value("S", "semantic", score=score_a, threshold=0.5),
                value("E_reference", "reference", score=score_b, threshold=0.5),
            ]
        },
    )
    return membership_support("x", statistics)


def test_insufficient_data_when_gate_fails():
    """spec_sanity 7: missing evidence must not become WEAK."""
    statistics = stats(["x", "y"], {("x", "y"): [value("S", "semantic", score=1.0)]})
    support = membership_support("x", statistics)
    role = classify_membership(support, thresholds=THRESHOLDS, chain_size=10)
    assert role.verdict is MembershipVerdict.INSUFFICIENT_DATA
    assert role.is_weak is False


def test_all_unavailable_gives_insufficient_data_not_weak():
    statistics = stats(
        ["x", "y"],
        {
            ("x", "y"): [
                value("S", "semantic", available=False),
                value("E_reference", "reference", available=False),
            ]
        },
    )
    support = membership_support("x", statistics)
    assert support.all_unavailable is True
    role = classify_membership(support, thresholds=THRESHOLDS, chain_size=10)
    assert role.verdict is MembershipVerdict.INSUFFICIENT_DATA
    assert role.is_weak is False


def test_core_requires_the_absolute_floor():
    """The floor blocks 'best of a bad chain'."""
    role = classify_membership(
        _support(1.0, 1.0),
        thresholds=THRESHOLDS,
        chain_size=4,
        margin_common=0.2,
        representativeness=0.9,
    )
    assert role.verdict is MembershipVerdict.CORE


@pytest.mark.parametrize(
    ("support", "representativeness", "margin_common", "expected"),
    (
        (_support(1.0, 1.0), None, 0.2, MembershipVerdict.PERIPHERAL),
        (_support(1.0, 1.0), 0.9, None, MembershipVerdict.PERIPHERAL),
        (_support(0.0, 0.0), None, None, MembershipVerdict.PERIPHERAL),
        (_support(0.0, 0.0), None, -0.1, MembershipVerdict.WEAK),
        (_support(1.0, 1.0), 0.9, 0.2, MembershipVerdict.CORE),
    ),
)
def test_role_requires_computable_metrics_for_core_and_weak(
    support, representativeness, margin_common, expected
):
    role = classify_membership(
        support,
        thresholds=THRESHOLDS,
        chain_size=4,
        representativeness=representativeness,
        margin_common=margin_common,
    )

    assert role.verdict is expected


def test_high_rank_below_floor_is_not_core():
    role = classify_membership(
        _support(0.0, 1.0),
        thresholds=THRESHOLDS,
        chain_size=4,
        support_rank_quantile=0.0,
        margin_common=0.5,
        representativeness=1.0,
    )
    assert role.verdict is not MembershipVerdict.CORE


def test_weak_requires_low_band_and_non_positive_margin():
    weak = classify_membership(
        _support(0.0, 0.0), thresholds=THRESHOLDS, chain_size=10, margin_common=-0.1
    )
    assert weak.verdict is MembershipVerdict.WEAK

    # Same low support but a positive contrastive margin is not WEAK.
    not_weak = classify_membership(
        _support(0.0, 0.0), thresholds=THRESHOLDS, chain_size=10, margin_common=0.4
    )
    assert not_weak.verdict is MembershipVerdict.PERIPHERAL


def test_peripheral_is_the_middle_ground():
    role = classify_membership(
        _support(1.0, 0.0),
        thresholds=THRESHOLDS,
        chain_size=20,
        support_rank_quantile=0.9,
        margin_common=0.1,
    )
    assert role.verdict is MembershipVerdict.PERIPHERAL


def test_small_chain_skips_quantile():
    """``|C| < 8`` uses floors only."""
    role = classify_membership(
        _support(1.0, 1.0),
        thresholds=THRESHOLDS,
        chain_size=SMALL_CHAIN_THRESHOLD - 1,
        support_rank_quantile=0.99,
        margin_common=0.2,
        representativeness=1.0,
    )
    assert role.verdict is MembershipVerdict.CORE


def test_large_chain_applies_quantile():
    role = classify_membership(
        _support(1.0, 1.0),
        thresholds=THRESHOLDS,
        chain_size=SMALL_CHAIN_THRESHOLD + 5,
        support_rank_quantile=0.99,
        margin_common=0.2,
        representativeness=1.0,
    )
    assert role.verdict is not MembershipVerdict.CORE


def test_role_records_config_version():
    """ADR-0025: every explanation records its threshold config version."""
    role = classify_membership(_support(1.0, 1.0), thresholds=THRESHOLDS, chain_size=4)
    assert role.config_version == "test-v1"
    assert role.reason


# --------------------------------------------------------------------------
# Small-chain and singleton policy (pinned)
# --------------------------------------------------------------------------


def test_small_chain_uses_absolute_floors_only():
    """``|C| < 8``: no quantile rank, only S_min / S_weak.

    A member with worst rank in the chain must still reach CORE if it clears the
    absolute floor, because ranking within a tiny chain is not meaningful.
    """
    role = classify_membership(
        _support(1.0, 1.0),
        thresholds=THRESHOLDS,
        chain_size=7,
        support_rank_quantile=1.0,
        margin_common=0.2,
        representativeness=1.0,
    )
    assert role.verdict is MembershipVerdict.CORE

    # And a low-support member in a small chain can still be WEAK on the floor.
    weak = classify_membership(
        _support(0.0, 0.0),
        thresholds=THRESHOLDS,
        chain_size=7,
        support_rank_quantile=0.0,
        margin_common=-0.1,
    )
    assert weak.verdict is MembershipVerdict.WEAK


def test_singleton_is_not_applicable_not_weak():
    """``|C| = 1``: every Fit is ⊥, so the verdict is NOT_APPLICABLE."""
    from graybox.singleton import singleton_membership_verdict
    from libs.contracts import IngestedChain

    chain = IngestedChain(chain_id="c1", snapshot_id="s1", member_count=1)
    verdict = singleton_membership_verdict(chain)
    assert verdict is MembershipVerdict.NOT_APPLICABLE
    assert verdict is not MembershipVerdict.WEAK
    assert verdict is not MembershipVerdict.INSUFFICIENT_DATA


def test_singleton_statistics_produce_no_fit():
    """With one member there is no pair, so support is ⊥ and never WEAK."""
    statistics = stats(["x"], {})
    support = membership_support("x", statistics)
    assert support.support is None
    role = classify_membership(support, thresholds=THRESHOLDS, chain_size=1)
    assert role.verdict is MembershipVerdict.INSUFFICIENT_DATA
    assert role.is_weak is False
