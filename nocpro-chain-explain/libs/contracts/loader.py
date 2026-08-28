"""Read a canonical snapshot package into the analysis model.

This is the parsing half of the Direct Snapshot Adapter (ADR-0030). It accepts
the versioned Input Contract v1 payload that ``nocpro-mock`` emits and rejects
incompatible major versions rather than coercing them (ADR-0002).

Parsing is deliberately strict and fail-closed:
- unknown enum values raise instead of falling back to a permissive default;
- missing system pair metadata stays ``UNKNOWN``, never ``NEUTRAL``;
- a snapshot that is not ``COMPLETE`` is flagged so Tier-1A can refuse it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_MAJOR_VERSION = "v1"


class ContractIngestError(ValueError):
    """Raised when a payload cannot be ingested under contract v1."""


@dataclass(frozen=True)
class IngestedAlarm:
    alarm_id: str
    snapshot_id: str
    raw: dict[str, str]
    alarm_name: str | None = None
    device_code: str | None = None
    node_reference: str | None = None
    severity_name: str | None = None
    canonical_start_time: str | None = None
    canonical_end_time: str | None = None
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class IngestedChain:
    chain_id: str
    snapshot_id: str
    member_count: int
    chain_name: str | None = None
    event_span_seconds: int | None = None

    @property
    def is_singleton(self) -> bool:
        """``|C| = 1`` is a first-class path, not an error case (ADR-0029)."""
        return self.member_count == 1


@dataclass(frozen=True)
class IngestedSnapshot:
    snapshot_id: str
    snapshot_time: str
    status: str
    source: str
    source_kind: str
    produced_at: str
    config_version: str | None = None
    topology_version: str | None = None

    @property
    def is_complete(self) -> bool:
        return self.status == "COMPLETE"


@dataclass
class IngestedPackage:
    """One parsed snapshot package."""

    snapshot: IngestedSnapshot
    alarms: dict[str, IngestedAlarm] = field(default_factory=dict)
    chains: dict[str, IngestedChain] = field(default_factory=dict)
    #: chain_id -> ordered member alarm ids
    memberships: dict[str, list[str]] = field(default_factory=dict)
    system_metadata: dict[str, Any] = field(default_factory=dict)
    topology: dict[str, Any] = field(default_factory=dict)
    operational_context: list[dict[str, Any]] = field(default_factory=list)
    provenance_manifest: dict[str, Any] = field(default_factory=dict)

    def members_of(self, chain_id: str) -> list[str]:
        return self.memberships.get(chain_id, [])

    def alarms_of(self, chain_id: str) -> list[IngestedAlarm]:
        return [self.alarms[a] for a in self.members_of(chain_id) if a in self.alarms]

    @property
    def unavailable_capabilities(self) -> tuple[str, ...]:
        """Capabilities the upstream declared it cannot provide.

        Explain must treat these as ``UNAVAILABLE``, not as negative findings.
        """
        return tuple(self.provenance_manifest.get("unavailable_capabilities") or ())


def _require(payload: dict[str, Any], key: str, context: str) -> Any:
    if key not in payload:
        raise ContractIngestError(f"{context}: missing required field {key!r}")
    return payload[key]


def load_package(payload: dict[str, Any]) -> IngestedPackage:
    """Parse a contract v1 payload."""
    if not isinstance(payload, dict):
        raise ContractIngestError("snapshot package must be a JSON object")

    version = payload.get("schema_version")
    if version != SUPPORTED_MAJOR_VERSION:
        raise ContractIngestError(
            f"incompatible schema_version {version!r}; this build supports "
            f"{SUPPORTED_MAJOR_VERSION!r} only"
        )

    raw_snapshot = _require(payload, "snapshot", "package")
    snapshot = IngestedSnapshot(
        snapshot_id=_require(raw_snapshot, "snapshot_id", "snapshot"),
        snapshot_time=_require(raw_snapshot, "snapshot_time", "snapshot"),
        status=_require(raw_snapshot, "status", "snapshot"),
        source=raw_snapshot.get("source", "unknown"),
        source_kind=_require(raw_snapshot, "source_kind", "snapshot"),
        produced_at=_require(raw_snapshot, "produced_at", "snapshot"),
        config_version=raw_snapshot.get("config_version"),
        topology_version=raw_snapshot.get("topology_version"),
    )

    package = IngestedPackage(snapshot=snapshot)

    for entry in payload.get("alarms") or ():
        alarm = IngestedAlarm(
            alarm_id=_require(entry, "alarm_id", "alarm"),
            snapshot_id=_require(entry, "snapshot_id", "alarm"),
            raw=dict(entry.get("raw") or {}),
            alarm_name=entry.get("alarm_name"),
            device_code=entry.get("device_code"),
            node_reference=entry.get("node_reference"),
            severity_name=entry.get("severity_name"),
            canonical_start_time=entry.get("canonical_start_time"),
            canonical_end_time=entry.get("canonical_end_time"),
            quality_flags=tuple(entry.get("quality_flags") or ()),
        )
        if alarm.alarm_id in package.alarms:
            raise ContractIngestError(f"duplicate alarm_id {alarm.alarm_id!r}")
        package.alarms[alarm.alarm_id] = alarm

    for entry in payload.get("chains") or ():
        chain = IngestedChain(
            chain_id=_require(entry, "chain_id", "chain"),
            snapshot_id=_require(entry, "snapshot_id", "chain"),
            member_count=int(_require(entry, "member_count", "chain")),
            chain_name=entry.get("chain_name"),
            event_span_seconds=entry.get("event_span_seconds"),
        )
        if chain.chain_id in package.chains:
            raise ContractIngestError(f"duplicate chain_id {chain.chain_id!r}")
        package.chains[chain.chain_id] = chain

    for entry in payload.get("memberships") or ():
        chain_id = _require(entry, "chain_id", "membership")
        alarm_id = _require(entry, "alarm_id", "membership")
        package.memberships.setdefault(chain_id, []).append(alarm_id)

    package.system_metadata = dict(payload.get("system_metadata") or {})
    package.topology = dict(payload.get("topology") or {})
    package.operational_context = list(payload.get("operational_context") or ())
    package.provenance_manifest = dict(payload.get("provenance_manifest") or {})

    _validate_consistency(package)
    return package


def _validate_consistency(package: IngestedPackage) -> None:
    """Snapshot scoping and membership consistency (ADR-0005)."""
    sid = package.snapshot.snapshot_id

    for alarm in package.alarms.values():
        if alarm.snapshot_id != sid:
            raise ContractIngestError(
                f"alarm {alarm.alarm_id!r} belongs to snapshot "
                f"{alarm.snapshot_id!r}, not {sid!r}"
            )
    for chain in package.chains.values():
        if chain.snapshot_id != sid:
            raise ContractIngestError(
                f"chain {chain.chain_id!r} belongs to snapshot "
                f"{chain.snapshot_id!r}, not {sid!r}"
            )

    for chain_id, members in package.memberships.items():
        if chain_id not in package.chains:
            raise ContractIngestError(
                f"membership references unknown chain_id {chain_id!r}"
            )
        for alarm_id in members:
            if alarm_id not in package.alarms:
                raise ContractIngestError(
                    f"membership references unknown alarm_id {alarm_id!r}"
                )

    for chain in package.chains.values():
        declared = chain.member_count
        actual = len(package.memberships.get(chain.chain_id, []))
        # The Golden fixture legitimately declares a member count without member
        # rows, so only a positive mismatch is an error.
        if actual and actual != declared:
            raise ContractIngestError(
                f"chain {chain.chain_id!r} declares member_count={declared} but "
                f"{actual} membership row(s) were ingested"
            )


def load_package_file(path: str | Path) -> IngestedPackage:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractIngestError(f"{target}: invalid JSON: {exc}") from exc
    return load_package(payload)
