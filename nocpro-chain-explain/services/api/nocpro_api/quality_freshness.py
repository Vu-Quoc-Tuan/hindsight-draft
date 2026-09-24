"""One contract for deciding whether persisted chain quality is still current."""

from __future__ import annotations

from typing import Any

from .cohesion_advisor import (
    CHAIN_OVERVIEW_PROJECTION_VERSION,
    CHAIN_QUALITY_PIPELINE_VERSION,
)


def projection_staleness_reason(
    projection: Any,
    *,
    snapshot_id: str | None = None,
    snapshot_version: str | None = None,
    config_version: str | None = None,
    topology_version: str | None = None,
    topology_version_known: bool = False,
    input_fingerprint: str | None = None,
) -> str | None:
    """Return the first identity mismatch, or ``None`` for a current projection.

    Unknown expected values are omitted; a known topology version must match.
    Snapshot fields were absent in legacy rows, so those fields remain optional
    until the projection schema is migrated and old rows are retired.
    """
    if not isinstance(projection, dict):
        return "PENDING"
    if projection.get("projection_version") != CHAIN_OVERVIEW_PROJECTION_VERSION:
        return "PROJECTION_STALE"
    if projection.get("pipeline_version") != CHAIN_QUALITY_PIPELINE_VERSION:
        return "PIPELINE_STALE"
    if snapshot_id is not None and projection.get("snapshot_id") not in (None, snapshot_id):
        return "SNAPSHOT_MISMATCH"
    if snapshot_version is not None and projection.get("snapshot_version") not in (None, snapshot_version):
        return "VERSION_MISMATCH"
    if config_version is not None and projection.get("config_version") != config_version:
        return "CONFIG_MISMATCH"
    if (topology_version_known or topology_version is not None) and projection.get("topology_version") != topology_version:
        return "TOPOLOGY_MISMATCH"
    if input_fingerprint is not None and projection.get("input_fingerprint") not in (None, input_fingerprint):
        return "FINGERPRINT_MISMATCH"
    return None


def terminal_quality_row_is_current(
    row: Any,
    *,
    snapshot_id: str | None = None,
    snapshot_version: str | None = None,
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
    if projection_staleness_reason(
        payload.get("overview_projection"),
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        config_version=config_version,
        topology_version=topology_version,
        topology_version_known=topology_version_known,
        input_fingerprint=getattr(row, "input_fingerprint", None),
    ) is not None:
        return False
    if status == "UNAVAILABLE":
        return True
    stars = getattr(row, "stars", None)
    if stars is None:
        stars = payload.get("stars")
    return isinstance(stars, (int, float))
