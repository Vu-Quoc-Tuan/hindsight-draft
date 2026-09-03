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
from typing import Any, Sequence
import yaml

from ..config import MockConfig
from ..contract import (
    MockSnapshotPackage,
    ProvenanceClass,
    ProvenanceManifest,
    Snapshot,
    SnapshotStatus,
    SourceKind,
    SourceRecord,
    SystemMetadata,
    package_to_json,
)
from ..loaders.alarm_csv import AlarmCsvLoader, AlarmRecord
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


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    val = value.strip().split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(val, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


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
) -> SlicedSequenceSummary:
    """Slice alarms into consecutive snapshot packages and save sequence directory."""
    csv_p = Path(alarm_csv_path)
    if not csv_p.exists():
        raise FileNotFoundError(f"Alarm CSV export file not found: {csv_p}")

    out_p = Path(output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    loader = AlarmCsvLoader(csv_p)
    all_records: list[tuple[datetime, datetime, AlarmRecord]] = []

    # Read records and parse their [start_time, end_time]
    for r in loader.iter_records():
        start = _parse_time(r.raw.get("cah.start_time")) or _parse_time(r.raw.get("cah.create_time"))
        if not start:
            continue
        end = _parse_time(r.raw.get("end_time"))
        if not end or end <= start or (end - start).total_seconds() > 86400 * 7:
            # Default active duration if missing or invalid: 30 minutes
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
                sampled_chains = set(list(allowed_chains)[:max_chains_per_snapshot])
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

        package = MockSnapshotPackage(
            snapshot=Snapshot(
                snapshot_id=snap_id,
                snapshot_version="1",
                snapshot_time=snap_time_str,
                status=SnapshotStatus.COMPLETE,
                source=DERIVED_REPLAY_SOURCE,
                source_kind=source_kind,
                produced_at=datetime.now(timezone.utc).isoformat(),
            ),
            alarms=alarms,
            chains=chains,
            memberships=memberships,
            topology=None,
            system_metadata=SystemMetadata(pair_metadata=()),
            provenance_manifest=ProvenanceManifest(
                sources=tuple(sources),
                unavailable_capabilities=("TOPOLOGY_NOT_LOADED",),
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
    manifest = {
        "scenario_id": scenario_id,
        "sequence_type": "EVOLUTION",
        "derivation_kind": "DERIVED_REPLAY",
        "production_validation": "NOT_ESTABLISHED",
        "step_minutes": step_minutes,
        "window_minutes": window_minutes,
        "start_time": t_base.isoformat(),
        "snapshots": snapshot_files,
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
