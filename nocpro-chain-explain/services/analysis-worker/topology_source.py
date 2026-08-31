"""Exact topology-source and synthetic-generation provenance helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any


TOPOLOGY_SOURCE_VERSION_MISSING = "TOPOLOGY_SOURCE_VERSION_MISSING"


def _non_blank(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class TopologySourceTrace:
    """One exact, non-fabricated topology source identity and generation trace."""

    source_id: str
    source_version: str
    scenario_id: str | None
    generator_version: str | None

    @property
    def source_ref(self) -> str:
        return f"{self.source_id}@{self.source_version}"


def topology_source_trace(record: Mapping[str, Any]) -> TopologySourceTrace | None:
    """Return an exact trace, or ``None`` when source identity is incomplete."""
    source_id = _non_blank(record.get("source_id"))
    source_version = _non_blank(record.get("source_version"))
    if source_id is None or source_version is None:
        return None
    generation = record.get("generation")
    if isinstance(generation, Mapping):
        scenario_id = _non_blank(generation.get("scenario_id"))
        generator_version = _non_blank(generation.get("generator_version"))
    else:
        scenario_id = None
        generator_version = None
    return TopologySourceTrace(
        source_id=source_id,
        source_version=source_version,
        scenario_id=scenario_id,
        generator_version=generator_version,
    )


def has_missing_topology_source(records: Iterable[Mapping[str, Any]]) -> bool:
    """True when at least one relevant record lacks exact source ID/version."""
    return any(topology_source_trace(record) is None for record in records)


def consistent_topology_trace(
    records: Iterable[Mapping[str, Any]],
) -> TopologySourceTrace | None:
    """Return the single exact trace shared by a non-empty record group."""
    traces = {topology_source_trace(record) for record in records}
    return next(iter(traces)) if len(traces) == 1 and None not in traces else None
