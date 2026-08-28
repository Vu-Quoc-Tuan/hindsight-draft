"""Descriptor mining tests (§5).

Covers the bitmap engine, the full metric set, bounded beam search, the
redundancy filter, and the two separate search objectives.
"""

from __future__ import annotations

import pytest

from descriptor import (
    Descriptor,
    DescriptorKind,
    MiningConfig,
    Predicate,
    build_predicate_index,
    bitmap_of_members,
    evaluate_extent,
    filter_redundant,
    jaccard,
    mine_descriptors,
    representativeness,
    representativeness_map,
)
from libs.contracts import IngestedAlarm

CONFIG = MiningConfig(config_version="desc-v1")


def alarm(alarm_id: str, **fields) -> IngestedAlarm:
    return IngestedAlarm(
        alarm_id=alarm_id,
        snapshot_id="s1",
        raw={k: str(v) for k, v in fields.items() if v is not None},
        alarm_name=fields.get("alarm_name"),
        device_code=fields.get("device_code"),
        node_reference=fields.get("node_reference"),
    )


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def test_metric_set_matches_the_spec_example():
    """30 inside + 500 outside of 100k: good FPR, bad precision."""
    from descriptor.metrics import DescriptorMetrics

    m = DescriptorMetrics(
        true_positives=30, false_positives=500, target_size=58, universe_size=100_000
    )
    assert m.coverage == pytest.approx(30 / 58, abs=1e-3)
    assert m.false_positive_rate == pytest.approx(0.005, abs=1e-4)
    # Precision is the metric that exposes the problem.
    assert m.precision == pytest.approx(30 / 530, abs=1e-4)
    assert m.precision < 0.06
    assert m.lift is not None and m.lift > 1


def test_lift_is_none_without_a_base_rate():
    from descriptor.metrics import DescriptorMetrics

    m = DescriptorMetrics(
        true_positives=0, false_positives=0, target_size=0, universe_size=0
    )
    assert m.lift is None
    assert m.coverage == 0.0


def test_common_but_undiscriminative_has_low_lift():
    """time<600s: 100% coverage, 94% of the universe => near-1 lift."""
    from descriptor.metrics import DescriptorMetrics

    m = DescriptorMetrics(
        true_positives=58, false_positives=9_400, target_size=58, universe_size=10_000
    )
    assert m.coverage == pytest.approx(1.0)
    assert m.lift is not None
    assert m.lift < 1.2


# --------------------------------------------------------------------------
# Predicate bitmaps
# --------------------------------------------------------------------------


def test_bitmap_popcount_matches_membership():
    universe = [
        alarm("a1", device_code="D1"),
        alarm("a2", device_code="D1"),
        alarm("a3", device_code="D2"),
    ]
    index = build_predicate_index(universe)
    d1 = Predicate(field="device_code", value="D1", derivation_tag="device")
    assert index.bitmap(d1).bit_count() == 2


def test_missing_field_creates_no_predicate():
    """Absence must not become a "value is empty" descriptor."""
    index = build_predicate_index([alarm("a1"), alarm("a2", device_code="D1")])
    fields = {p.field for p in index.predicates()}
    assert fields == {"device_code"}
    assert len(index.predicates()) == 1


def test_value_cap_keeps_most_frequent():
    universe = [alarm(f"a{i}", device_code=f"D{i}") for i in range(10)]
    universe += [alarm("hot1", device_code="HOT"), alarm("hot2", device_code="HOT")]
    index = build_predicate_index(universe, max_values_per_field=2)
    values = {p.value for p in index.predicates()}
    assert "HOT" in values
    assert len(values) == 2


def test_bitmap_of_members_selects_the_target():
    universe = [alarm("a1"), alarm("a2"), alarm("a3")]
    index = build_predicate_index(universe)
    target = bitmap_of_members(index, {"a1", "a3"})
    assert target.bit_count() == 2


# --------------------------------------------------------------------------
# Redundancy filter
# --------------------------------------------------------------------------


