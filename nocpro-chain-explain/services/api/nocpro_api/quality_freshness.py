"""One contract for deciding whether persisted chain quality is still current."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from libs.contracts.analysis_identity import (
    AnalysisIdentity,
    analysis_identity_from_projection,
    identity_mismatch,
)

from .cohesion_advisor import (
    CHAIN_OVERVIEW_PROJECTION_VERSION,
    CHAIN_QUALITY_PIPELINE_VERSION,
)
from .observability import active_observability
from .quality_readiness import quality_assessment_contract_is_valid


def record_quality_freshness_lag(
    row: Any | None, *, stage: str, state: str
) -> None:
    """Record persisted assessment age without attaching business identifiers."""
    updated_at = getattr(row, "updated_at", None)
    if not isinstance(updated_at, datetime) or updated_at.tzinfo is None:
        return
    age_seconds = (datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)).total_seconds()
    if age_seconds < 0:
        # A future DB timestamp indicates clock skew; do not report a false lag.
        return
    observability = active_observability()
    if observability is not None:
        observability.record_duration(
            "quality.freshness.lag",
            age_seconds,
            {"stage": stage, "cache.state": state},
        )


def projection_staleness_reason(
    projection: Any,
    *,
    snapshot_id: str | None = None,
    snapshot_version: str | None = None,
    chain_id: str | None = None,
    config_version: str | None = None,
    review_config_version: str | None = None,
    topology_version: str | None = None,
    topology_version_known: bool = False,
    input_fingerprint: str | None = None,
    canonical_row: Any | None = None,
) -> str | None:
    """Return the first identity mismatch, or ``None`` for a current projection.

    A valid public envelope is mandatory. Legacy flat projections are stale;
    callers must not fill missing values from current config or topology.
    """
    if not isinstance(projection, dict):
        return "PENDING"
    if projection.get("projection_version") != CHAIN_OVERVIEW_PROJECTION_VERSION:
        return "PROJECTION_STALE"
    adapted = analysis_identity_from_projection(projection)
    if not adapted.available or adapted.identity is None:
        return adapted.reason or "IDENTITY_INCOMPLETE"
    identity = adapted.identity

    flat_projection_fields = (
        ("snapshot_id", "snapshot_id", "SNAPSHOT_MISMATCH"),
        ("snapshot_version", "snapshot_version", "VERSION_MISMATCH"),
        ("chain_id", "chain_id", "CHAIN_MISMATCH"),
        ("config_version", "analysis_config_version", "CONFIG_MISMATCH"),
        ("review_config_version", "review_config_version", "REVIEW_CONFIG_MISMATCH"),
        ("topology_version", "topology_version", "TOPOLOGY_MISMATCH"),
        ("pipeline_version", "pipeline_version", "PIPELINE_STALE"),
        ("input_fingerprint", "input_fingerprint", "FINGERPRINT_MISMATCH"),
    )
    for public_name, identity_name, mismatch in flat_projection_fields:
        if public_name not in projection:
            return "IDENTITY_INCOMPLETE"
        if projection[public_name] != getattr(identity, identity_name):
            return mismatch

    expected_values = identity.to_payload()
    if snapshot_id is not None:
        expected_values["snapshot_id"] = snapshot_id
    if snapshot_version is not None:
        expected_values["snapshot_version"] = snapshot_version
    if chain_id is not None:
        expected_values["chain_id"] = chain_id
    if config_version is not None:
        expected_values["analysis_config_version"] = config_version
    if review_config_version is not None:
        expected_values["review_config_version"] = review_config_version
    if topology_version_known or topology_version is not None:
        expected_values["topology_version"] = topology_version
    expected_values["pipeline_version"] = CHAIN_QUALITY_PIPELINE_VERSION
    if input_fingerprint is not None:
        expected_values["input_fingerprint"] = input_fingerprint
    try:
        expected = AnalysisIdentity(**expected_values)
    except (TypeError, ValueError):
        return "IDENTITY_INCOMPLETE"
    mismatch = identity_mismatch(identity, expected)
    if mismatch is not None:
        return mismatch

    if canonical_row is not None:
        canonical_values = {
            "snapshot_id": getattr(canonical_row, "snapshot_id", None),
            "snapshot_version": getattr(canonical_row, "snapshot_version", None),
            "chain_id": getattr(canonical_row, "chain_id", None),
            "input_fingerprint": getattr(canonical_row, "input_fingerprint", None),
        }
        if any(value is None for value in canonical_values.values()):
            return "IDENTITY_INCOMPLETE"
        try:
            canonical_expected = AnalysisIdentity(
                **{
                    **identity.to_payload(),
                    **canonical_values,
                }
            )
        except (TypeError, ValueError):
            return "IDENTITY_INCOMPLETE"
        mismatch = identity_mismatch(identity, canonical_expected)
        if mismatch is not None:
            return mismatch
    return None


def terminal_quality_row_is_current(
    row: Any,
    *,
    snapshot_id: str | None = None,
    snapshot_version: str | None = None,
    review_config_version: str | None = None,
    config_version: str | None = None,
    topology_version: str | None = None,
    topology_version_known: bool = False,
) -> bool:
    payload = getattr(row, "payload", None)
    if not isinstance(payload, dict):
        return False
    status = getattr(row, "status", None)
    status = str(getattr(status, "value", status) or payload.get("status") or "").upper()
    if status not in {"EVALUATED", "UNAVAILABLE"}:
        return False
    if str(payload.get("status") or "").upper() != status:
        return False
    if hasattr(row, "stars") and getattr(row, "stars") != payload.get("stars"):
        return False
    if not quality_assessment_contract_is_valid(payload):
        return False
    if projection_staleness_reason(
        payload.get("overview_projection"),
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        chain_id=getattr(row, "chain_id", None),
        config_version=config_version,
        review_config_version=review_config_version,
        topology_version=topology_version,
        topology_version_known=topology_version_known,
        input_fingerprint=getattr(row, "input_fingerprint", None),
        canonical_row=row,
    ) is not None:
        return False
    return True
