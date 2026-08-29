"""Gray-box adapter with exact ``M_pair`` present.

Covers the optional half of MVP item 1: exact pair metadata is ingested *when
upstream supplies it*, while raw values stay SYSTEM_FACT and are never
normalized into an Evidence channel (ADR-0008).
"""

from __future__ import annotations

import pytest

from graybox import adapt_graybox_metadata, render_text
from libs.contracts import load_package

TIMEWINDOW_VETO_SENTINEL = -999999999
ATTRIBUTE_REF = "SYN-ATTR-TIMEWINDOW-01"


@pytest.fixture()
def package():
    """Mirrors the mock's system_pair_metadata_semantics_v1 scenario."""
    return load_package(
        {
            "schema_version": "v1",
            "snapshot": {
                "snapshot_id": "s1",
                "snapshot_version": "1",
                "snapshot_time": "2026-01-01T00:00:00",
                "status": "COMPLETE",
                "source": "nocpro-mock",
                "source_kind": "SYNTHETIC_TEST",
                "produced_at": "2026-01-01T00:00:01+00:00",
                "schema_version": "v1",
            },
            "chains": [
                {"chain_id": "SYN-CHAIN-1", "snapshot_id": "s1", "member_count": 0}
            ],
            "system_metadata": {
                "attribute_configs": [
                    {
                        "attribute_type": 3,
                        "attribute_ref": ATTRIBUTE_REF,
                        "content": "TimeWindow",
                        "algorithm_type": "TIME_WINDOW",
                        "weight": 1.0,
                    }
                ],
                "pair_metadata_batches": [
                    {
                        "batch_id": "batch-1",
                        "coverage_scope": "BOUNDED_COMPARISON",
                        "attribute_ref": ATTRIBUTE_REF,
                        "chain_id": "SYN-CHAIN-1",
                        "pair_count": 4,
                        "max_compare_per_alarm": 1000,
                    }
                ],
                "pair_metadata": [
                    {
                        "chain_id": "SYN-CHAIN-1",
                        "alarm_id_a": "SYN-A-001",
                        "alarm_id_b": "SYN-A-002",
                        "system_pair_status": "EVALUATED",
                        "attribute_ref": ATTRIBUTE_REF,
                        "raw_score": 1.0,
                        "system_semantic": "SUPPORT",
                    },
                    {
                        "chain_id": "SYN-CHAIN-1",
                        "alarm_id_a": "SYN-A-001",
                        "alarm_id_b": "SYN-A-003",
                        "system_pair_status": "EVALUATED",
                        "attribute_ref": ATTRIBUTE_REF,
                        "raw_score": TIMEWINDOW_VETO_SENTINEL,
                        "system_semantic": "VETO",
                    },
                    {
                        "chain_id": "SYN-CHAIN-1",
                        "alarm_id_a": "SYN-A-002",
                        "alarm_id_b": "SYN-A-003",
                        "system_pair_status": "EVALUATED",
                        "attribute_ref": ATTRIBUTE_REF,
                        "raw_score": 2.0,
                        "system_semantic": "SUPPORT",
                    },
                    {
                        "chain_id": "SYN-CHAIN-1",
                        "alarm_id_a": "SYN-A-001",
                        "alarm_id_b": "SYN-A-004",
                        "system_pair_status": "NOT_EVALUATED",
                        "attribute_ref": ATTRIBUTE_REF,
                    },
                ],
            },
        }
    )


@pytest.fixture()
def metadata(package):
    return adapt_graybox_metadata(package, "SYN-CHAIN-1")


def test_pair_metadata_is_ingested(metadata):
    assert metadata.available is True
    assert len(metadata.pair_facts) == 4


def test_pair_lookup_is_undirected(metadata):
    forward = metadata.pair_fact("SYN-A-001", "SYN-A-002")
    reverse = metadata.pair_fact("SYN-A-002", "SYN-A-001")
    assert forward is not None
    assert forward == reverse


def test_veto_preserves_the_raw_sentinel(metadata):
    veto = metadata.pair_fact("SYN-A-001", "SYN-A-003")
    assert veto.is_veto is True
    assert veto.raw_score == TIMEWINDOW_VETO_SENTINEL
    # The sentinel must not be clamped or turned into a normalized score.
    assert veto.raw_score < 0


def test_out_of_range_score_is_preserved(metadata):
    """Raw 2.0 stays 2.0: normalizing it would make it evidence (ADR-0008)."""
    pair = metadata.pair_fact("SYN-A-002", "SYN-A-003")
    assert pair.raw_score == 2.0


def test_not_evaluated_pair_has_no_score(metadata):
    pair = metadata.pair_fact("SYN-A-001", "SYN-A-004")
    assert pair.system_pair_status == "NOT_EVALUATED"
    assert pair.raw_score is None
    assert pair.system_semantic is None


def test_absent_pair_resolves_unknown_not_neutral(metadata):
    """Under BOUNDED_COMPARISON, absence means 'not compared'."""
    assert metadata.pair_fact("SYN-A-001", "SYN-A-999") is None
    assert metadata.pair_status("SYN-A-001", "SYN-A-999") == "UNKNOWN"
    assert metadata.coverage_scope_for(ATTRIBUTE_REF) == "BOUNDED_COMPARISON"


def test_attribute_ref_links_pair_to_config(metadata):
    """A raw score is only interpretable via its Attribute."""
    refs = {c.attribute_ref for c in metadata.attribute_configs}
    assert all(f.attribute_ref in refs for f in metadata.pair_facts)
    config = metadata.attribute_configs[0]
    assert config.attribute_type == 3
    assert config.type_name == "TimeWindow"


def test_attribute_config_carries_no_raw_score(metadata):
    """M_pair and M_attribute_config stay type-separated."""
    config = metadata.attribute_configs[0]
    assert not hasattr(config, "raw_score")
    assert config.weight == 1.0


def test_system_fact_box_reports_pair_and_veto_counts(metadata):
    text = render_text(metadata)
    assert "Exact pair metadata: 4 record(s), 3 evaluated" in text
    assert "1 veto" in text
    assert "Attribute 3 TimeWindow" in text


def test_batch_coverage_is_not_duplicated_per_pair(metadata):
    """coverage_scope belongs to the batch, not to each pair."""
    assert len(metadata.coverage_batches) == 1
    assert metadata.coverage_batches[0].max_compare_per_alarm == 1000
    for fact in metadata.pair_facts:
        assert not hasattr(fact, "coverage_scope")
