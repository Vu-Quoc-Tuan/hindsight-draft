"""Explanation drift tests (§7, ADR-0021; spec_sanity 18).

Central rule: a configuration change must never be reported as changed incident
behavior, and a tier without a cache on both sides reports unavailability rather
than "no drift".
"""

from __future__ import annotations

import pytest

from descriptor import (
    Descriptor,
    DescriptorKind,
    DescriptorMetrics,
    DescriptorSet,
    Predicate,
)
from evolution import (
    DriftAvailability,
    DriftCause,
    DriftTier,
    classify_cause,
    diff_descriptors,
    higher_tier_drift_available,
    tier1a_drift,
)


def _descriptor(value: str, *, coverage: int = 8, precision_fp: int = 2) -> Descriptor:
    return Descriptor(
        kind=DescriptorKind.IDENTITY,
        predicates=(Predicate(field="device_code", value=value, derivation_tag="device"),),
        extent=0,
        metrics=DescriptorMetrics(
            true_positives=coverage,
            false_positives=precision_fp,
            target_size=10,
            universe_size=1000,
        ),
    )


def _set(chain_id: str, values: list[str], config_version: str = "v17") -> DescriptorSet:
    return DescriptorSet(
        chain_id=chain_id,
        identity=tuple(_descriptor(v) for v in values),
        config_version=config_version,
    )


# --------------------------------------------------------------------------
# Descriptor diff
# --------------------------------------------------------------------------


def test_identical_descriptor_sets_show_no_change():
    drift = diff_descriptors(_set("C1", ["D1", "D2"]), _set("C1", ["D1", "D2"]))
    assert drift.changed is False
    assert drift.added == ()
    assert drift.removed == ()
    assert drift.top_descriptor_changed is False


def test_added_and_removed_descriptors_are_reported():
    drift = diff_descriptors(_set("C1", ["D1", "D2"]), _set("C1", ["D1", "D3"]))
    assert drift.added == ("device_code=D3",)
    assert drift.removed == ("device_code=D2",)
    assert drift.retained == ("device_code=D1",)
    assert drift.changed is True


def test_top_descriptor_change_is_detected():
    drift = diff_descriptors(_set("C1", ["D1", "D2"]), _set("C1", ["D2", "D1"]))
    assert drift.top_descriptor_changed is True
    assert drift.changed is True


def test_coverage_delta_is_reported():
    previous = DescriptorSet(
        chain_id="C1", identity=(_descriptor("D1", coverage=5),)
    )
    current = DescriptorSet(
        chain_id="C1", identity=(_descriptor("D1", coverage=9),)
    )
    drift = diff_descriptors(previous, current)
    assert drift.coverage_delta == pytest.approx(0.4)


# --------------------------------------------------------------------------
# Cause attribution
# --------------------------------------------------------------------------


def test_config_change_alone_is_config_drift():
    """spec_sanity 18: CONFIG_DRIFT must not be reported as DATA_DRIFT."""
    cause = classify_cause(
        descriptor_changed=True, membership_changed=False, config_changed=True
    )
    assert cause is DriftCause.CONFIG_DRIFT
    assert cause is not DriftCause.DATA_DRIFT


def test_membership_change_alone_is_data_drift():
    cause = classify_cause(
        descriptor_changed=True, membership_changed=True, config_changed=False
    )
    assert cause is DriftCause.DATA_DRIFT


def test_both_changed_is_mixed_not_data():
    """Attribution is ambiguous, so it must not default to data."""
    cause = classify_cause(
        descriptor_changed=True, membership_changed=True, config_changed=True
    )
    assert cause is DriftCause.MIXED
    assert cause is not DriftCause.DATA_DRIFT


def test_no_change_is_none():
    cause = classify_cause(
        descriptor_changed=False, membership_changed=False, config_changed=True
    )
    assert cause is DriftCause.NONE


# --------------------------------------------------------------------------
# Tier-1A drift
# --------------------------------------------------------------------------


def test_tier1a_drift_reports_config_wording():
    drift = tier1a_drift(
        "C1",
        previous_descriptors=_set("C1", ["D1"]),
        current_descriptors=_set("C1", ["D2"]),
        member_count_previous=10,
        member_count_current=10,
        previous_config_version="v17",
        current_config_version="v18",
    )
    assert drift.tier is DriftTier.TIER_1A
    assert drift.cause is DriftCause.CONFIG_DRIFT
    assert "analysis configuration changed" in drift.narrative
    # Must not claim the incident changed.
    assert "incident changed" not in drift.narrative


def test_tier1a_drift_reports_data_wording():
    drift = tier1a_drift(
        "C1",
        previous_descriptors=_set("C1", ["D1"]),
        current_descriptors=_set("C1", ["D2"]),
        member_count_previous=10,
        member_count_current=14,
        previous_config_version="v17",
        current_config_version="v17",
    )
    assert drift.cause is DriftCause.DATA_DRIFT
    assert "incident changed" in drift.narrative
    assert drift.member_count_delta == 4


def test_missing_descriptor_snapshot_is_unavailable_not_no_drift():
    drift = tier1a_drift(
        "C1",
        previous_descriptors=None,
        current_descriptors=_set("C1", ["D1"]),
        member_count_previous=None,
        member_count_current=10,
    )
    assert drift.availability is DriftAvailability.UNAVAILABLE_NO_CACHE
    assert drift.descriptor_drift is None
    assert "unavailable" in drift.narrative


def test_higher_tiers_need_a_cache_on_both_sides():
    """A role that was never computed cannot be diffed (ADR-0021)."""
    assert higher_tier_drift_available(True, True) is DriftAvailability.AVAILABLE
    assert (
        higher_tier_drift_available(True, False)
        is DriftAvailability.UNAVAILABLE_NO_CACHE
    )
    assert (
        higher_tier_drift_available(False, True)
        is DriftAvailability.UNAVAILABLE_NO_CACHE
    )


def test_lifecycle_event_is_carried_into_drift():
    from evolution import ChainEvolution, EvolutionEvent

    evolution = ChainEvolution(
        snapshot_chain_id="C1",
        event=EvolutionEvent.GROW,
        lineage_component_id="lc_0000",
        branch_id="lc_0000:b0",
        previous_chain_ids=("C0",),
        decomposition=None,
        jaccard=0.8,
        reason="grew",
    )
    drift = tier1a_drift(
        "C1",
        previous_descriptors=_set("C1", ["D1"]),
        current_descriptors=_set("C1", ["D1"]),
        member_count_previous=10,
        member_count_current=12,
        evolution=evolution,
    )
    assert drift.lifecycle_event == "GROW"
