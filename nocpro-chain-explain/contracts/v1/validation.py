"""Canonical Input Contract v1 — validation.

Enforces the invariants the ADRs mark as required tests. Validation is
fail-closed: anything unproven is an error, never a silently coerced default.

Covers:
- ADR-0002  incompatible major version rejected; enum/format validated
- ADR-0005  Tier-1A only on COMPLETE snapshots; snapshot-scoped IDs
- ADR-0010  SYNTHETIC_TEST / BACKFILL cannot validate
- ADR-0011  failure domains stay hyperedges, never clique-projected
- ADR-0026  synthetic objects carry deterministic generation metadata
- ADR-MOCK-0005  no fuzzy mapping; undirected adjacency stays undirected
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .enums import (
    TIMEWINDOW_VETO_SENTINEL,
    VALIDATION_ELIGIBLE_SOURCE_KINDS,
    MappingMethod,
    MappingStatus,
    RelationType,
    SnapshotStatus,
    SourceKind,
    SystemPairStatus,
    SystemSemantic,
)
from .models import MockSnapshotPackage

SUPPORTED_SCHEMA_VERSION = "v1"


class ContractViolation(Exception):
    """Raised when a payload violates the canonical Input Contract."""


@dataclass
class ValidationResult:
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_failed(self) -> None:
        if self.errors:
            joined = "\n  - ".join(self.errors)
            raise ContractViolation(
                f"{len(self.errors)} contract violation(s):\n  - {joined}"
            )


def _check_version(pkg: MockSnapshotPackage, errors: list[str]) -> None:
    if pkg.schema_version != SUPPORTED_SCHEMA_VERSION:
        errors.append(
            f"incompatible schema_version {pkg.schema_version!r}; "
            f"expected {SUPPORTED_SCHEMA_VERSION!r}"
        )
    if pkg.snapshot.schema_version != SUPPORTED_SCHEMA_VERSION:
        errors.append(
            f"snapshot.schema_version {pkg.snapshot.schema_version!r} is incompatible"
        )


def _check_snapshot(pkg: MockSnapshotPackage, errors: list[str]) -> None:
    snap = pkg.snapshot
    if not snap.snapshot_id:
        errors.append("snapshot.snapshot_id is required")
    if not snap.snapshot_version:
        errors.append("snapshot.snapshot_version is required")
    if not snap.snapshot_time:
        errors.append("snapshot.snapshot_time is required")
    if not snap.produced_at:
        errors.append("snapshot.produced_at is required")
    for field_name, value in (
        ("snapshot_time", snap.snapshot_time),
        ("produced_at", snap.produced_at),
    ):
        if value:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"snapshot.{field_name} must be an ISO-8601 timestamp")
    if not isinstance(snap.status, SnapshotStatus):
        errors.append("snapshot.status must be a SnapshotStatus")
    if not isinstance(snap.source_kind, SourceKind):
        errors.append("snapshot.source_kind must be a SourceKind")


def _check_snapshot_scoping(pkg: MockSnapshotPackage, errors: list[str]) -> None:
    """Every record must belong to this snapshot (ADR-0005)."""
    sid = pkg.snapshot.snapshot_id
    for alarm in pkg.alarms:
        if alarm.snapshot_id != sid:
            errors.append(
                f"alarm {alarm.alarm_id!r} snapshot_id {alarm.snapshot_id!r} "
                f"does not match snapshot {sid!r}"
            )
    for chain in pkg.chains:
        if chain.snapshot_id != sid:
            errors.append(
                f"chain {chain.chain_id!r} snapshot_id {chain.snapshot_id!r} "
                f"does not match snapshot {sid!r}"
            )
    for m in pkg.memberships:
        if m.snapshot_id != sid:
            errors.append(
                f"membership {m.chain_id!r}/{m.alarm_id!r} is not scoped to {sid!r}"
            )


def _check_referential_integrity(pkg: MockSnapshotPackage, errors: list[str]) -> None:
    alarm_ids = {a.alarm_id for a in pkg.alarms}
    chain_ids = {c.chain_id for c in pkg.chains}

    if len(alarm_ids) != len(pkg.alarms):
        errors.append("duplicate alarm_id values in alarms[]")
    if len(chain_ids) != len(pkg.chains):
        errors.append("duplicate chain_id values in chains[]")

    for m in pkg.memberships:
        if m.alarm_id not in alarm_ids:
            errors.append(f"membership references unknown alarm_id {m.alarm_id!r}")
        if m.chain_id not in chain_ids:
            errors.append(f"membership references unknown chain_id {m.chain_id!r}")

    counted: dict[str, int] = {}
    for m in pkg.memberships:
        counted[m.chain_id] = counted.get(m.chain_id, 0) + 1
    for chain in pkg.chains:
        actual = counted.get(chain.chain_id, 0)
        if actual != chain.member_count:
            errors.append(
                f"chain {chain.chain_id!r} declares member_count={chain.member_count} "
                f"but {actual} membership row(s) present"
            )


def _check_topology(pkg: MockSnapshotPackage, errors: list[str]) -> None:
    for edge in pkg.topology.edges:
        # ADR-MOCK-0005: undirected adjacency must not become a directed claim.
        if edge.relation_type is RelationType.IP_ADJACENCY and edge.directed:
            errors.append(
                f"edge {edge.edge_id!r}: IP_ADJACENCY cannot be directed=True; "
                "the source provides undirected adjacency only"
            )
        if edge.source_resource_id == edge.target_resource_id:
            errors.append(f"edge {edge.edge_id!r} is a self-loop")

    edge_ids = [e.edge_id for e in pkg.topology.edges]
    if len(set(edge_ids)) != len(edge_ids):
        errors.append("duplicate edge_id values in topology.edges[]")

    for fd in pkg.topology.failure_domains:
        if len(fd.members) < 1:
            errors.append(f"failure domain {fd.failure_domain_id!r} has no members")
        if len(set(fd.members)) != len(fd.members):
            errors.append(
                f"failure domain {fd.failure_domain_id!r} has duplicate members"
            )

    for path in pkg.topology.active_paths:
        if len(path.nodes) < 2:
            errors.append(f"active path {path.path_id!r} needs at least two nodes")


def _check_mappings(pkg: MockSnapshotPackage, errors: list[str]) -> None:
    """Mapping must fail closed; fuzzy matching is forbidden (ADR-MOCK-0005)."""
    for mp in pkg.topology.mappings:
        resolved = mp.mapping_status in (
            MappingStatus.EXACT,
            MappingStatus.VERIFIED_ALIAS,
            MappingStatus.STRUCTURED_FIELD_UNIQUE,
        )
        if resolved and not mp.resource_id:
            errors.append(
                f"mapping for alarm {mp.alarm_id!r} claims "
                f"{mp.mapping_status.value} without a resource_id"
            )
        if not resolved and mp.resource_id:
            errors.append(
                f"mapping for alarm {mp.alarm_id!r} is {mp.mapping_status.value} "
                "but still carries a resource_id"
            )
        if mp.mapping_status is MappingStatus.UNMAPPED:
            if mp.mapping_method is not MappingMethod.NONE:
                errors.append(
                    f"mapping for alarm {mp.alarm_id!r} is UNMAPPED but "
                    f"mapping_method={mp.mapping_method.value}"
                )
        elif resolved and mp.mapping_method is MappingMethod.NONE:
            errors.append(
                f"mapping for alarm {mp.alarm_id!r} claims "
                f"{mp.mapping_status.value} with mapping_method=NONE"
            )
        if (
            mp.mapping_status is MappingStatus.STRUCTURED_FIELD_UNIQUE
            and mp.mapping_method is not MappingMethod.STRUCTURED_FIELD_EXACT
        ):
            errors.append(
                f"mapping for alarm {mp.alarm_id!r} claims "
                "STRUCTURED_FIELD_UNIQUE without "
                "mapping_method=STRUCTURED_FIELD_EXACT"
            )
        if (
            mp.mapping_method is MappingMethod.STRUCTURED_FIELD_EXACT
            and mp.mapping_status is not MappingStatus.STRUCTURED_FIELD_UNIQUE
        ):
            errors.append(
                f"mapping for alarm {mp.alarm_id!r} uses "
                "STRUCTURED_FIELD_EXACT without "
                "mapping_status=STRUCTURED_FIELD_UNIQUE"
            )


def _check_pair_metadata(pkg: MockSnapshotPackage, errors: list[str]) -> None:
    """``M_pair`` typing rules (ADR-0002, ADR-0008, D1 addendum)."""
    sm = pkg.system_metadata
    batch_refs = {b.batch_id for b in sm.pair_metadata_batches}
    if len(batch_refs) != len(sm.pair_metadata_batches):
        errors.append("duplicate batch_id values in system_metadata.pair_metadata_batches[]")

    known_attribute_refs = {
        cfg.attribute_ref for cfg in sm.attribute_configs if cfg.attribute_ref
    }

    for pair in sm.pair_metadata:
        label = f"pair metadata {pair.alarm_id_a!r}/{pair.alarm_id_b!r}"

        if pair.alarm_id_a == pair.alarm_id_b:
            errors.append(f"{label}: a pair cannot reference the same alarm twice")

        # A raw score is uninterpretable without knowing which Attribute made it.
        if pair.raw_score is not None and not pair.attribute_ref:
            errors.append(f"{label}: raw_score requires an attribute_ref")

        if (
            pair.attribute_ref
            and known_attribute_refs
            and pair.attribute_ref not in known_attribute_refs
        ):
            errors.append(
                f"{label}: attribute_ref {pair.attribute_ref!r} has no matching "
                "AttributeConfig"
            )

        evaluated = pair.system_pair_status is SystemPairStatus.EVALUATED
        if not evaluated:
            # NOT_EVALUATED / UNKNOWN carry no score to interpret.
            if pair.raw_score is not None:
                errors.append(
                    f"{label}: system_pair_status="
                    f"{pair.system_pair_status.value} cannot carry a raw_score"
                )
            if pair.system_semantic is not None:
                errors.append(
                    f"{label}: system_pair_status="
                    f"{pair.system_pair_status.value} cannot carry a system_semantic"
                )

        if pair.system_semantic is SystemSemantic.VETO:
            # The raw sentinel is preserved, never replaced by a null score.
            if pair.raw_score != TIMEWINDOW_VETO_SENTINEL:
                errors.append(
                    f"{label}: system_semantic=VETO must preserve "
                    f"raw_score={TIMEWINDOW_VETO_SENTINEL}, got {pair.raw_score!r}"
                )
            if pair.veto is False:
                errors.append(f"{label}: system_semantic=VETO conflicts with veto=False")
        elif pair.veto is True:
            errors.append(
                f"{label}: veto=True requires system_semantic=VETO"
            )


def _check_synthetic_provenance(pkg: MockSnapshotPackage, errors: list[str]) -> None:
    """Synthetic objects need deterministic generation metadata (ADR-0026)."""

    def check(obj: object, label: str) -> None:
        kind = getattr(obj, "source_kind", None)
        if kind is not SourceKind.SYNTHETIC_TEST:
            return
        gen = getattr(obj, "generation", None)
        if gen is None:
            errors.append(f"{label} is SYNTHETIC_TEST but has no generation metadata")
            return
        if not gen.scenario_id:
            errors.append(f"{label} generation metadata lacks scenario_id")
        if not gen.generation_rule:
            errors.append(f"{label} generation metadata lacks generation_rule")
        if not gen.generator_version:
            errors.append(f"{label} generation metadata lacks generator_version")

    for node in pkg.topology.nodes:
        check(node, f"topology node {node.resource_id!r}")
    for edge in pkg.topology.edges:
        check(edge, f"topology edge {edge.edge_id!r}")
    for fd in pkg.topology.failure_domains:
        check(fd, f"failure domain {fd.failure_domain_id!r}")
    for path in pkg.topology.active_paths:
        check(path, f"active path {path.path_id!r}")
    for ctx in pkg.operational_context:
        check(ctx, f"operational context {ctx.context_id!r}")


def validate_package(pkg: MockSnapshotPackage) -> ValidationResult:
    """Validate a package against Input Contract v1."""
    errors: list[str] = []
    _check_version(pkg, errors)
    _check_snapshot(pkg, errors)
    _check_snapshot_scoping(pkg, errors)
    _check_referential_integrity(pkg, errors)
    _check_topology(pkg, errors)
    _check_mappings(pkg, errors)
    _check_pair_metadata(pkg, errors)
    _check_synthetic_provenance(pkg, errors)
    return ValidationResult(errors=errors)


def is_validation_eligible(source_kind: SourceKind) -> bool:
    """ADR-0010 stage-1 source-kind gate.

    Only ``REAL_LIVE`` / ``REAL_EXPORT_REPLAY`` may proceed toward validation,
    and passing this gate does not by itself make a source independent.
    """
    return source_kind in VALIDATION_ELIGIBLE_SOURCE_KINDS
