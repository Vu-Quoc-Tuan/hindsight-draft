"""H_domain failure-domain hyperedge adapter (ADR-0011, ADR-0032).

Failure-domain records contain resource sets.  This adapter resolves them to
chain alarm membership for WHY/candidate generation while deliberately exposing
no pair score and performing no clique projection.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedPackage
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


def failure_domains_for_chain(
    package: IngestedPackage, chain_id: str
) -> tuple[FailureDomainEvidence, ...]:
    if chain_id not in package.chains:
        raise KeyError(f"unknown chain_id {chain_id!r}")
    resolver = ResourceResolver.from_package(package)
    alarm_to_resource = {
        alarm_id: resolver.resource_of(alarm_id)
        for alarm_id in package.members_of(chain_id)
    }
    results: list[FailureDomainEvidence] = []
    for record in package.topology.get("failure_domains") or ():
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
        results.append(
            FailureDomainEvidence(
                failure_domain_id=str(record.get("failure_domain_id", "")),
                domain_type=str(record.get("domain_type", "UNKNOWN")),
                member_alarm_ids=alarm_members,
                member_resource_ids=frozenset(
                    resource
                    for resource in resource_members
                    if resource in set(alarm_to_resource.values())
                ),
                source_id=record.get("source_id"),
                source_kind=record.get("source_kind"),
                provenance_class=provenance_class,
                provenance_subtype=provenance_subtype,
                quality_status=str(record.get("quality_status", "UNKNOWN")),
            )
        )
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
