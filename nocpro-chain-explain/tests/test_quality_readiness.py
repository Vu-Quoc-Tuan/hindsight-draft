from __future__ import annotations

import pytest

from nocpro_api.quality_readiness import (
    evaluate_quality_readiness,
    quality_assessment_contract_is_valid,
)


def evaluate(**overrides):
    values = {
        "alarm_count": 4,
        "evaluated_members": 4,
        "topology_status": "AVAILABLE",
        "mapped_alarm_count": 4,
        "evaluated_pair_count": 6,
        "eligible_pair_count": 6,
        "mapped_device_count": 2,
        "total_device_count": 2,
        "audit_status": "EVALUATED",
        "audit_complete": True,
        "review_status": "COMPLETED",
    }
    values.update(overrides)
    return evaluate_quality_readiness(**values)


def test_complete_independent_families_and_zero_connected_paths_can_be_ready():
    readiness = evaluate()

    assert readiness.status == "READY"
    assert readiness.observed_families == ("membership", "topology", "structural")
    assert readiness.complete_families == ("topology", "structural")
    assert readiness.evaluated_pair_count == readiness.eligible_pair_count == 6


def test_role_coverage_exactly_half_is_sufficient_but_below_half_is_not():
    boundary = evaluate(evaluated_members=2)
    below = evaluate(evaluated_members=1)

    assert boundary.status == "READY"
    assert below.status == "INSUFFICIENT"
    assert "INSUFFICIENT_ROLE_COVERAGE" in below.missing_reasons


def test_audit_can_support_readiness_when_topology_is_unavailable():
    readiness = evaluate(
        topology_status="UNAVAILABLE",
        evaluated_pair_count=0,
        eligible_pair_count=0,
        mapped_device_count=0,
        total_device_count=2,
        audit_status="EVALUATED",
        audit_complete=True,
    )

    assert readiness.status == "READY"
    assert readiness.complete_families == ("structural",)
    assert readiness.observed_families == ("membership", "structural")
    assert "TOPOLOGY_NOT_USED" in readiness.missing_reasons


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"topology_status": "PARTIAL", "evaluated_pair_count": 3},
            "TOPOLOGY_PAIR_COVERAGE_INCOMPLETE",
        ),
        ({"mapped_device_count": 1}, "TOPOLOGY_MAPPING_INCOMPLETE"),
    ],
)
def test_partial_topology_is_visible_even_when_audit_is_an_independent_family(
    overrides, reason
):
    readiness = evaluate(**overrides)

    # An exact, complete Audit can support an Audit-only assessment; partial
    # topology remains visible but is excluded from its score.
    assert readiness.status == "READY"
    assert reason in readiness.missing_reasons
    assert "TOPOLOGY_NOT_USED" in readiness.missing_reasons


def test_partial_topology_without_an_independent_audit_is_insufficient():
    readiness = evaluate(
        topology_status="PARTIAL",
        evaluated_pair_count=3,
        audit_status="NOT_EVALUATED",
        audit_complete=False,
    )

    assert readiness.status == "INSUFFICIENT"
    assert "INSUFFICIENT_INDEPENDENT_EVIDENCE" in readiness.missing_reasons


def test_review_must_be_completed_even_when_other_evidence_is_complete():
    readiness = evaluate(review_status="NOT_EVALUATED")

    assert readiness.status == "PARTIAL"
    assert "REVIEW_NOT_COMPLETED" in readiness.missing_reasons


def test_unavailable_audit_is_not_mistaken_for_a_completed_independent_family():
    readiness = evaluate(audit_status="UNAVAILABLE", audit_complete=False)

    assert readiness.status == "READY"  # complete topology remains independent
    assert "AUDIT_UNAVAILABLE" in readiness.missing_reasons


def test_singleton_is_not_applicable():
    readiness = evaluate(
        alarm_count=1,
        evaluated_members=1,
        mapped_alarm_count=1,
        eligible_pair_count=0,
        evaluated_pair_count=0,
        mapped_device_count=1,
        total_device_count=1,
        topology_status="AVAILABLE",
    )

    assert readiness.status == "NOT_APPLICABLE"
    assert readiness.observed_families == ()
    assert "SINGLETON_CHAIN" in readiness.missing_reasons


@pytest.mark.parametrize(
    "overrides",
    [
        {"alarm_count": -1},
        {"evaluated_members": -1},
        {"evaluated_members": 5},
        {"mapped_device_count": -1},
        {"mapped_device_count": 3},
        {"mapped_alarm_count": -1},
        {"mapped_alarm_count": 5},
        {"evaluated_pair_count": -1},
        {"evaluated_pair_count": 7},
        {"alarm_count": True},
    ],
)
def test_inconsistent_or_negative_counts_raise_contract_error(overrides):
    with pytest.raises(ValueError):
        evaluate(**overrides)


def test_over_merge_is_not_added_as_a_second_structural_family():
    readiness = evaluate()

    assert "structural" in readiness.observed_families
    assert "over_merge" not in readiness.observed_families
    assert len(readiness.observed_families) == 3


@pytest.mark.parametrize(
    "assessment",
    [
        {
            "status": "EVALUATED",
            "readiness": "READY",
            "readiness_policy_version": "quality-readiness-v1",
            "reason_codes": [],
            "evidence_coverage": {},
            "stars": 4,
        },
        {
            "status": "UNAVAILABLE",
            "readiness": "PARTIAL",
            "readiness_policy_version": "quality-readiness-v1",
            "reason_codes": ["REVIEW_NOT_COMPLETED"],
            "evidence_coverage": {},
            "stars": None,
        },
    ],
)
def test_quality_assessment_status_and_readiness_contract(assessment):
    assert quality_assessment_contract_is_valid(assessment) is True


@pytest.mark.parametrize(
    "assessment",
    [
        {"status": "EVALUATED", "readiness": "PARTIAL", "stars": 4},
        {"status": "UNAVAILABLE", "readiness": "INSUFFICIENT", "stars": 1},
        {"status": "EVALUATED", "readiness": "READY", "stars": 0},
        {
            "status": "UNAVAILABLE",
            "readiness": "PARTIAL",
            "readiness_policy_version": "quality-readiness-v0",
            "reason_codes": [],
            "evidence_coverage": {},
            "stars": None,
        },
    ],
)
def test_quality_assessment_contract_fails_closed_on_status_or_policy_mismatch(assessment):
    assert quality_assessment_contract_is_valid(assessment) is False
