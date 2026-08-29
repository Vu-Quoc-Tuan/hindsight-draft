"""Gray-box Metadata Adapter tests (MVP item 1).

The end-to-end cases ingest packages produced by the real ``nocpro-mock`` CLI, so
the adapter is exercised against the actual contract rather than hand-written
payloads. That is what ADR-0029 requires: gray-box metadata must arrive through
the adapter contract, not be hard-coded.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from graybox import (
    GrayBoxMetadata,
    adapt_graybox_metadata,
    render_system_fact_box,
    render_text,
)
from libs.contracts import ContractIngestError, load_package
from tests.conftest import MOCK_ROOT


def _snapshot(**overrides):
    payload = {
        "schema_version": "v1",
        "snapshot": {
            "snapshot_id": "s1",
            "snapshot_version": "1",
            "snapshot_time": "2026-01-01T00:00:00",
            "status": "COMPLETE",
            "source": "nocpro-mock",
            "source_kind": "REAL_EXPORT_REPLAY",
            "produced_at": "2026-01-01T00:00:01+00:00",
            "schema_version": "v1",
        },
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Contract ingestion
# --------------------------------------------------------------------------


def test_incompatible_major_version_is_rejected():
    with pytest.raises(ContractIngestError, match="incompatible schema_version"):
        load_package(_snapshot(schema_version="v2"))


def test_missing_snapshot_field_is_rejected():
    payload = _snapshot()
    del payload["snapshot"]["snapshot_id"]
    with pytest.raises(ContractIngestError, match="snapshot_id"):
        load_package(payload)


def test_membership_referencing_unknown_alarm_is_rejected():
    payload = _snapshot(
        chains=[{"chain_id": "c1", "snapshot_id": "s1", "member_count": 1}],
        memberships=[{"chain_id": "c1", "alarm_id": "ghost", "snapshot_id": "s1"}],
    )
    with pytest.raises(ContractIngestError, match="unknown alarm_id"):
        load_package(payload)


def test_cross_snapshot_record_is_rejected():
    payload = _snapshot(
        alarms=[{"alarm_id": "a1", "snapshot_id": "OTHER", "raw": {}}]
    )
    with pytest.raises(ContractIngestError, match="not 's1'"):
        load_package(payload)


def test_incomplete_snapshot_is_flagged():
    """Tier-1A must be able to refuse an incomplete snapshot (ADR-0005)."""
    payload = _snapshot()
    payload["snapshot"]["status"] = "INCOMPLETE"
    package = load_package(payload)
    assert package.snapshot.is_complete is False


# --------------------------------------------------------------------------
# Black-box degradation
# --------------------------------------------------------------------------


def test_missing_metadata_yields_blackbox_mode():
    """No system metadata means Black-box, not an error (§2)."""
    package = load_package(
        _snapshot(chains=[{"chain_id": "c1", "snapshot_id": "s1", "member_count": 0}])
    )
    metadata = adapt_graybox_metadata(package, "c1")
    assert metadata.available is False
    lines = render_system_fact_box(metadata)
    assert any(line.kind == "MODE" for line in lines)
    assert "Black-box" in lines[0].text


def test_missing_pair_metadata_defaults_to_unknown():
    """Never NEUTRAL: that would assert the system evaluated the pair."""
    metadata = GrayBoxMetadata(chain_id="c1")
    assert metadata.pair_status("a1", "a2") == "UNKNOWN"
    assert metadata.pair_fact("a1", "a2") is None


def test_unrecognized_enum_values_fail_closed():
    payload = _snapshot(
        chains=[{"chain_id": "c1", "snapshot_id": "s1", "member_count": 0}],
        system_metadata={
            "chain_characteristics": [
                {
                    "chain_id": "c1",
                    "name": "X",
                    "pair_count": 3,
                    "coverage_scope": "TOTALLY_COVERED",
                }
            ],
            "pair_metadata": [
                {
                    "chain_id": "c1",
                    "alarm_id_a": "a1",
                    "alarm_id_b": "a2",
                    "system_pair_status": "PROBABLY",
                }
            ],
        },
    )
    metadata = adapt_graybox_metadata(load_package(payload), "c1")
    # An unknown coverage scope must not be read as FULL_PAIR_SPACE.
    assert metadata.characteristics[0].coverage_scope == "UNKNOWN"
    assert metadata.characteristics[0].covers_full_pair_space is False
    assert metadata.pair_facts[0].system_pair_status == "UNKNOWN"


# --------------------------------------------------------------------------
# Golden 2214039 end-to-end through the mock CLI
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def golden_package(request):
    """Ingest the Golden package emitted by the real mock CLI."""
    if not MOCK_ROOT.is_dir():
        pytest.skip("sibling nocpro-mock repo not present")
    venv_python = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv_python) if venv_python.is_file() else sys.executable
    result = subprocess.run(
        [interpreter, "-m", "nocpro_mock.cli", "golden"],
        cwd=MOCK_ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"mock CLI unavailable: {result.stderr[:300]}")
    return load_package(json.loads(result.stdout))


def test_golden_rules_are_ingested(golden_package):
    metadata = adapt_graybox_metadata(golden_package, "2214039")
    assert metadata.available is True
    assert len(metadata.rules) == 3
    assert metadata.merge_strategy == "OR"

    remote = metadata.rule("CORE_CHAINING_REMOTE_NODE")
    assert remote.connector_count == 34
    assert remote.extender_count == 6
    assert remote.member_count == 58
    assert metadata.rule("CORE_CHAINING_REFERENCE_NODE").connector_count == 58
    assert metadata.rule("CORE_CHAINING_DEFAULT").connector_count == 18


def test_golden_connector_ratio_is_derived_not_asserted(golden_package):
    metadata = adapt_graybox_metadata(golden_package, "2214039")
    reference = metadata.rule("CORE_CHAINING_REFERENCE_NODE")
    assert reference.connector_ratio == pytest.approx(1.0)
    remote = metadata.rule("CORE_CHAINING_REMOTE_NODE")
    assert remote.connector_ratio == pytest.approx(34 / 58)


def test_golden_characteristics_keep_coverage_typing(golden_package):
    metadata = adapt_graybox_metadata(golden_package, "2214039")
    time_char = metadata.characteristics_named("TIME_LT_SECONDS")[0]
    assert time_char.pair_count == 1653
    assert time_char.threshold_seconds == 600
    assert time_char.covers_full_pair_space is True

    refs = {c.value: c for c in metadata.characteristics_named("NODE_REFERENCE_EQUAL")}
    assert refs["DEHL01"].pair_count == 435
    assert refs["DEHT01"].pair_count == 378
    # Aggregates without proven coverage stay UNKNOWN.
    assert refs["DEHL01"].covers_full_pair_space is False


def test_golden_aggregates_do_not_create_pair_facts(golden_package):
    """1653 aggregate pairs must not become 1653 exact pair records (ADR-0008)."""
    metadata = adapt_graybox_metadata(golden_package, "2214039")
    assert metadata.pair_facts == ()
    assert metadata.pair_status("any", "other") == "UNKNOWN"


def test_golden_declares_unavailable_capabilities(golden_package):
    metadata = adapt_graybox_metadata(golden_package, "2214039")
    assert "EXACT_PAIR_METADATA" in metadata.unavailable_capabilities
    lines = render_system_fact_box(metadata)
    assert any(line.kind == "UNAVAILABLE" for line in lines)


def test_system_fact_box_states_only_system_evidence(golden_package):
    """The box must not contain post-hoc conclusions (§2 wording discipline)."""
    metadata = adapt_graybox_metadata(golden_package, "2214039")
    text = render_text(metadata)
    assert "SYSTEM-PROVIDED EVIDENCE" in text
    assert "58 connector" in text
    assert "Merge: OR" in text

    lowered = text.lower()
    for forbidden in (
        "because",
        "over-merge",
        "nocpro is wrong",
        "discriminative",
        "root cause",
    ):
        assert forbidden not in lowered


def test_no_fabricated_model_internals(golden_package):
    """simiDict / A_ij / ΔQ are never required nor invented."""
    metadata = adapt_graybox_metadata(golden_package, "2214039")
    rendered = render_text(metadata).lower()
    for forbidden in ("simidict", "a_ij", "deltaq", "delta q", "modularity"):
        assert forbidden not in rendered
    assert metadata.attribute_configs == ()
