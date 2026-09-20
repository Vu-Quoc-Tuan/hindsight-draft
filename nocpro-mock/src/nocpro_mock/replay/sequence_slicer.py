"""Time-window sequential snapshot slicer for real alarm data.

Slices real-world 30-day alarm exports (e.g. alarmIP.csv, alarmIT.csv) into
consecutive canonical MockSnapshotPackages over sliding time windows. This
produces derived replay windows for local Evolution/H/T_delay testing.  It does
not turn one export into verified upstream sequential snapshots and therefore
must never establish production Evolution validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yaml

from ..contract import (
    MockSnapshotPackage,
    ProvenanceManifest,
    QualityFlag,
    Snapshot,
    SnapshotStatus,
    SourceKind,
    SourceRecord,
    SystemMetadata,
    Topology,
    TopologyRef,
    canonical_topology_version,
    package_to_json,
)
from ..loaders.alarm_csv import AlarmCsvLoader, AlarmRecord, parse_timestamp
from ..normalize.alarms import build_chains, normalize_alarm


DERIVED_REPLAY_SOURCE = "nocpro-mock-derived-replay-slicer"


@dataclass(frozen=True)
class SlicedSequenceSummary:
    scenario_id: str
    output_dir: Path
    snapshot_count: int
    total_distinct_alarms: int
    total_distinct_chains: int
    start_time: str
    end_time: str
    step_minutes: int
    window_minutes: int



def slice_alarm_sequence(
    *,
    alarm_csv_path: str | Path,
    output_dir: str | Path,
    scenario_id: str = "real_alarm_evolution_v1",
    num_snapshots: int = 5,
    step_minutes: int = 5,
    window_minutes: int = 15,
    start_time_iso: str | None = None,
    max_chains_per_snapshot: int | None = None,
    source_kind: SourceKind = SourceKind.REAL_EXPORT_REPLAY,
    profile_id: str = "ALARM_ONLY",
    topo_ip_path: str | Path | None = None,
    topo_it_path: str | Path | None = None,
) -> SlicedSequenceSummary:
    """Slice alarms into consecutive snapshot packages and save sequence directory."""
    if profile_id not in ("ALARM_ONLY", "IP_NETWORK", "IT_SERVICES"):
        raise ValueError(
            f"Unsupported profile_id for sequence slicing: '{profile_id}'. "
            "Supported profiles are ALARM_ONLY, IP_NETWORK, and IT_SERVICES."
        )
    if num_snapshots < 1:
        raise ValueError("num_snapshots must be >= 1")
    if step_minutes < 1:
        raise ValueError("step_minutes must be >= 1")
    if window_minutes < 1:
        raise ValueError("window_minutes must be >= 1")
    if max_chains_per_snapshot is not None and max_chains_per_snapshot < 1:
        raise ValueError("max_chains_per_snapshot must be >= 1 when provided")
    csv_p = Path(alarm_csv_path)
    if not csv_p.exists():
        raise FileNotFoundError(f"Alarm CSV export file not found: {csv_p}")

    out_p = Path(output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    loader = AlarmCsvLoader(csv_p)
    all_records: list[tuple[datetime, datetime, AlarmRecord]] = []

    # Read records and sanitize their [start_time, end_time] using canonical loader fields and flags
    for r in loader.iter_records():
        if QualityFlag.TIMESTAMP_FUTURE_OUTLIER.value in r.quality_flags:
            continue

        start = r.canonical_start_time
        if start is None and r.raw.get("cah.create_time"):
            start = parse_timestamp(r.raw.get("cah.create_time"))

        if not start or start.year >= loader.future_year_threshold:
            continue

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        end = r.canonical_end_time
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        if (
            not end
            or end.year >= loader.future_year_threshold
            or QualityFlag.END_BEFORE_START.value in r.quality_flags
            or end <= start
            or (end - start).total_seconds() > 86400 * 7
        ):
            # Default active duration if missing, reversed, or invalid: 30 minutes
            end = start + timedelta(minutes=30)

        all_records.append((start, end, r))

    if not all_records:
        raise ValueError(f"No valid time records found in {csv_p}")

    all_records.sort(key=lambda item: item[0])

    if start_time_iso:
        t_base = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00"))
    else:
        # Find a dense cluster or use the first timestamp
        t_base = all_records[0][0]

    step_delta = timedelta(minutes=step_minutes)
    window_delta = timedelta(minutes=window_minutes)

    topology_ref = None
    topology_version = None
    topo_sources: list[SourceRecord] = []
    unavailable_caps: list[str] = []
    mapper = None

    if profile_id == "IP_NETWORK" and topo_ip_path is not None:
        from ..loaders.topology_ip_csv import TopoIPLoader
        from ..normalize.resource_mapping import ResourceMapper
        from ..normalize.topology import TOPOLOGY_LAYER_IP
        topo_ip_p = Path(topo_ip_path)
        if topo_ip_p.is_file():
            topo_loader = TopoIPLoader(topo_ip_p)
            topo_src_ver = topo_loader.source_version()
            topology_version = (
                canonical_topology_version("IP_NETWORK", topo_src_ver)
                if canonical_topology_version
                else f"ip-{topo_src_ver.split(':', 1)[-1][:32]}"
            )
            topology_ref = TopologyRef(
                profile_id="IP_NETWORK",
                topology_version=topology_version,
                source_version=topo_src_ver,
            )
            device_codes = topo_loader.device_codes()
            mapper = ResourceMapper(
                device_codes,
                topology_layer=TOPOLOGY_LAYER_IP,
                source_version=topo_src_ver,
            )
            topo_sources.append(
                SourceRecord(
                    source_id="topo_ip_csv",
                    source_kind=source_kind,
                    file_path=str(topo_ip_p),
                )
            )
    elif profile_id == "IT_SERVICES" and topo_it_path is not None:
        from ..normalize.resource_mapping import build_it_resource_mapper
        from ..loaders.topology_it_csv import ITTopologyLoader
        topo_it_p = Path(topo_it_path)
        if topo_it_p.is_dir():
            loader = ITTopologyLoader(topo_it_p)
            graph = loader.load_graph()
            topo_src_ver = graph.source_version
            topology_version = (
                canonical_topology_version("IT_SERVICES", topo_src_ver)
                if canonical_topology_version
                else f"it-{topo_src_ver.split(':', 1)[-1][:32]}"
            )
            topology_ref = TopologyRef(
                profile_id="IT_SERVICES",
                topology_version=topology_version,
                source_version=topo_src_ver,
            )
            mapper = build_it_resource_mapper(topo_it_p, source_version=topo_src_ver)
            topo_sources.append(
                SourceRecord(
                    source_id="topo_it_dir",
                    source_kind=source_kind,
                    file_path=str(topo_it_p),
                )
            )
            unavailable_caps.append("OPERATIONAL_DEPENDENCY_MAPPING_UNVERIFIED")
    elif profile_id == "ALARM_ONLY":
        unavailable_caps.append("TOPOLOGY_NOT_LOADED")

    snapshot_files: list[str] = []
    seen_alarms: set[str] = set()
    seen_chains: set[str] = set()

    for idx in range(num_snapshots):
        t_current = t_base + idx * step_delta
        t_window_start = t_current - window_delta

        # Active if alarm [start, end] intersects [t_window_start, t_current]
        active_records: list[AlarmRecord] = []
        for start, end, rec in all_records:
            if start <= t_current and end >= t_window_start:
                active_records.append(rec)

        # Optional chain limit
        if max_chains_per_snapshot:
            allowed_chains = {r.chaining_id for r in active_records}
            if len(allowed_chains) > max_chains_per_snapshot:
                sampled_chains = set(sorted(allowed_chains)[:max_chains_per_snapshot])
                active_records = [r for r in active_records if r.chaining_id in sampled_chains]

        snap_id = f"{scenario_id}_snap_{idx:03d}"
        snap_time_str = t_current.isoformat()

        alarms = tuple(
            normalize_alarm(r, snapshot_id=snap_id, source_kind=source_kind)
            for r in active_records
        )
        chains, memberships = build_chains(
            active_records, snapshot_id=snap_id, source_kind=source_kind
        )

        for a in alarms:
            seen_alarms.add(a.alarm_id)
        for c in chains:
            seen_chains.add(c.chain_id)

        sources = [
            SourceRecord(
                source_id="alarm_data_csv",
                source_kind=source_kind,
                file_path=str(csv_p),
                record_count=len(active_records),
            )
        ]

        if mapper is not None:
            mappings = tuple(
                mapper.map_alarm(
                    a.alarm_id, device_code=a.device_code, node_reference=a.node_reference
                )
                for a in alarms
            )
            topology = Topology(nodes=(), edges=(), mappings=mappings)
        else:
            topology = Topology(nodes=(), edges=(), mappings=())

        package = MockSnapshotPackage(
            snapshot=Snapshot(
                snapshot_id=snap_id,
                snapshot_version="1",
                snapshot_time=snap_time_str,
                status=SnapshotStatus.COMPLETE,
                source=DERIVED_REPLAY_SOURCE,
                source_kind=source_kind,
                # Derived replay has no upstream production timestamp.  Pin
                # this to snapshot time so equal inputs serialize identically.
                produced_at=snap_time_str,
                topology_version=topology_version,
                topology_ref=topology_ref,
            ),
            alarms=alarms,
            chains=chains,
            memberships=memberships,
            topology=topology,
            system_metadata=SystemMetadata(pair_metadata=()),
            provenance_manifest=ProvenanceManifest(
                sources=tuple(sources + topo_sources),
                unavailable_capabilities=tuple(unavailable_caps),
                notes=(
                    "DERIVED_REPLAY: time windows were generated from a single "
                    "real export and are not verified upstream snapshots.",
                    "PRODUCTION_EVOLUTION_VALIDATION_NOT_ESTABLISHED",
                ),
            ),
        )

        filename = f"snapshot_{idx:03d}.json"
        with (out_p / filename).open("w", encoding="utf-8") as f:
            f.write(package_to_json(package, indent=2))
        snapshot_files.append(filename)

    # Write sequence.yaml
    expected_transitions = [
        {
            "from": snapshot_files[i],
            "to": snapshot_files[i + 1],
            "expected_event": "CONTINUE",
        }
        for i in range(len(snapshot_files) - 1)
    ]
    manifest = {
        "scenario_id": scenario_id,
        "sequence_type": "EVOLUTION",
        "seed": 42,
        "derivation_kind": "DERIVED_REPLAY",
        "production_validation": "NOT_ESTABLISHED",
        "step_minutes": step_minutes,
        "window_minutes": window_minutes,
        "start_time": t_base.isoformat(),
        "snapshots": snapshot_files,
        "expected_transitions": expected_transitions,
    }
    with (out_p / "sequence.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)

    return SlicedSequenceSummary(
        scenario_id=scenario_id,
        output_dir=out_p,
        snapshot_count=num_snapshots,
        total_distinct_alarms=len(seen_alarms),
        total_distinct_chains=len(seen_chains),
        start_time=t_base.isoformat(),
        end_time=(t_base + (num_snapshots - 1) * step_delta).isoformat(),
        step_minutes=step_minutes,
        window_minutes=window_minutes,
    )