def test_jaccard_of_identical_extents_is_one():
    assert jaccard(0b1110, 0b1110) == pytest.approx(1.0)
    assert jaccard(0b1100, 0b0011) == pytest.approx(0.0)


def test_redundancy_filter_keeps_the_higher_scoring_rule():
    from descriptor.metrics import DescriptorMetrics

    def make(label_value: str, extent: int, coverage_tp: int) -> Descriptor:
        return Descriptor(
            kind=DescriptorKind.IDENTITY,
            predicates=(
                Predicate(field="f", value=label_value, derivation_tag="t"),
            ),
            extent=extent,
            metrics=DescriptorMetrics(
                true_positives=coverage_tp,
                false_positives=0,
                target_size=10,
                universe_size=100,
            ),
        )

    best = make("A", 0b1111111111, 10)
    near_duplicate = make("B", 0b1111111110, 9)
    distinct = make("C", 0b0000000011, 2)
    kept = filter_redundant([best, near_duplicate, distinct])
    labels = [d.predicates[0].value for d in kept]
    assert "A" in labels
    assert "B" not in labels
    assert "C" in labels


# --------------------------------------------------------------------------
# IDENTITY mining
# --------------------------------------------------------------------------


def _two_block_universe():
    """20 target alarms on D1, 20 non-target on D2."""
    universe = [alarm(f"t{i}", device_code="D1", alarm_name="X") for i in range(20)]
    universe += [alarm(f"o{i}", device_code="D2", alarm_name="Y") for i in range(20)]
    return universe


def test_identity_finds_the_defining_predicate():
    universe = _two_block_universe()
    index = build_predicate_index(universe)
    target = bitmap_of_members(index, {f"t{i}" for i in range(20)})
    descriptors = mine_descriptors(index, target, config=CONFIG)
    assert descriptors
    top = descriptors[0]
    assert top.metrics.coverage == pytest.approx(1.0)
    assert top.metrics.precision == pytest.approx(1.0)
    assert top.metrics.false_positive_rate == pytest.approx(0.0)


def test_identity_respects_the_global_precision_floor():
    """A rule covering everything cannot pass a high precision floor."""
    universe = [alarm(f"a{i}", severity_name="Major") for i in range(50)]
    index = build_predicate_index(universe)
    target = bitmap_of_members(index, {"a0", "a1"})
    strict = MiningConfig(config_version="v", precision_global_min=0.9)
    assert mine_descriptors(index, target, config=strict) == []


def test_identity_prefers_shorter_rules_on_a_coverage_tie():
    universe = _two_block_universe()
    index = build_predicate_index(universe)
    target = bitmap_of_members(index, {f"t{i}" for i in range(20)})
    descriptors = mine_descriptors(index, target, config=CONFIG)
    best = descriptors[0]
    # device_code=D1 alone is enough; a conjunction adds nothing.
    assert best.depth == 1


def test_beam_search_respects_max_depth():
    universe = [
        alarm(f"t{i}", device_code="D1", alarm_name="X", severity_name="Major")
        for i in range(10)
    ]
    universe += [
        alarm(f"o{i}", device_code="D2", alarm_name="Y", severity_name="Minor")
        for i in range(10)
    ]
    index = build_predicate_index(universe)
    target = bitmap_of_members(index, {f"t{i}" for i in range(10)})
    config = MiningConfig(config_version="v", max_depth=2, precision_global_min=0.5)
    descriptors = mine_descriptors(index, target, config=config)
    assert descriptors
    assert all(d.depth <= 2 for d in descriptors)


def test_one_field_per_rule():
    """``field=A AND field=B`` is unsatisfiable and must never be generated."""
    universe = _two_block_universe()
    index = build_predicate_index(universe)
    target = bitmap_of_members(index, {f"t{i}" for i in range(20)})
    for descriptor in mine_descriptors(index, target, config=CONFIG):
        fields = [p.field for p in descriptor.predicates]
        assert len(fields) == len(set(fields))


def test_empty_target_yields_nothing():
    index = build_predicate_index(_two_block_universe())
    assert mine_descriptors(index, 0, config=CONFIG) == []


