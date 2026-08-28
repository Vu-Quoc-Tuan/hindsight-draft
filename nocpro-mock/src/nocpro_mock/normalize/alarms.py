"""Raw alarm records -> canonical contract objects.

Chains come from the observed ``chaining_id`` partition only. Nothing is
re-clustered (ADR-MOCK-0001), and singleton chains are first-class: 2,072 of the
2,824 observed chains (73.37%) have exactly one member.
"""

from __future__ import annotations

from ..contract import (
    Alarm,
    Chain,
    ChainMembership,
    ProvenanceClass,
    SourceKind,
)
from ..loaders.alarm_csv import AlarmRecord


def _iso(value: object) -> str | None:
    return value.isoformat() if value is not None else None


def normalize_alarm(
    record: AlarmRecord, *, snapshot_id: str, source_kind: SourceKind
) -> Alarm:
    """Build a contract ``Alarm``, preserving every raw column verbatim."""
    return Alarm(
        alarm_id=record.alarm_id,
        snapshot_id=snapshot_id,
        source_kind=source_kind,
        # Raw upstream observation, not downstream analysis.
        provenance_class=ProvenanceClass.SYSTEM_FACT,
        raw=dict(record.raw),
        raw_start_time=record.raw_start_time,
        raw_end_time=record.raw_end_time,
        canonical_start_time=_iso(record.canonical_start_time),
        canonical_end_time=_iso(record.canonical_end_time),
        alarm_name=record.alarm_name,
        device_code=record.device_code,
        node_reference=record.node_reference,
        severity_name=record.severity_name,
        quality_flags=record.quality_flags,
    )


def build_chains(
    records: list[AlarmRecord], *, snapshot_id: str, source_kind: SourceKind
) -> tuple[tuple[Chain, ...], tuple[ChainMembership, ...]]:
    """Replay the observed partition.

    Members keep first-seen order and chains are emitted in first-seen order, so
    output is deterministic for a given input file.
    """
    grouped: dict[str, list[AlarmRecord]] = {}
    for record in records:
        grouped.setdefault(record.chaining_id, []).append(record)

    chains: list[Chain] = []
    memberships: list[ChainMembership] = []

    for chain_id, members in grouped.items():
        starts = [m.canonical_start_time for m in members if m.canonical_start_time]
        span: int | None = None
        if len(starts) >= 2:
            span = int((max(starts) - min(starts)).total_seconds())
        elif len(starts) == 1:
            span = 0

        chains.append(
            Chain(
                chain_id=chain_id,
                snapshot_id=snapshot_id,
                member_count=len(members),
                source_kind=source_kind,
                provenance_class=ProvenanceClass.SYSTEM_FACT,
                chain_name=members[0].get("chaining_name"),
                event_span_seconds=span,
            )
        )
        for member in members:
            memberships.append(
                ChainMembership(
                    chain_id=chain_id,
                    alarm_id=member.alarm_id,
                    snapshot_id=snapshot_id,
                    source_kind=source_kind,
                )
            )

    return tuple(chains), tuple(memberships)
