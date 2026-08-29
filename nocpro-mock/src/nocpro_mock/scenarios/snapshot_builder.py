"""Build synthetic snapshot packages for history/evolution sequences.

Each snapshot is an ordinary :class:`MockSnapshotPackage`. Sequencing lives in
the manifest, so nothing here knows it is part of a sequence beyond stamping the
scenario provenance.

Snapshots stay ``source_kind=SYNTHETIC_TEST``: the delivery role
(``HISTORY_BOOTSTRAP``) is a sequence concern and must not overwrite provenance.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..contract import (
    Alarm,
    Chain,
    ChainMembership,
    GenerationMetadata,
    MockSnapshotPackage,
    ProvenanceClass,
    ProvenanceManifest,
    Snapshot,
    SnapshotStatus,
    SourceKind,
    SourceRecord,
)

#: Fixed epoch so generated fixtures are byte-stable across runs.
SEQUENCE_EPOCH = datetime(2026, 1, 1, 0, 0, 0)


def build_synthetic_snapshot(
    *,
    scenario_id: str,
    seed: int,
    generator_version: str,
    snapshot_index: int,
    chains: dict[str, list[str]],
    alarm_families: dict[str, str] | None = None,
    snapshot_interval_seconds: int = 60,
    generation_rule: str = "synthetic snapshot sequence member",
) -> MockSnapshotPackage:
    """Build one synthetic snapshot from a ``chain_id -> [alarm_id]`` mapping.

    ``alarm_families`` optionally tags each alarm with a family, which is what a
    history scenario needs so downstream can compute family-level co-grouping.
    """
    snapshot_id = f"{scenario_id}:snapshot_{snapshot_index:03d}"
    snapshot_time = SEQUENCE_EPOCH + timedelta(
        seconds=snapshot_index * snapshot_interval_seconds
    )
    families = alarm_families or {}

    generation = GenerationMetadata(
        scenario_id=scenario_id,
        seed=seed,
        generator_version=generator_version,
        generation_rule=generation_rule,
    )

    alarms: list[Alarm] = []
    chain_records: list[Chain] = []
    memberships: list[ChainMembership] = []

    for chain_id, members in chains.items():
        if len(set(members)) != len(members):
            raise ValueError(f"chain {chain_id!r} lists an alarm twice")
        for offset, alarm_id in enumerate(members):
            start = snapshot_time + timedelta(seconds=offset)
            raw = {
                "cah.id": alarm_id,
                "chaining_id": chain_id,
                "cah.start_time": start.isoformat(),
                "device_code": alarm_id,
            }
            family = families.get(alarm_id)
            if family:
                raw["alarm_name"] = family
            alarms.append(
                Alarm(
                    alarm_id=alarm_id,
                    snapshot_id=snapshot_id,
                    source_kind=SourceKind.SYNTHETIC_TEST,
                    provenance_class=ProvenanceClass.SYSTEM_FACT,
                    raw=raw,
                    raw_start_time=start.isoformat(),
                    canonical_start_time=start.isoformat(),
                    alarm_name=family,
                    device_code=alarm_id,
                )
            )
            memberships.append(
                ChainMembership(
                    chain_id=chain_id,
                    alarm_id=alarm_id,
                    snapshot_id=snapshot_id,
                    source_kind=SourceKind.SYNTHETIC_TEST,
                )
            )

        starts = [
            snapshot_time + timedelta(seconds=i) for i in range(len(members))
        ]
        span = int((max(starts) - min(starts)).total_seconds()) if starts else None
        chain_records.append(
            Chain(
                chain_id=chain_id,
                snapshot_id=snapshot_id,
                member_count=len(members),
                source_kind=SourceKind.SYNTHETIC_TEST,
                provenance_class=ProvenanceClass.SYSTEM_FACT,
                event_span_seconds=span,
            )
        )

    return MockSnapshotPackage(
        snapshot=Snapshot(
            snapshot_id=snapshot_id,
            snapshot_version=f"{snapshot_index + 1}",
            snapshot_time=snapshot_time.isoformat(),
            status=SnapshotStatus.COMPLETE,
            source="nocpro-mock",
            # Synthetic stays synthetic regardless of delivery role.
            source_kind=SourceKind.SYNTHETIC_TEST,
            produced_at=snapshot_time.isoformat(),
        ),
        alarms=tuple(alarms),
        chains=tuple(chain_records),
        memberships=tuple(memberships),
        provenance_manifest=ProvenanceManifest(
            sources=(
                SourceRecord(
                    source_id=scenario_id,
                    source_kind=SourceKind.SYNTHETIC_TEST,
                    record_count=len(alarms),
                    notes=(generation.generation_rule,),
                ),
            ),
            generator_version=generator_version,
            notes=(
                f"scenario_id={scenario_id}",
                f"seed={seed}",
                "Synthetic snapshot; cannot be used as real validation.",
            ),
        ),
    )
