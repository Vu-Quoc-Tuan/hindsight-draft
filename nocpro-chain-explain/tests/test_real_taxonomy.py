"""Test Real Data Taxonomy Adapter and Fingerprint Integration."""

from __future__ import annotations

from channels.real_taxonomy import (
    build_real_alarm_taxonomy,
    build_real_historical_taxonomy,
    extract_taxonomy_tokens_from_alarm,
)
from channels.semantic import evaluate_semantic_channel, SCORE_SAME_FAMILY
from history.evidence import TaxonomyLevel
from libs.contracts import IngestedAlarm
from similar_chains.fingerprint import (
    build_fingerprint,
)


def test_extract_taxonomy_tokens_from_real_records() -> None:
    raw_ip = {
        "alarm_name": "Interface down",
        "fault_id": "47933128",
        "group_name": "Cảnh báo event Core",
        "network_class_name": "AGG_DISTRICT",
    }
    alarm = IngestedAlarm(alarm_id="ALM_1", snapshot_id="S1", raw=raw_ip, alarm_name="Interface down")
    extracted = extract_taxonomy_tokens_from_alarm(alarm)
    assert extracted is not None
    name, tokens = extracted
    assert name == "Interface down"
    assert tokens.type == "47933128"
    assert tokens.family == "Cảnh báo event Core"
    assert tokens.category == "AGG_DISTRICT"


def test_semantic_channel_evaluates_with_real_taxonomy() -> None:
    alarm_a = IngestedAlarm(
        alarm_id="A1",
        snapshot_id="S1",
        alarm_name="Interface down",
        raw={"group_name": "Cảnh báo event Core"},
    )
    alarm_b = IngestedAlarm(
        alarm_id="A2",
        snapshot_id="S1",
        alarm_name="Port down LACP",
        raw={"group_name": "Cảnh báo event Core"},
    )

    taxonomy = build_real_alarm_taxonomy([alarm_a, alarm_b])
    assert taxonomy.family_of("Interface down") == "Cảnh báo event Core"
    assert taxonomy.family_of("Port down LACP") == "Cảnh báo event Core"

    result = evaluate_semantic_channel(alarm_a, alarm_b, taxonomy=taxonomy)
    assert result.availability is True
    assert result.positive_score == SCORE_SAME_FAMILY
    assert "same family" in result.detail


def test_fingerprint_uses_group_fallback_when_alarm_type_name_is_null() -> None:
    # Notice: alarm_type_name is None, exactly as in real Viettel NocPro export
    alarm = IngestedAlarm(
        alarm_id="A1",
        snapshot_id="S1",
        alarm_name="CBS. Alarm Power Rx Warning",
        raw={
            "alarm_type_name": None,
            "group_name": "Cảnh báo power Core",
            "fault_id": "715054",
            "device_type_name": "CX600-X8",
        },
    )

    fp = build_fingerprint(
        chain_id="C1",
        alarms=[alarm],
        identity_descriptors=[],
        duration_seconds=120,
    )

    assert "FAMILY:Cảnh báo power Core" in fp.family_terms.counts


def test_historical_taxonomy_token_lookup() -> None:
    alarm_it = IngestedAlarm(
        alarm_id="A_IT_1",
        snapshot_id="S1",
        alarm_name="Pod has been in a non-ready state",
        raw={
            "fault_id": "45058986",
            "group_name": "Cảnh báo UDCNTT_VCLOUD",
            "monitor_type_name": "Cảnh báo VCLOUD",
        },
    )

    hist_tax = build_real_historical_taxonomy([alarm_it])
    assert "Pod has been in a non-ready state" in hist_tax.tokens_by_alarm_name
    tokens = hist_tax.resolve(alarm_it)
    assert tokens is not None
    assert tokens.at(TaxonomyLevel.TYPE) == "45058986"
    assert tokens.at(TaxonomyLevel.FAMILY) == "Cảnh báo UDCNTT_VCLOUD"
    assert tokens.at(TaxonomyLevel.CATEGORY) == "Cảnh báo VCLOUD"


def test_missing_taxonomy_fields_remain_missing_without_fabricated_tokens() -> None:
    alarm = IngestedAlarm(
        alarm_id="A_MISSING",
        snapshot_id="S1",
        alarm_name="Observed name only",
        raw={"group_id": "123", "network_class_name": ""},
    )
    extracted = extract_taxonomy_tokens_from_alarm(alarm)
    assert extracted is not None
    _, tokens = extracted
    assert tokens.type is None
    assert tokens.family is None
    assert tokens.category is None
