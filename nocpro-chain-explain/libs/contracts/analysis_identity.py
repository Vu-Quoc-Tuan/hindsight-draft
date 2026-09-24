"""Versioned, immutable identity shared by analysis artifacts and clients."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Mapping


ANALYSIS_IDENTITY_VERSION = "analysis-identity-v1"
IDENTITY_INCOMPLETE = "IDENTITY_INCOMPLETE"


@dataclass(frozen=True)
class AnalysisIdentity:
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    topology_version: str | None
    analysis_config_version: str
    review_config_version: str | None
    pipeline_version: str
    input_fingerprint: str
    identity_version: str = ANALYSIS_IDENTITY_VERSION

    def __post_init__(self) -> None:
        if self.identity_version != ANALYSIS_IDENTITY_VERSION:
            raise ValueError(IDENTITY_INCOMPLETE)
        for name in (
            "snapshot_id",
            "snapshot_version",
            "chain_id",
            "analysis_config_version",
            "pipeline_version",
            "input_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(IDENTITY_INCOMPLETE)
        for name in ("topology_version", "review_config_version"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(IDENTITY_INCOMPLETE)

    def to_payload(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class IdentityAdapterResult:
    identity: AnalysisIdentity | None
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.identity is not None and self.reason is None


def _identity_from_mapping(values: Mapping[str, Any]) -> IdentityAdapterResult:
    required = (
        "identity_version",
        "snapshot_id",
        "snapshot_version",
        "chain_id",
        "topology_version",
        "analysis_config_version",
        "review_config_version",
        "pipeline_version",
        "input_fingerprint",
    )
    if any(name not in values for name in required):
        return IdentityAdapterResult(None, IDENTITY_INCOMPLETE)
    version = values["identity_version"]
    if version != ANALYSIS_IDENTITY_VERSION:
        return IdentityAdapterResult(None, IDENTITY_INCOMPLETE)
    try:
        return IdentityAdapterResult(
            AnalysisIdentity(
                snapshot_id=values["snapshot_id"],
                snapshot_version=values["snapshot_version"],
                chain_id=values["chain_id"],
                topology_version=values["topology_version"],
                analysis_config_version=values["analysis_config_version"],
                review_config_version=values["review_config_version"],
                pipeline_version=values["pipeline_version"],
                input_fingerprint=values["input_fingerprint"],
                identity_version=version,
            )
        )
    except (TypeError, ValueError):
        return IdentityAdapterResult(None, IDENTITY_INCOMPLETE)


def analysis_identity_from_projection(payload: Any) -> IdentityAdapterResult:
    """Adapt only an explicitly versioned public projection envelope.

    Legacy flat projection fields are intentionally not upgraded here: the
    caller must establish their canonical row identity before considering an
    old artifact reusable.
    """
    if not isinstance(payload, Mapping):
        return IdentityAdapterResult(None, IDENTITY_INCOMPLETE)
    identity = payload.get("analysis_identity")
    if not isinstance(identity, Mapping):
        return IdentityAdapterResult(None, IDENTITY_INCOMPLETE)
    return _identity_from_mapping(identity)


def analysis_identity_from_review(
    identity: Any,
    *,
    pipeline_version: str,
    input_fingerprint: str,
) -> IdentityAdapterResult:
    """Adapt a Review identity without filling fields from active state."""
    if is_dataclass(identity) and not isinstance(identity, type):
        values = asdict(identity)
    elif isinstance(identity, Mapping):
        values = identity
    else:
        try:
            values = vars(identity)
        except TypeError:
            return IdentityAdapterResult(None, IDENTITY_INCOMPLETE)

    required = (
        "snapshot_id",
        "snapshot_version",
        "chain_id",
        "topology_version",
        "analysis_version",
        "config_version",
    )
    if any(name not in values for name in required):
        return IdentityAdapterResult(None, IDENTITY_INCOMPLETE)
    return _identity_from_mapping(
        {
            "identity_version": ANALYSIS_IDENTITY_VERSION,
            "snapshot_id": values["snapshot_id"],
            "snapshot_version": values["snapshot_version"],
            "chain_id": values["chain_id"],
            "topology_version": values["topology_version"],
            "analysis_config_version": values["analysis_version"],
            "review_config_version": values["config_version"],
            "pipeline_version": pipeline_version,
            "input_fingerprint": input_fingerprint,
        }
    )


def identity_mismatch(
    actual: AnalysisIdentity, expected: AnalysisIdentity
) -> str | None:
    """Return the first ordered mismatch; equal explicit ``None`` is valid."""
    ordered_fields = (
        ("snapshot_id", "SNAPSHOT_MISMATCH"),
        ("snapshot_version", "VERSION_MISMATCH"),
        ("chain_id", "CHAIN_MISMATCH"),
        ("topology_version", "TOPOLOGY_MISMATCH"),
        ("analysis_config_version", "CONFIG_MISMATCH"),
        ("review_config_version", "REVIEW_CONFIG_MISMATCH"),
        ("pipeline_version", "PIPELINE_STALE"),
        ("input_fingerprint", "FINGERPRINT_MISMATCH"),
    )
    for field_name, reason in ordered_fields:
        if getattr(actual, field_name) != getattr(expected, field_name):
            return reason
    return None