def test_mining_is_deterministic():
    universe = _two_block_universe()
    index = build_predicate_index(universe)
    target = bitmap_of_members(index, {f"t{i}" for i in range(20)})
    first = mine_descriptors(index, target, config=CONFIG)
    second = mine_descriptors(index, target, config=CONFIG)
    assert [d.label for d in first] == [d.label for d in second]


def test_beam_does_not_revisit_predicates_disjoint_from_target():
    """A conjunction cannot cover the target if one operand is disjoint."""
    universe = [
        alarm("t", device_code="D1", alarm_name="X", severity_name="Major"),
        alarm("o", device_code="D2", alarm_name="Y", severity_name="Minor"),
    ]
    index = build_predicate_index(universe)
    target = bitmap_of_members(index, {"t"})
    disjoint = Predicate(field="device_code", value="D2", derivation_tag="device")
    calls: dict[Predicate, int] = {}
    original_bitmap = index.bitmap

    def counted_bitmap(predicate: Predicate) -> int:
        calls[predicate] = calls.get(predicate, 0) + 1
        return original_bitmap(predicate)

    index.bitmap = counted_bitmap  # type: ignore[method-assign]
    mine_descriptors(index, target, config=CONFIG)

    # Read once while filtering depth-1 seeds, never again during deepening.
    assert calls[disjoint] == 1


# --------------------------------------------------------------------------
# CONTRASTIVE mining
# --------------------------------------------------------------------------


def test_contrastive_requires_a_local_universe():
    """A global floor cannot express local discrimination."""
    index = build_predicate_index(_two_block_universe())
    target = bitmap_of_members(index, {f"t{i}" for i in range(20)})
    with pytest.raises(ValueError, match="requires a local_universe"):
        mine_descriptors(
            index, target, config=CONFIG, kind=DescriptorKind.CONTRASTIVE
        )


def test_globally_common_but_locally_discriminative_is_found():
    """The DIAMETER case: fails a global floor, passes locally.

    ``TYPE=D`` covers the whole target and a large slice of the global universe,
    so global precision is low. Inside ``U_local`` it is perfectly
    discriminative, which is exactly what CONTRASTIVE must surface.
    """
    target_alarms = [alarm(f"t{i}", alarm_name="D", device_code="D1") for i in range(10)]
    rival_alarms = [alarm(f"r{i}", alarm_name="E", device_code="D2") for i in range(10)]
    # Large global background that also carries alarm_name=D.
    background = [alarm(f"b{i}", alarm_name="D", device_code=f"B{i}") for i in range(200)]

    universe = target_alarms + rival_alarms + background
    index = build_predicate_index(universe, max_values_per_field=300)
    target = bitmap_of_members(index, {a.alarm_id for a in target_alarms})
    u_local = bitmap_of_members(
        index,
        {a.alarm_id for a in target_alarms} | {a.alarm_id for a in rival_alarms},
    )

    identity = mine_descriptors(
        index,
        target,
        config=MiningConfig(config_version="v", precision_global_min=0.9),
        local_universe=u_local,
    )
    name_rules = [d for d in identity if d.predicates[0].field == "alarm_name"]
    assert not name_rules, "alarm_name=D should fail the global precision floor"

    contrastive = mine_descriptors(
        index,
        target,
        config=MiningConfig(config_version="v", precision_local_min=0.9),
        kind=DescriptorKind.CONTRASTIVE,
        local_universe=u_local,
    )
    labels = [d.label for d in contrastive]
    assert "alarm_name=D" in labels
    found = next(d for d in contrastive if d.label == "alarm_name=D")
    assert found.precision_local == pytest.approx(1.0)
    # Globally it is a poor rule; that is the point.
    assert found.metrics.precision < 0.1


