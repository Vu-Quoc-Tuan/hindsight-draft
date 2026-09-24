from __future__ import annotations

from dataclasses import replace
import json

import pytest

from libs.contracts.analysis_identity import (
    ANALYSIS_IDENTITY_VERSION,
    IDENTITY_INCOMPLETE,
    AnalysisIdentity,
    analysis_identity_from_projection,
    analysis_identity_from_review,
    identity_mismatch,
)


@pytest.fixture
def identity() -> AnalysisIdentity:
    return AnalysisIdentity(
        snapshot_id="snapshot-1",
        snapshot_version="001",
        chain_id="chain-1",
        topology_version="topology-7",
        analysis_config_version="analysis-config-3",
        review_config_version="review-config-2",
        pipeline_version="quality-pipeline-4",
        input_fingerprint="source-fingerprint",
    )


@pytest.mark.parametrize(
    ("field_name", "value", "reason"),
    [
        ("snapshot_id", "snapshot-2", "SNAPSHOT_MISMATCH"),
        ("snapshot_version", "1", "VERSION_MISMATCH"),
        ("chain_id", "chain-2", "CHAIN_MISMATCH"),
        ("topology_version", None, "TOPOLOGY_MISMATCH"),
        ("analysis_config_version", "analysis-config-4", "CONFIG_MISMATCH"),
        ("review_config_version", "review-config-3", "REVIEW_CONFIG_MISMATCH"),
        ("pipeline_version", "quality-pipeline-5", "PIPELINE_STALE"),
        ("input_fingerprint", "different-source", "FINGERPRINT_MISMATCH"),
    ],
)
def test_identity_comparator_reports_first_field_mismatch(identity, field_name, value, reason):
    assert identity_mismatch(replace(identity, **{field_name: value}), identity) == reason


def test_equal_explicit_no_topology_is_not_unknown(identity):
    expected = replace(identity, topology_version=None)
    assert identity_mismatch(expected, expected) is None
    assert identity_mismatch(identity, expected) == "TOPOLOGY_MISMATCH"


def test_json_round_trip_preserves_snapshot_version_as_a_string(identity):
    decoded = json.loads(json.dumps(identity.to_payload()))
    result = analysis_identity_from_projection({"analysis_identity": decoded})

    assert result.available
    assert result.identity == identity
    assert result.identity.snapshot_version == "001"
    assert isinstance(result.identity.snapshot_version, str)


@pytest.mark.parametrize(
    "missing_field",
    [
        "identity_version",
        "snapshot_id",
        "snapshot_version",
        "chain_id",
        "topology_version",
        "analysis_config_version",
        "review_config_version",
        "pipeline_version",
        "input_fingerprint",
    ],
)
def test_projection_identity_missing_any_field_is_incomplete(identity, missing_field):
    payload = identity.to_payload()
    del payload[missing_field]

    result = analysis_identity_from_projection({"analysis_identity": payload})

    assert result.identity is None
    assert result.reason == IDENTITY_INCOMPLETE


def test_legacy_flat_projection_is_not_upgraded_from_active_state(identity):
    result = analysis_identity_from_projection(
        {
            "snapshot_id": identity.snapshot_id,
            "snapshot_version": identity.snapshot_version,
            "chain_id": identity.chain_id,
            "config_version": identity.analysis_config_version,
            "topology_version": identity.topology_version,
            "pipeline_version": identity.pipeline_version,
            "input_fingerprint": identity.input_fingerprint,
        }
    )

    assert result.identity is None
    assert result.reason == IDENTITY_INCOMPLETE


def test_review_adapter_requires_explicit_topology_field_and_uses_only_review_values(identity):
    review = {
        "snapshot_id": identity.snapshot_id,
        "snapshot_version": identity.snapshot_version,
        "chain_id": identity.chain_id,
        "analysis_version": identity.analysis_config_version,
        "config_version": identity.review_config_version,
        "topology_version": None,
    }
    result = analysis_identity_from_review(
        review,
        pipeline_version=identity.pipeline_version,
        input_fingerprint=identity.input_fingerprint,
    )
    assert result.available
    assert result.identity.topology_version is None
    assert result.identity.identity_version == ANALYSIS_IDENTITY_VERSION

    del review["topology_version"]
    incomplete = analysis_identity_from_review(
        review,
        pipeline_version=identity.pipeline_version,
        input_fingerprint=identity.input_fingerprint,
    )
    assert incomplete.identity is None
    assert incomplete.reason == IDENTITY_INCOMPLETE


def test_identity_rejects_non_string_snapshot_version(identity):
    payload = identity.to_payload()
    payload["snapshot_version"] = 1

    result = analysis_identity_from_projection({"analysis_identity": payload})

    assert result.identity is None
    assert result.reason == IDENTITY_INCOMPLETE
