"""Snapshot package assembly.

The snapshot is the processing boundary (ADR-0005), so the mock emits complete
packages rather than loose records. Two entry points:

- :func:`build_real_replay_snapshot` — replays the real alarm export, optionally
  with real topoIP adjacency and exact-identity mapping.
- :func:`build_golden_snapshot` — replays the Golden 2214039 observed facts, whose
  topology mapping stays UNMAPPED against the current topoIP export.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..config import MockConfig
from ..contract import (
    AlarmResourceMapping,
    Chain,
    MappingMethod,
    MappingStatus,
    MockSnapshotPackage,
    ProvenanceClass,
    ProvenanceManifest,
    Snapshot,
    SnapshotStatus,
    SourceKind,
    SourceRecord,
    SystemMetadata,
    Topology,
)
from ..fixtures.golden import GoldenFixture, load_golden_fixture
from ..loaders.alarm_csv import AlarmCsvLoader
from ..loaders.topology_ip_csv import TopoIPLoader
from ..normalize.alarms import build_chains, normalize_alarm
from ..normalize.bounded_subgraph import extract_bounded_ip_subgraph
from ..normalize.resource_mapping import ResourceMapper
from ..normalize.topology import TOPOLOGY_LAYER_IP, normalize_topo_ip

SOURCE_NAME = "nocpro-mock"

#: Capabilities the real exports cannot support; declared so downstream cannot
#: mistake absence for a negative finding (docs 06).
TOPO_IP_UNAVAILABLE_CAPABILITIES = (
    "DIRECTED_DEPENDENCY",
    "SHARED_ANCESTOR",
    "ACTIVE_PATH",
    "ROUTING_PATH",
    "DOMINATOR",
    "FAILURE_DOMAIN",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_real_replay_snapshot(
    *,
    alarm_csv_path: str | Path,
    config: MockConfig,
    snapshot_id: str,
    snapshot_version: str = "1",
    snapshot_time: datetime | None = None,
    topo_ip_path: str | Path | None = None,
    chain_ids: set[str] | None = None,
    limit: int | None = None,
    bounded_subgraph: bool = True,
) -> MockSnapshotPackage:
    """Replay the real alarm export as one canonical snapshot.

    ``chain_ids`` / ``limit`` subset the export for fast iteration; the resulting
    snapshot is still internally consistent.
    """
    config.assert_policy_safe()
    reference_time = snapshot_time or datetime.now(timezone.utc).replace(tzinfo=None)
    source_kind = SourceKind.REAL_EXPORT_REPLAY

    loader = AlarmCsvLoader(
        alarm_csv_path, future_year_threshold=config.future_timestamp_year_threshold
    )
    records = []
    for record in loader.iter_records():
        if chain_ids is not None and record.chaining_id not in chain_ids:
            continue
        records.append(record)
        if limit is not None and len(records) >= limit:
            break

    alarms = tuple(
        normalize_alarm(r, snapshot_id=snapshot_id, source_kind=source_kind)
        for r in records
    )
    chains, memberships = build_chains(
        records, snapshot_id=snapshot_id, source_kind=source_kind
    )

    sources = [
        SourceRecord(
            source_id="alarm_data_csv",
            source_kind=source_kind,
            file_path=str(alarm_csv_path),
            record_count=len(records),
        )
    ]

    topology = Topology()
    unavailable: list[str] = []

    if topo_ip_path is not None and config.topo_ip_enabled:
        all_relations = TopoIPLoader(topo_ip_path).load()
        if bounded_subgraph:
            seed_codes = {a.device_code for a in alarms if a.device_code}
            relations = extract_bounded_ip_subgraph(all_relations, seed_codes, max_hops=1)
        else:
            relations = all_relations
        nodes, edges = normalize_topo_ip(
            relations,
            source_id="topo_ip_csv",
            reference_time=reference_time,
            freshness_pass_max_age_seconds=(
                config.topology_freshness_pass_max_age_seconds
            ),
        )
        mapper = ResourceMapper(
            {n.resource_id for n in nodes},
            topology_layer=TOPOLOGY_LAYER_IP,
        )
        mappings = tuple(
            mapper.map_alarm(
                a.alarm_id, device_code=a.device_code, node_reference=a.node_reference
            )
            for a in alarms
        )
        topology = Topology(nodes=nodes, edges=edges, mappings=mappings)
        sources.append(
            SourceRecord(
                source_id="topo_ip_csv",
                source_kind=source_kind,
                file_path=str(topo_ip_path),
                record_count=len(relations),
            )
        )
        unavailable.extend(TOPO_IP_UNAVAILABLE_CAPABILITIES)
    else:
        unavailable.append("TOPOLOGY_NOT_LOADED")

    if not config.topo_it_enabled:
        unavailable.append(f"TOPO_IT ({config.topo_it_disabled_reason})")

    return MockSnapshotPackage(
        snapshot=Snapshot(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            snapshot_time=reference_time.isoformat(),
            status=SnapshotStatus.COMPLETE,
            source=SOURCE_NAME,
            source_kind=source_kind,
            produced_at=_now_iso(),
            config_version=config.config_version,
        ),
        alarms=alarms,
        chains=chains,
        memberships=memberships,
        # The export carries no per-pair scores or executed attribute config.
        system_metadata=SystemMetadata(),
        topology=topology,
        provenance_manifest=ProvenanceManifest(
            sources=tuple(sources),
            config_version=config.config_version,
            generator_version=config.generator_version,
            unavailable_capabilities=tuple(unavailable),
            notes=(
                "Observed chaining_id partition replayed as-is; no re-clustering.",
                "cah.chaining_explain and is_root_alarm are empty in this export "
                "and are not fabricated.",
            ),
        ),
    )


def build_golden_snapshot(
    *,
    config: MockConfig,
    snapshot_id: str = "snapshot_golden_2214039",
    snapshot_version: str = "1",
    snapshot_time: datetime | None = None,
    fixture: GoldenFixture | None = None,
    topo_ip_device_codes: set[str] | None = None,
) -> MockSnapshotPackage:
    """Replay the Golden fixture's observed facts.

    Alarm-level rows are not part of the fixture, so the chain is emitted with
    its observed ``member_count`` and no synthesized member alarms. Topology
    mapping is reported UNMAPPED because the current topoIP export contains no
    exact match for the DEA resources.
    """
    config.assert_policy_safe()
    golden = fixture or load_golden_fixture()
    reference_time = snapshot_time or datetime.now(timezone.utc).replace(tzinfo=None)

    chain = Chain(
        chain_id=golden.chain_id,
        snapshot_id=snapshot_id,
        member_count=0,
        source_kind=golden.source_kind,
        provenance_class=ProvenanceClass.SYSTEM_FACT,
        event_span_seconds=golden.event_span_seconds,
    )

    known: set[str] = topo_ip_device_codes or set()
    mapper = ResourceMapper(known, topology_layer=TOPOLOGY_LAYER_IP)
    golden_resources = ("DEHL01", "DEHT01", "HLC9102DEA01", "HHT9603DEA01")
    mappings: list[AlarmResourceMapping] = []
    for resource in golden_resources:
        resource_id, status, method, confidence = mapper.map_identifier(resource)
        mappings.append(
            AlarmResourceMapping(
                # No member alarm IDs are sourced; the fixture-scoped resource
                # identity is used as the mapping subject.
                alarm_id=f"{golden.fixture_id}:{resource}",
                resource_id=resource_id,
                mapping_status=status if resource_id else MappingStatus.UNMAPPED,
                mapping_method=method if resource_id else MappingMethod.NONE,
                mapping_confidence=confidence if resource_id else None,
                topology_layer=TOPOLOGY_LAYER_IP,
            )
        )

    return MockSnapshotPackage(
        snapshot=Snapshot(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            snapshot_time=reference_time.isoformat(),
            status=SnapshotStatus.COMPLETE,
            source=SOURCE_NAME,
            source_kind=golden.source_kind,
            produced_at=_now_iso(),
            config_version=config.config_version,
        ),
        chains=(chain,),
        system_metadata=golden.system_metadata,
        topology=Topology(mappings=tuple(mappings)),
        provenance_manifest=ProvenanceManifest(
            sources=(
                SourceRecord(
                    source_id=golden.fixture_id,
                    source_kind=golden.source_kind,
                    record_count=golden.member_count,
                    notes=golden.notes,
                ),
            ),
            config_version=config.config_version,
            generator_version=config.generator_version,
            unavailable_capabilities=(
                "EXACT_PAIR_METADATA",
                "EXECUTED_ATTRIBUTE_CONFIG",
                *TOPO_IP_UNAVAILABLE_CAPABILITIES,
            ),
            notes=(
                f"Observed member_count={golden.member_count}; member alarm rows "
                "are not present in the current export and are not synthesized.",
                "Aggregate characteristics are not expanded into pair edges.",
                "Not an over-merge ground truth.",
            ),
        ),
    )
