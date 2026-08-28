"""Deterministic candidate cut generation (§6, ADR-0019).

Four sources only. No new community detection is run here -- that would be
"Louvain a second time" over evidence the module itself produced:

    Entity (categorical)     partition by dominant predicate value
    Dependency pair graph    connected components after threshold theta_dep
    Failure-domain H_domain  each hyperedge is one candidate block
    Descriptor               extents of top non-redundant IDENTITY rules

Candidate cuts are these blocks plus their pairwise union/difference.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations

from descriptor.mining import Descriptor
from descriptor.predicates import Predicate, read_field
from libs.contracts import IngestedAlarm


class CandidateSource(str, Enum):
    ENTITY = "ENTITY"
    DEPENDENCY = "DEPENDENCY"
    FAILURE_DOMAIN = "FAILURE_DOMAIN"
    DESCRIPTOR = "DESCRIPTOR"
    #: Union/difference of two base blocks.
    DERIVED = "DERIVED"


@dataclass(frozen=True)
class Candidate:
    """One candidate block ``S`` with traceable provenance.

    ``label`` states where the cut came from, which is what lets the audit
    answer "cut comes from where" instead of presenting an opaque partition.
    """

    source: CandidateSource
    members: frozenset[str]
    label: str


def entity_candidates(
    alarms: list[IngestedAlarm],
    *,
    fields: tuple[str, ...] = ("node_reference", "device_code", "location_code"),
) -> list[Candidate]:
    """Partition by dominant predicate value for each whitelisted field."""
    candidates: list[Candidate] = []
    for field in fields:
        groups: dict[str, set[str]] = {}
        for alarm in alarms:
            value = read_field(alarm, field)
            if value is not None:
                groups.setdefault(value, set()).add(alarm.alarm_id)
        for value, members in sorted(groups.items()):
            if len(members) < 2:
                # A singleton value cannot itself be a two-sided cut candidate.
                continue
            candidates.append(
                Candidate(
                    source=CandidateSource.ENTITY,
                    members=frozenset(members),
                    label=f"{field}={value}",
                )
            )
    return candidates


def dependency_candidates(
    members: list[str],
    edges: list[tuple[str, str, float]],
    *,
    theta_dep: float = 0.5,
) -> list[Candidate]:
    """Connected components of the dependency pair graph above ``theta_dep``.

    Union-find on supported edges only, per the deterministic table.
    """
    parent: dict[str, str] = {m: m for m in members}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b, weight in edges:
        if weight >= theta_dep and a in parent and b in parent:
            union(a, b)

    grouped: dict[str, set[str]] = {}
    for node in members:
        grouped.setdefault(find(node), set()).add(node)

    return [
        Candidate(
            source=CandidateSource.DEPENDENCY,
            members=frozenset(component),
            label=f"dependency component ({len(component)} members)",
        )
        for component in grouped.values()
        if len(component) >= 2
    ]


def failure_domain_candidates(
    domains: list[tuple[str, frozenset[str]]],
) -> list[Candidate]:
    """One candidate block per failure-domain hyperedge.

    Each hyperedge is used whole, never clique-projected into pair edges
    (ADR-0011); it simply proposes a block.
    """
    return [
        Candidate(
            source=CandidateSource.FAILURE_DOMAIN,
            members=frozenset(members),
            label=f"failure domain {domain_id}",
        )
        for domain_id, members in domains
        if len(members) >= 2
    ]


def descriptor_candidates(
    descriptors: tuple[Descriptor, ...], index, *, top_k: int = 5
) -> list[Candidate]:
    """Extents of the top non-redundant IDENTITY rules.

    ``descriptors`` is expected to already be redundancy-filtered by the mining
    step (docs 5); this function only converts extents to member sets.
    """
    candidates: list[Candidate] = []
    for descriptor in descriptors[:top_k]:
        members = frozenset(
            index.universe[i]
            for i in range(index.size)
            if descriptor.matches_alarm_bit(i)
        )
        if len(members) >= 2:
            candidates.append(
                Candidate(
                    source=CandidateSource.DESCRIPTOR,
                    members=members,
                    label=descriptor.label,
                )
            )
    return candidates


def derived_candidates(
    base: list[Candidate], *, all_members: frozenset[str]
) -> list[Candidate]:
    """Pairwise union and difference of the base blocks.

    Kept as an explicit, bounded step -- not a search -- so the set of
    candidates stays deterministic and traceable to the pair that produced it.
    """
    derived: list[Candidate] = []
    for a, b in combinations(base, 2):
        union = a.members | b.members
        if 2 <= len(union) < len(all_members):
            derived.append(
                Candidate(
                    source=CandidateSource.DERIVED,
                    members=frozenset(union),
                    label=f"({a.label}) UNION ({b.label})",
                )
            )
        diff_ab = a.members - b.members
        if len(diff_ab) >= 2:
            derived.append(
                Candidate(
                    source=CandidateSource.DERIVED,
                    members=frozenset(diff_ab),
                    label=f"({a.label}) MINUS ({b.label})",
                )
            )
        diff_ba = b.members - a.members
        if len(diff_ba) >= 2:
            derived.append(
                Candidate(
                    source=CandidateSource.DERIVED,
                    members=frozenset(diff_ba),
                    label=f"({b.label}) MINUS ({a.label})",
                )
            )
    return derived


def deduplicate_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Drop exact-duplicate member sets, keeping the first (highest-priority) label."""
    seen: set[frozenset[str]] = set()
    kept: list[Candidate] = []
    for candidate in candidates:
        if candidate.members in seen:
            continue
        seen.add(candidate.members)
        kept.append(candidate)
    return kept


def generate_candidates(
    *,
    alarms: list[IngestedAlarm],
    dependency_edges: list[tuple[str, str, float]],
    failure_domains: list[tuple[str, frozenset[str]]],
    descriptors: tuple[Descriptor, ...],
    predicate_index,
    theta_dep: float = 0.5,
    include_derived: bool = True,
) -> list[Candidate]:
    """Generate the full deterministic candidate set for one chain."""
    all_members = frozenset(a.alarm_id for a in alarms)
    member_list = sorted(all_members)

    base = (
        entity_candidates(alarms)
        + dependency_candidates(member_list, dependency_edges, theta_dep=theta_dep)
        + failure_domain_candidates(failure_domains)
        + descriptor_candidates(descriptors, predicate_index)
    )
    base = deduplicate_candidates(base)

    all_candidates = list(base)
    if include_derived:
        all_candidates.extend(
            derived_candidates(base, all_members=all_members)
        )
    return deduplicate_candidates(all_candidates)
