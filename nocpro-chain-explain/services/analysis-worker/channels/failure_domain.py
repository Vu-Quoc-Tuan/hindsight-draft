"""H_domain failure-domain hyperedge adapter (ADR-0011, ADR-0032).

Failure-domain records contain resource sets.  This adapter resolves them to
chain alarm membership for WHY/candidate generation while deliberately exposing
no pair score and performing no clique projection.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedPackage
from libs.contracts.topology_mapping import RESOLVED_STATUSES
from libs.provenance import ProvenanceClass, ProvenanceSubtype

from .dependency import ResourceResolver


@dataclass(frozen=True)
class FailureDomainEvidence:
    failure_domain_id: str
    domain_type: str
    member_alarm_ids: frozenset[str]
    member_resource_ids: frozenset[str]
    source_id: str | None
    source_kind: str | None
    provenance_class: ProvenanceClass
    provenance_subtype: ProvenanceSubtype | None
    quality_status: str
    source_version: str | None = None

    @property
    def eligible_for_candidate(self) -> bool:
        """Explicitly failed mappings/records may be shown but cannot propose a cut."""
        if self.quality_status.upper() == "FAIL":
            return False
        # A shared-storage source relation is context for distinct instances.
        # Repeated alarms mapped to one instance do not form a multi-resource
        # block and must not become an Audit candidate by alarm-count alone.
        if (
            self.domain_type == "SHARED_STORAGE_CONTEXT"
            and len(self.member_resource_ids) < 2
        ):
            return False
        return True


def _topology_storage_domains(package: IngestedPackage) -> tuple[dict, ...]:
    """Derive shared-resource context from persisted storage relation rows.

    This records the source fact "these instances link to the same storage"
    without claiming that storage caused an alarm or treating the relation as a
    directed dependency edge for Dep_hop.
    """
    by_storage: dict[str, set[str]] = {}
    traces: dict[str, set[tuple[str, str, str, str, str | None]]] = {}
    qualities: dict[str, set[str]] = {}
    invalid_traces: set[str] = set()
    for edge in package.topology.get("edges") or ():
        if (
            not isinstance(edge, dict)
            or edge.get("relation_type") != "INSTANCE_LINKS_STORAGE"
        ):
            continue
        instance_id = edge.get("source_resource_id")
        storage_id = edge.get("target_resource_id")
        if (
            not isinstance(instance_id, str)
            or not instance_id
            or not isinstance(storage_id, str)
            or not storage_id
        ):
            continue
        raw_quality = edge.get("quality_status", "UNKNOWN")
        quality = getattr(raw_quality, "value", raw_quality)
        quality = str(quality or "UNKNOWN").upper()
        if quality not in {"PASS", "FAIL", "UNKNOWN"}:
            invalid_traces.add(storage_id)
            continue
        by_storage.setdefault(storage_id, set()).add(instance_id)
        qualities.setdefault(storage_id, set()).add(quality)
        source_id = edge.get("source_id")
        version = edge.get("source_version")
        kind = edge.get("source_kind")
        provenance = edge.get("provenance_class")
        subtype = edge.get("provenance_subtype")
        if not all(
            isinstance(value, str) and value
            for value in (source_id, version, kind, provenance)
        ):
            invalid_traces.add(storage_id)
            continue
        if provenance == ProvenanceClass.EXTERNAL_OPERATIONAL.value and not (
            isinstance(subtype, str) and subtype
        ):
            invalid_traces.add(storage_id)
            continue
        traces.setdefault(storage_id, set()).add(
            (source_id, version, kind, provenance, subtype)
        )

    result = []
    for storage_id, instances in sorted(by_storage.items()):
        source_traces = traces.get(storage_id, set())
        if (
            len(instances) < 2
            or storage_id in invalid_traces
            or len(source_traces) != 1
        ):
            continue
        (
            source_id,
            source_version,
            source_kind,
            provenance_class,
            provenance_subtype,
        ) = next(iter(source_traces))
        profile_id = package.topology.get("profile_id")
        source_ref = (
            f"{profile_id}/{source_id}"
            if isinstance(profile_id, str) and profile_id
            else source_id
        )
        result.append({
            "failure_domain_id": f"SHARED_STORAGE:{source_ref}:{storage_id}",
            "domain_type": "SHARED_STORAGE_CONTEXT",
            "members": sorted(instances),
            "source_id": source_id,
            "source_kind": source_kind,
            "source_version": source_version,
            "provenance_class": provenance_class,
            "provenance_subtype": provenance_subtype,
            "quality_status": (
                "FAIL"
                if "FAIL" in qualities.get(storage_id, set())
                else "PASS"
                if qualities.get(storage_id) == {"PASS"}
                else "UNKNOWN"
            ),
        })
    return tuple(result)


def _source_context_alarm_resources(package: IngestedPackage) -> dict[str, str]:
    """Resolve source-field mappings only for explicitly labelled context.

    ``STRUCTURED_FIELD_UNIQUE`` is useful for following a topoIT source row to a
    node, but it is not an operational alarm-resource mapping. This helper is
    used only for derived shared-storage context; the general resolver remains
    strict for explicit failure domains and ``Dep_hop``.
    """
    rows_by_alarm: dict[str, list[dict]] = {}
    for row in package.topology.get("mappings") or ():
        if not isinstance(row, dict):
            continue
        alarm_id = row.get("alarm_id")
        if isinstance(alarm_id, str) and alarm_id:
            rows_by_alarm.setdefault(alarm_id, []).append(row)

    def token(value):
        return getattr(value, "value", value)

    resolved: dict[str, str] = {}
    allowed_statuses = set(RESOLVED_STATUSES) | {"STRUCTURED_FIELD_UNIQUE"}
    for alarm_id, rows in rows_by_alarm.items():
        statuses = {token(row.get("mapping_status")) for row in rows}
        if len(statuses) != 1 or not statuses <= allowed_statuses:
            continue
        signatures = {
            tuple(sorted(
                (str(key), token(value))
                for key, value in row.items()
                if key != "alarm_id"
            ))
            for row in rows
        }
        if len(signatures) != 1:
            continue
        status = next(iter(statuses))
        method = token(rows[0].get("mapping_method"))
        if (
            status == "STRUCTURED_FIELD_UNIQUE"
            and method != "STRUCTURED_FIELD_EXACT"
        ):
            continue
        resource_id = rows[0].get("resource_id")
        if isinstance(resource_id, str) and resource_id:
            resolved[alarm_id] = resource_id
    return resolved


def failure_domains_for_chain(
    package: IngestedPackage, chain_id: str
) -> tuple[FailureDomainEvidence, ...]:
    if chain_id not in package.chains:
        raise KeyError(f"unknown chain_id {chain_id!r}")
    chain_alarm_ids = set(package.members_of(chain_id))
    strict_resolver = ResourceResolver.from_package(package)
    strict_alarm_to_resource = {
        alarm_id: strict_resolver.resource_of(alarm_id)
        for alarm_id in chain_alarm_ids
    }
    context_resolver = _source_context_alarm_resources(package)
    context_alarm_to_resource = {
        alarm_id: context_resolver.get(alarm_id)
        for alarm_id in chain_alarm_ids
    }
    results: list[FailureDomainEvidence] = []

    def append_records(records: tuple[dict, ...], alarm_to_resource: dict[str, str | None]):
        for record in records:
            resource_members = frozenset(
                str(resource) for resource in (record.get("members") or ()) if resource
            )
            alarm_members = frozenset(
                alarm_id
                for alarm_id, resource_id in alarm_to_resource.items()
                if resource_id is not None and resource_id in resource_members
            )
            if not alarm_members:
                continue
            try:
                provenance_class = ProvenanceClass(
                    record.get(
                        "provenance_class", ProvenanceClass.EXTERNAL_OPERATIONAL.value
                    )
                )
                raw_subtype = record.get("provenance_subtype")
                provenance_subtype = (
                    ProvenanceSubtype(raw_subtype)
                    if raw_subtype is not None
                    else ProvenanceSubtype.TOPOLOGY_EXTERNAL
                    if provenance_class is ProvenanceClass.EXTERNAL_OPERATIONAL
                    else None
                )
            except ValueError:
                # Invalid provenance cannot be repaired locally; fail closed by
                # omitting this domain from normalized explanation/candidates.
                continue
            resolved_resources = {
                resource for resource in alarm_to_resource.values() if resource
            }
            results.append(
                FailureDomainEvidence(
                    failure_domain_id=str(record.get("failure_domain_id", "")),
                    domain_type=str(record.get("domain_type", "UNKNOWN")),
                    member_alarm_ids=alarm_members,
                    member_resource_ids=frozenset(
                        resource for resource in resource_members
                        if resource in resolved_resources
                    ),
                    source_id=record.get("source_id"),
                    source_kind=record.get("source_kind"),
                    provenance_class=provenance_class,
                    provenance_subtype=provenance_subtype,
                    quality_status=(
                        str(record.get("quality_status") or "UNKNOWN").upper()
                    ),
                    source_version=(
                        str(record["source_version"])
                        if record.get("source_version") is not None
                        else None
                    ),
                )
            )

    # Explicit SRLG/power/etc. records require the strict mapping contract.
    append_records(
        tuple(package.topology.get("failure_domains") or ()),
        strict_alarm_to_resource,
    )
    # A unique source-field match is accepted only for the weaker derived
    # storage context, never promoted to an explicit failure-domain claim.
    append_records(_topology_storage_domains(package), context_alarm_to_resource)
    return tuple(
        sorted(results, key=lambda item: (item.domain_type, item.failure_domain_id))
    )


def failure_domains_for_member(
    package: IngestedPackage, chain_id: str, alarm_id: str
) -> tuple[FailureDomainEvidence, ...]:
    if alarm_id not in set(package.members_of(chain_id)):
        raise KeyError(f"alarm {alarm_id!r} is not a member of chain {chain_id!r}")
    return tuple(
        domain
        for domain in failure_domains_for_chain(package, chain_id)
        if alarm_id in domain.member_alarm_ids
    )
