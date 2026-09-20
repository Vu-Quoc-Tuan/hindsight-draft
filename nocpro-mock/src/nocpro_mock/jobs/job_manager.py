"""Server-side Background Job Manager for NocPro Mock Studio.

Manages concurrency lanes, background workers, Kafka streaming with interruptible
delays, pause/resume barriers, state persistence, and SSE event streaming.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from aiokafka import AIOKafkaProducer

from ..contract import (
    parse_package,
)
from ..producer.kafka_snapshot import (
    KafkaSnapshotConfig,
    build_snapshot_wire_batch,
    publish_snapshot_batch,
)
from ..producer.kafka_topology import (
    KafkaTopologyConfig,
    build_ip_topology_payload,
    build_it_topology_payload,
    build_topology_wire_batch,
)
from ..replay.sequence_slicer import slice_alarm_sequence
from ..scenarios.sequence import load_sequence_manifest

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    PAUSED = "PAUSED"
    STOP_REQUESTED = "STOP_REQUESTED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobType(str, Enum):
    SLICE_SEQUENCE = "SLICE_SEQUENCE"
    PUBLISH_SINGLE = "PUBLISH_SINGLE"
    PUBLISH_SEQUENCE = "PUBLISH_SEQUENCE"
    PUBLISH_TOPOLOGY = "PUBLISH_TOPOLOGY"


class ConflictError(Exception):
    """Raised when an active job is already occupying the requested concurrency lane."""


LANE_SNAPSHOT = "snapshot_publish"
LANE_TOPOLOGY = "topology_publish"
LANE_SLICE = "slice_worker"

JOB_TYPE_LANES: dict[JobType, str] = {
    JobType.PUBLISH_SINGLE: LANE_SNAPSHOT,
    JobType.PUBLISH_SEQUENCE: LANE_SNAPSHOT,
    JobType.PUBLISH_TOPOLOGY: LANE_TOPOLOGY,
    JobType.SLICE_SEQUENCE: LANE_SLICE,
}

ACTIVE_STATUSES = {
    JobStatus.PENDING,
    JobStatus.RUNNING,
    JobStatus.PAUSE_REQUESTED,
    JobStatus.PAUSED,
    JobStatus.STOP_REQUESTED,
}


@dataclass
class JobEvent:
    event_id: int
    timestamp: str
    event_type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "data": self.data,
        }


@dataclass
class JobRecord:
    job_id: str
    job_type: JobType
    status: JobStatus
    created_at: str
    params: dict[str, Any]
    started_at: str | None = None
    completed_at: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "params": self.params,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "events_count": len(self.events),
        }


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class JobController:
    """Controls execution and signals for a running job."""

    def __init__(self, record: JobRecord, persist_fn: Callable[[JobRecord], None]):
        self.record = record
        self._persist_fn = persist_fn
        self._lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._pause_requested = threading.Event()
        self._resume_event = threading.Event()
        self._event_counter = 0
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()

    @property
    def job_id(self) -> str:
        return self.record.job_id

    @property
    def status(self) -> JobStatus:
        with self._lock:
            return self.record.status

    def is_stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def is_pause_requested(self) -> bool:
        return self._pause_requested.is_set()

    def update_status(self, new_status: JobStatus, message: str | None = None) -> None:
        with self._lock:
            old_status = self.record.status
            self.record.status = new_status
            if new_status == JobStatus.RUNNING and not self.record.started_at:
                self.record.started_at = _iso_now()
            elif new_status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELLED}:
                self.record.completed_at = _iso_now()
            self._persist_fn(self.record)

        self.emit_event(
            "status_changed",
            {"from": old_status.value, "to": new_status.value, "message": message or ""},
        )

    def update_progress(self, current: int, total: int, message: str = "", extra: dict[str, Any] | None = None) -> None:
        percent = round((current / total * 100), 1) if total > 0 else 0.0
        prog = {
            "current": current,
            "total": total,
            "percent": percent,
            "message": message,
        }
        if extra:
            prog.update(extra)

        with self._lock:
            self.record.progress = prog
            self._persist_fn(self.record)

        self.emit_event("progress", prog)

    def set_result(self, result: dict[str, Any]) -> None:
        with self._lock:
            self.record.result = result
            self._persist_fn(self.record)

    def set_error(self, error: str) -> None:
        with self._lock:
            self.record.error = error
            self._persist_fn(self.record)
        self.emit_event("error", {"error": error})

    def request_pause(self) -> None:
        with self._lock:
            if self.record.status != JobStatus.RUNNING:
                raise ValueError(f"Cannot pause job in status {self.record.status.value}")
            self.record.status = JobStatus.PAUSE_REQUESTED
            self._pause_requested.set()
            self._resume_event.clear()
            self._persist_fn(self.record)
        self.emit_event("pause_requested", {"job_id": self.job_id})

    def request_resume(self) -> None:
        with self._lock:
            if self.record.status != JobStatus.PAUSED:
                raise ValueError(f"Cannot resume job in status {self.record.status.value}")
            self.record.status = JobStatus.RUNNING
            self._pause_requested.clear()
            self._resume_event.set()
            self._persist_fn(self.record)
        self.emit_event("resumed", {"job_id": self.job_id})

    def request_stop(self) -> None:
        with self._lock:
            if self.record.status not in {JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.PAUSE_REQUESTED}:
                raise ValueError(f"Cannot stop job in status {self.record.status.value}")
            self.record.status = JobStatus.STOP_REQUESTED
            self._stop_requested.set()
            self._resume_event.set()  # Unblock if currently paused
            self._persist_fn(self.record)
        self.emit_event("stop_requested", {"job_id": self.job_id})

    def wait_if_paused(self) -> bool:
        """Called at clean snapshot boundaries. If paused, waits until resumed or stopped.
        
        Returns:
            True if job was stopped during pause, False if resumed normally.
        """
        if self._stop_requested.is_set():
            return True

        if self._pause_requested.is_set():
            with self._lock:
                self.record.status = JobStatus.PAUSED
                self._persist_fn(self.record)
            self.emit_event("paused", {"job_id": self.job_id})

            # Wait until resume or stop
            while not self._resume_event.is_set():
                time.sleep(0.05)

            if self._stop_requested.is_set():
                return True

            with self._lock:
                if self.record.status == JobStatus.PAUSED:
                    self.record.status = JobStatus.RUNNING
                    self._persist_fn(self.record)
            self.emit_event("resumed", {"job_id": self.job_id})

        return self._stop_requested.is_set()

    def interruptible_delay(self, seconds: float) -> bool:
        """Sleep for `seconds` while checking for pause or stop flags.
        
        Returns:
            True if stopped during sleep, False if finished sleep normally.
        """
        if seconds <= 0:
            return self._stop_requested.is_set()

        start = time.time()
        while time.time() - start < seconds:
            if self._stop_requested.is_set() or self._pause_requested.is_set():
                break
            time.sleep(min(0.05, seconds - (time.time() - start)))

        return self._stop_requested.is_set()

    def emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._event_counter += 1
            event = JobEvent(
                event_id=self._event_counter,
                timestamp=_iso_now(),
                event_type=event_type,
                data=data,
            )
            event_dict = event.to_dict()
            self.record.events.append(event_dict)
            if len(self.record.events) > 1000:
                self.record.events = self.record.events[-1000:]
            subscribers = list(self._subscribers)

        for q in subscribers:
            try:
                q.put_nowait(event_dict)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        with self._lock:
            q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=500)
            # Replay recent events
            for ev in self.record.events[-50:]:
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    break
            self._subscribers.add(q)
            return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(q)


class JobManager:
    """Coordinates jobs, enforce concurrency lanes, and manages disk persistence."""

    def __init__(self, state_dir: str | Path | None = None):
        env_dir = os.environ.get("NOCPRO_MOCK_STATE_DIR")
        self.state_dir = Path(state_dir or env_dir or ".cache").resolve()
        self.jobs_dir = self.state_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._controllers: dict[str, JobController] = {}
        self._load_persisted_jobs()

    def _load_persisted_jobs(self) -> None:
        """Load past jobs from disk and sanitize any interrupted jobs."""
        for file in self.jobs_dir.glob("*.json"):
            try:
                raw = json.loads(file.read_text(encoding="utf-8"))
                status = JobStatus(raw["status"])
                if status in ACTIVE_STATUSES:
                    # Mark stale interrupted jobs as FAILED on startup
                    status = JobStatus.FAILED
                    raw["status"] = status.value
                    raw["error"] = "Process terminated while job was active"
                    raw["completed_at"] = _iso_now()
                    file.write_text(json.dumps(raw, indent=2), encoding="utf-8")

                record = JobRecord(
                    job_id=raw["job_id"],
                    job_type=JobType(raw["job_type"]),
                    status=status,
                    created_at=raw["created_at"],
                    params=raw.get("params", {}),
                    started_at=raw.get("started_at"),
                    completed_at=raw.get("completed_at"),
                    progress=raw.get("progress", {}),
                    result=raw.get("result"),
                    error=raw.get("error"),
                    events=raw.get("events", []),
                )
                ctrl = JobController(record, self._persist_job)
                self._controllers[record.job_id] = ctrl
            except Exception as exc:
                logger.warning("Failed to load job file %s: %s", file, exc)

    def _persist_job(self, record: JobRecord) -> None:
        path = self.jobs_dir / f"{record.job_id}.json"
        temp_path = self.jobs_dir / f"{record.job_id}.json.tmp"
        payload = {
            "job_id": record.job_id,
            "job_type": record.job_type.value,
            "status": record.status.value,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "completed_at": record.completed_at,
            "params": record.params,
            "progress": record.progress,
            "result": record.result,
            "error": record.error,
            "events": record.events,
        }
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)

    def _check_lane_available(self, job_type: JobType) -> None:
        target_lane = JOB_TYPE_LANES[job_type]
        for ctrl in self._controllers.values():
            if JOB_TYPE_LANES.get(ctrl.record.job_type) == target_lane:
                if ctrl.record.status in ACTIVE_STATUSES:
                    raise ConflictError(
                        f"Concurrency lane '{target_lane}' is currently locked by active job "
                        f"'{ctrl.job_id}' (status: {ctrl.record.status.value}). Only one active job per lane is permitted."
                    )

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            ctrl = self._controllers.get(job_id)
            return ctrl.record if ctrl else None

    def get_controller(self, job_id: str) -> JobController | None:
        with self._lock:
            return self._controllers.get(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            records = [c.record for c in self._controllers.values()]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in records[:limit]]

    def create_job(self, job_type: JobType, params: dict[str, Any]) -> JobController:
        with self._lock:
            self._check_lane_available(job_type)
            job_id = f"job_{job_type.value.lower()}_{uuid.uuid4().hex[:8]}"
            record = JobRecord(
                job_id=job_id,
                job_type=job_type,
                status=JobStatus.PENDING,
                created_at=_iso_now(),
                params=params,
            )
            ctrl = JobController(record, self._persist_job)
            self._controllers[job_id] = ctrl
            self._persist_job(record)
            return ctrl

    # -------------------------------------------------------------------------
    # Execution Runners
    # -------------------------------------------------------------------------

    def submit_slice_job(
        self,
        *,
        alarm_csv_path: str | Path,
        output_dir: str | Path,
        scenario_id: str,
        num_snapshots: int = 5,
        step_minutes: int = 5,
        window_minutes: int = 15,
        max_chains: int | None = None,
        profile_id: str = "ALARM_ONLY",
        topo_ip_path: str | Path | None = None,
        topo_it_path: str | Path | None = None,
    ) -> JobRecord:
        params = {
            "alarm_csv_path": str(alarm_csv_path),
            "output_dir": str(output_dir),
            "scenario_id": scenario_id,
            "num_snapshots": num_snapshots,
            "step_minutes": step_minutes,
            "window_minutes": window_minutes,
            "max_chains": max_chains,
            "profile_id": profile_id,
            "topo_ip_path": str(topo_ip_path) if topo_ip_path else None,
            "topo_it_path": str(topo_it_path) if topo_it_path else None,
        }
        ctrl = self.create_job(JobType.SLICE_SEQUENCE, params)
        worker = threading.Thread(
            target=self._run_slice_worker,
            args=(ctrl, params),
            daemon=True,
            name=f"slice-worker-{ctrl.job_id}",
        )
        worker.start()
        return ctrl.record

    def _run_slice_worker(self, ctrl: JobController, params: dict[str, Any]) -> None:
        ctrl.update_status(JobStatus.RUNNING, "Starting sequence slicing...")
        try:
            summary = slice_alarm_sequence(
                alarm_csv_path=params["alarm_csv_path"],
                output_dir=params["output_dir"],
                scenario_id=params["scenario_id"],
                num_snapshots=params["num_snapshots"],
                step_minutes=params["step_minutes"],
                window_minutes=params["window_minutes"],
                max_chains_per_snapshot=params["max_chains"],
                profile_id=params.get("profile_id", "ALARM_ONLY"),
                topo_ip_path=params.get("topo_ip_path"),
                topo_it_path=params.get("topo_it_path"),
            )
            ctrl.update_progress(
                params["num_snapshots"],
                params["num_snapshots"],
                f"Successfully generated {summary.snapshot_count} snapshots",
            )
            ctrl.set_result(
                {
                    "scenario_id": summary.scenario_id,
                    "output_dir": str(summary.output_dir),
                    "snapshot_count": summary.snapshot_count,
                    "total_distinct_alarms": summary.total_distinct_alarms,
                    "total_distinct_chains": summary.total_distinct_chains,
                    "start_time": summary.start_time,
                    "end_time": summary.end_time,
                }
            )
            ctrl.update_status(JobStatus.COMPLETED, "Slicing completed successfully")
        except Exception as exc:
            logger.exception("Slice job failed: %s", exc)
            ctrl.set_error(str(exc))
            ctrl.update_status(JobStatus.FAILED, str(exc))

    def submit_topology_publish_job(
        self,
        *,
        profile_id: str,
        source_path: str | Path,
        bootstrap_servers: str,
        topic: str = "nocpro.topology.v1",
        chunk_target_bytes: int = 2 * 1024 * 1024,
    ) -> JobRecord:
        params = {
            "profile_id": profile_id,
            "source_path": str(source_path),
            "bootstrap_servers": bootstrap_servers,
            "topic": topic,
            "chunk_target_bytes": chunk_target_bytes,
        }
        ctrl = self.create_job(JobType.PUBLISH_TOPOLOGY, params)
        worker = threading.Thread(
            target=self._run_topology_worker,
            args=(ctrl, params),
            daemon=True,
            name=f"topo-worker-{ctrl.job_id}",
        )
        worker.start()
        return ctrl.record

    def _run_topology_worker(self, ctrl: JobController, params: dict[str, Any]) -> None:
        ctrl.update_status(JobStatus.RUNNING, "Preparing topology wire payload...")
        try:
            profile_id = params["profile_id"]
            path = Path(params["source_path"])
            if profile_id == "IP_NETWORK":
                payload = build_ip_topology_payload(path)
            elif profile_id == "IT_SERVICES":
                payload = build_it_topology_payload(path)
            else:
                raise ValueError(f"Unsupported topology profile: {profile_id}")

            config = KafkaTopologyConfig(
                topic=params["topic"],
                chunk_target_bytes=params["chunk_target_bytes"],
            )
            batch = build_topology_wire_batch(payload, config=config)

            async def _publish() -> None:
                producer = AIOKafkaProducer(
                    bootstrap_servers=params["bootstrap_servers"],
                    enable_idempotence=True,
                    max_request_size=max(4 * 1024 * 1024, config.chunk_target_bytes * 2),
                )
                await producer.start()
                try:
                    ctrl.update_progress(0, len(batch.events), "Connected to Kafka. Publishing events...")
                    for idx, event in enumerate(batch.events):
                        await producer.send_and_wait(
                            params["topic"],
                            key=batch.key,
                            value=json.dumps(event, separators=(",", ":")).encode("utf-8"),
                        )
                        ctrl.update_progress(
                            idx + 1,
                            len(batch.events),
                            f"Published {event.get('event_type')} ({idx + 1}/{len(batch.events)})",
                        )
                    await producer.flush()
                finally:
                    await producer.stop()

            asyncio.run(_publish())

            ctrl.set_result(
                {
                    "profile_id": profile_id,
                    "topology_version": batch.topology_version,
                    "chunks_published": len(batch.chunks),
                    "total_uncompressed_bytes": len(batch.canonical_bytes),
                    "compressed_bytes": len(batch.compressed_bytes),
                    "payload_checksum": batch.complete["payload_checksum"],
                }
            )
            ctrl.update_status(JobStatus.COMPLETED, "Topology published successfully")
        except Exception as exc:
            logger.exception("Topology publish job failed: %s", exc)
            ctrl.set_error(str(exc))
            ctrl.update_status(JobStatus.FAILED, str(exc))

    def submit_sequence_publish_job(
        self,
        *,
        sequence_path: str | Path,
        bootstrap_servers: str,
        topic: str = "nocpro.snapshot.v1",
        chunk_target_bytes: int = 2 * 1024 * 1024,
        delay_seconds: float = 0.3,
        mode: str = "paced",  # "paced" or "single_shot"
    ) -> JobRecord:
        params = {
            "sequence_path": str(sequence_path),
            "bootstrap_servers": bootstrap_servers,
            "topic": topic,
            "chunk_target_bytes": chunk_target_bytes,
            "delay_seconds": delay_seconds if mode == "paced" else 0.0,
            "mode": mode,
        }
        ctrl = self.create_job(JobType.PUBLISH_SEQUENCE, params)
        worker = threading.Thread(
            target=self._run_sequence_worker,
            args=(ctrl, params),
            daemon=True,
            name=f"seq-worker-{ctrl.job_id}",
        )
        worker.start()
        return ctrl.record

    def _run_sequence_worker(self, ctrl: JobController, params: dict[str, Any]) -> None:
        ctrl.update_status(JobStatus.RUNNING, "Initializing Kafka sequence stream...")
        try:
            seq_dir = Path(params["sequence_path"])
            manifest = load_sequence_manifest(seq_dir / "sequence.yaml")
            snapshots = list(manifest.snapshots)
            total = len(snapshots)

            config = KafkaSnapshotConfig(
                topic=params["topic"],
                chunk_target_bytes=params["chunk_target_bytes"],
            )

            results: list[dict[str, Any]] = []

            async def _stream() -> None:
                # Reusable producer across entire sequence
                producer = AIOKafkaProducer(
                    bootstrap_servers=params["bootstrap_servers"],
                    enable_idempotence=True,
                    max_request_size=max(4 * 1024 * 1024, config.chunk_target_bytes * 2),
                )
                await producer.start()
                try:
                    for idx, snap_file in enumerate(snapshots):
                        # Barrier check before beginning next snapshot
                        if ctrl.wait_if_paused():
                            ctrl.update_status(JobStatus.STOPPED, f"Sequence stopped at snapshot {idx}/{total}")
                            return

                        snap_path = seq_dir / snap_file
                        raw = json.loads(snap_path.read_text(encoding="utf-8"))
                        package = parse_package(raw)
                        batch = build_snapshot_wire_batch(package, config=config)

                        # Publish snapshot events sequentially under snapshot key
                        await publish_snapshot_batch(producer, batch, topic=params["topic"])
                        await producer.flush()

                        snap_res = {
                            "snapshot_id": package.snapshot.snapshot_id,
                            "snapshot_version": package.snapshot.snapshot_version,
                            "chunks_count": len(batch.chunks),
                            "total_bytes": len(batch.canonical_bytes),
                            "checksum": batch.complete["snapshot_checksum"][:12] + "...",
                        }
                        results.append(snap_res)

                        ctrl.update_progress(
                            idx + 1,
                            total,
                            f"Published snapshot {idx + 1}/{total} ({package.snapshot.snapshot_id})",
                            extra={"last_snapshot": snap_res},
                        )

                        # Interruptible delay between snapshots
                        if idx < total - 1 and params["delay_seconds"] > 0:
                            stopped = ctrl.interruptible_delay(params["delay_seconds"])
                            if stopped:
                                ctrl.update_status(JobStatus.STOPPED, f"Sequence stopped after snapshot {idx + 1}/{total}")
                                return

                    ctrl.set_result(
                        {
                            "sequence_id": manifest.scenario_id,
                            "total_snapshots": total,
                            "published_count": len(results),
                            "snapshots": results,
                        }
                    )
                    ctrl.update_status(JobStatus.COMPLETED, f"Published all {total} snapshots successfully")

                finally:
                    await producer.stop()

            asyncio.run(_stream())

        except Exception as exc:
            logger.exception("Sequence publish job failed: %s", exc)
            ctrl.set_error(str(exc))
            ctrl.update_status(JobStatus.FAILED, str(exc))

    def submit_single_publish_job(
        self,
        *,
        package: Any,
        bootstrap_servers: str,
        topic: str = "nocpro.snapshot.v1",
        chunk_target_bytes: int = 2 * 1024 * 1024,
    ) -> JobRecord:
        params = {
            "snapshot_id": package.snapshot.snapshot_id,
            "bootstrap_servers": bootstrap_servers,
            "topic": topic,
            "chunk_target_bytes": chunk_target_bytes,
        }
        ctrl = self.create_job(JobType.PUBLISH_SINGLE, params)
        worker = threading.Thread(
            target=self._run_single_worker,
            args=(ctrl, package, params),
            daemon=True,
            name=f"single-worker-{ctrl.job_id}",
        )
        worker.start()
        return ctrl.record

    def _run_single_worker(self, ctrl: JobController, package: Any, params: dict[str, Any]) -> None:
        ctrl.update_status(JobStatus.RUNNING, "Publishing snapshot...")
        try:
            config = KafkaSnapshotConfig(
                topic=params["topic"],
                chunk_target_bytes=params["chunk_target_bytes"],
            )
            batch = build_snapshot_wire_batch(package, config=config)

            async def _publish() -> None:
                producer = AIOKafkaProducer(
                    bootstrap_servers=params["bootstrap_servers"],
                    enable_idempotence=True,
                    max_request_size=max(4 * 1024 * 1024, config.chunk_target_bytes * 2),
                )
                await producer.start()
                try:
                    await publish_snapshot_batch(producer, batch, topic=params["topic"])
                    await producer.flush()
                finally:
                    await producer.stop()

            asyncio.run(_publish())

            ctrl.update_progress(1, 1, "Snapshot published")
            ctrl.set_result(
                {
                    "snapshot_id": package.snapshot.snapshot_id,
                    "chunks_count": len(batch.chunks),
                    "total_bytes": len(batch.canonical_bytes),
                    "checksum": batch.complete["snapshot_checksum"],
                }
            )
            ctrl.update_status(JobStatus.COMPLETED, "Snapshot published successfully")
        except Exception as exc:
            logger.exception("Single snapshot publish job failed: %s", exc)
            ctrl.set_error(str(exc))
            ctrl.update_status(JobStatus.FAILED, str(exc))


Job = JobRecord

_GLOBAL_JOB_MANAGER: JobManager | None = None
_GLOBAL_LOCK = threading.Lock()


def get_job_manager(state_dir: str | Path | None = None) -> JobManager:
    global _GLOBAL_JOB_MANAGER
    with _GLOBAL_LOCK:
        if _GLOBAL_JOB_MANAGER is None:
            _GLOBAL_JOB_MANAGER = JobManager(state_dir=state_dir)
        return _GLOBAL_JOB_MANAGER
