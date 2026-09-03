"""Build synthetic snapshot packages for history/evolution sequences.

Each snapshot is an ordinary :class:`MockSnapshotPackage`. Sequencing lives in
the manifest, so nothing here knows it is part of a sequence beyond stamping the
scenario provenance.

Snapshots stay ``source_kind=SYNTHETIC_TEST``: the delivery role
(``HISTORY_BOOTSTRAP``) is a sequence concern and must not overwrite provenance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    Topology,
)
from .schema import TopologySourceDefinition

#: Fixed epoch so generated fixtures are byte-stable across runs.
SEQUENCE_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def build_synthetic_snapshot(
    *,
    scenario_id: str,
    seed: int,
    generator_version: str,
    snapshot_index: int,
    chains: dict[str, list[str]],
    alarm_families: dict[str, str] | None = None,
    alarm_profiles: dict[str, dict[str, object]] | None = None,
    snapshot_interval_seconds: int = 60,
    generation_rule: str = "synthetic snapshot sequence member",
    topology: Topology | None = None,
    topology_source: TopologySourceDefinition | None = None,
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
    profiles = alarm_profiles or {}
    supplied_topology = topology or Topology()
    topology_records = (
        *supplied_topology.nodes,
        *supplied_topology.edges,
        *supplied_topology.failure_domains,
        *supplied_topology.active_paths,
    )
    if topology_records and topology_source is None:
        raise ValueError("topology records require an explicit topology_source")
    if topology_source is not None:
        expected_identity = (
            topology_source.source_id,
            topology_source.source_version,
        )
        for record in topology_records:
            actual_identity = (
                getattr(record, "source_id", None),
                getattr(record, "source_version", None),
            )
            if actual_identity != expected_identity:
                raise ValueError(
                    "topology record source identity does not match topology_source: "
                    f"expected={expected_identity!r}, actual={actual_identity!r}"
                )
        for mapping in supplied_topology.mappings:
            if mapping.source_version != topology_source.source_version:
                raise ValueError(
                    "topology mapping source_version does not match topology_source"
                )

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
            profile = profiles.get(alarm_id, {})
            start = snapshot_time + timedelta(
                seconds=int(profile.get("start_offset_seconds", offset))
            )
            device_code = str(profile.get("device_code", alarm_id))
            node_reference = profile.get("node_reference")
            alarm_name = profile.get("alarm_name", families.get(alarm_id))
            raw = {
                "cah.id": alarm_id,
                "chaining_id": chain_id,
                "cah.start_time": start.isoformat(),
                "device_code": device_code,
            }
            if alarm_name:
                raw["alarm_name"] = str(alarm_name)
            if node_reference:
                raw["node_reference"] = str(node_reference)
            location_code = profile.get("location_code")
            if location_code:
                raw["location_code"] = str(location_code)
            remote_node = profile.get("remote_node")
            if remote_node:
                raw["remote_node"] = str(remote_node)
            alarms.append(
                Alarm(
                    alarm_id=alarm_id,
                    snapshot_id=snapshot_id,
                    source_kind=SourceKind.SYNTHETIC_TEST,
                    provenance_class=ProvenanceClass.SYSTEM_FACT,
                    raw=raw,
                    raw_start_time=start.isoformat(),
                    canonical_start_time=start.isoformat(),
                    alarm_name=str(alarm_name) if alarm_name else None,
                    device_code=device_code,
                    node_reference=(
                        str(node_reference) if node_reference else None
                    ),
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
            snapshot_time
            + timedelta(
                seconds=int(
                    profiles.get(alarm_id, {}).get("start_offset_seconds", index)
                )
            )
            for index, alarm_id in enumerate(members)
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
            topology_version=(
                topology_source.source_version if topology_source else None
            ),
        ),
        alarms=tuple(alarms),
        chains=tuple(chain_records),
        memberships=tuple(memberships),
        topology=supplied_topology,
        provenance_manifest=ProvenanceManifest(
            sources=(
                SourceRecord(
                    source_id=scenario_id,
                    source_kind=SourceKind.SYNTHETIC_TEST,
                    record_count=len(alarms),
                    notes=(generation.generation_rule,),
                ),
                *(
                    (
                        SourceRecord(
                            source_id=topology_source.source_id,
                            source_version=topology_source.source_version,
                            source_kind=SourceKind.SYNTHETIC_TEST,
                            record_count=len(topology_records),
                            notes=(
                                f"scenario_id={scenario_id}",
                                f"generator_version={generator_version}",
                                "Synthetic topology; cannot validate production.",
                            ),
                        ),
                    )
                    if topology_source
                    else ()
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