def test_local_universe_must_include_the_target():
    """Excluding C makes every local precision 0.0 and kills CONTRASTIVE.

    This pins a real bug: with ``U_local`` built from competitors only, local TP
    is always zero.
    """
    target_alarms = [alarm(f"t{i}", device_code="D1") for i in range(5)]
    rival_alarms = [alarm(f"r{i}", device_code="D2") for i in range(5)]
    index = build_predicate_index(target_alarms + rival_alarms)
    target = bitmap_of_members(index, {a.alarm_id for a in target_alarms})

    rivals_only = bitmap_of_members(index, {a.alarm_id for a in rival_alarms})
    broken = mine_descriptors(
        index,
        target,
        config=CONFIG,
        kind=DescriptorKind.CONTRASTIVE,
        local_universe=rivals_only,
    )
    assert broken == [], "competitors-only U_local cannot yield local precision"

    with_target = rivals_only | target
    working = mine_descriptors(
        index,
        target,
        config=CONFIG,
        kind=DescriptorKind.CONTRASTIVE,
        local_universe=with_target,
    )
    assert working
    assert working[0].precision_local == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Representativeness
# --------------------------------------------------------------------------


def test_representativeness_is_precision_weighted():
    universe = _two_block_universe()
    index = build_predicate_index(universe)
    target = bitmap_of_members(index, {f"t{i}" for i in range(20)})
    descriptors = tuple(mine_descriptors(index, target, config=CONFIG))

    inside = representativeness("t0", descriptors, index)
    outside = representativeness("o0", descriptors, index)
    assert inside is not None and outside is not None
    assert inside > outside
    assert 0.0 <= inside <= 1.0


def test_representativeness_is_unavailable_without_descriptors():
    """No descriptor means "unknown", not "atypical"."""
    index = build_predicate_index(_two_block_universe())
    assert representativeness("t0", (), index) is None


def test_representativeness_of_unknown_alarm_is_unavailable():
    index = build_predicate_index(_two_block_universe())
    target = bitmap_of_members(index, {f"t{i}" for i in range(20)})
    descriptors = tuple(mine_descriptors(index, target, config=CONFIG))
    assert representativeness("ghost", descriptors, index) is None


def test_representativeness_map_covers_every_member():
    index = build_predicate_index(_two_block_universe())
    members = [f"t{i}" for i in range(20)]
    target = bitmap_of_members(index, set(members))
    descriptors = tuple(mine_descriptors(index, target, config=CONFIG))
    mapping = representativeness_map(members, descriptors, index)
    assert set(mapping) == set(members)
    assert all(v is not None for v in mapping.values())


# --------------------------------------------------------------------------
# Contrastive top-3 bound (§5, §11)
# --------------------------------------------------------------------------


def test_top_contrastive_candidates_is_bounded_to_three_by_default():
    from descriptor.contrastive import BlockingCandidate, top_contrastive_candidates

    candidates = tuple(
        BlockingCandidate(chain_id=f"C{i}", shared_key="k", shared_value="v", overlap=10 - i)
        for i in range(5)
    )
    top3 = top_contrastive_candidates(candidates)
    assert len(top3) == 3
    assert [c.chain_id for c in top3] == ["C0", "C1", "C2"]


def test_top_contrastive_candidates_does_not_resort():
    """It takes a prefix of an already-ranked list; it must not re-rank."""
    from descriptor.contrastive import BlockingCandidate, top_contrastive_candidates

    # Deliberately not sorted by overlap; the function must not fix that.
    candidates = (
        BlockingCandidate(chain_id="LOW", shared_key="k", shared_value="v", overlap=1),
        BlockingCandidate(chain_id="HIGH", shared_key="k", shared_value="v", overlap=100),
    )
    top = top_contrastive_candidates(candidates, top_k=2)
    assert [c.chain_id for c in top] == ["LOW", "HIGH"]


def test_top_contrastive_candidates_fewer_than_k_returns_all():
    from descriptor.contrastive import BlockingCandidate, top_contrastive_candidates

    candidates = (BlockingCandidate(chain_id="only", shared_key="k", shared_value="v", overlap=1),)
    assert top_contrastive_candidates(candidates) == candidates


def test_default_contrastive_top_k_is_three():
    from descriptor.contrastive import DEFAULT_CONTRASTIVE_TOP_K

    assert DEFAULT_CONTRASTIVE_TOP_K == 3
