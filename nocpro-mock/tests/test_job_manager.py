"""Unit tests for JobManager, concurrency lanes, state persistence, and streaming lifecycle."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nocpro_mock.jobs.job_manager import (
    ConflictError,
    JobManager,
    JobStatus,
    JobType,
    LANE_SNAPSHOT,
    LANE_TOPOLOGY,
    LANE_SLICE,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Path:
    state_dir = tmp_path / "mock_state"
    state_dir.mkdir()
    return state_dir


def test_job_manager_create_and_persist(temp_state_dir: Path):
    manager = JobManager(state_dir=temp_state_dir)
    ctrl = manager.create_job(JobType.SLICE_SEQUENCE, {"scenario_id": "test_1"})
    assert ctrl.status == JobStatus.PENDING
    assert ctrl.job_id.startswith("job_slice_sequence_")

    job_file = temp_state_dir / "jobs" / f"{ctrl.job_id}.json"
    assert job_file.is_file()
    data = json.loads(job_file.read_text(encoding="utf-8"))
    assert data["job_id"] == ctrl.job_id
    assert data["status"] == "PENDING"
    assert data["params"]["scenario_id"] == "test_1"

    # Reload from fresh manager
    manager2 = JobManager(state_dir=temp_state_dir)
    loaded = manager2.get_job(ctrl.job_id)
    assert loaded is not None
    assert loaded.job_id == ctrl.job_id


def test_job_manager_stale_job_recovery(temp_state_dir: Path):
    manager = JobManager(state_dir=temp_state_dir)
    ctrl = manager.create_job(JobType.PUBLISH_SEQUENCE, {"seq": "1"})
    ctrl.update_status(JobStatus.RUNNING, "Streaming...")

    # Simulate process crash/restart
    manager_restart = JobManager(state_dir=temp_state_dir)
    loaded = manager_restart.get_job(ctrl.job_id)
    assert loaded is not None
    assert loaded.status == JobStatus.FAILED
    assert "Process terminated" in (loaded.error or "")


def test_job_manager_concurrency_lanes(temp_state_dir: Path):
    manager = JobManager(state_dir=temp_state_dir)

    # Lane: snapshot_publish
    ctrl1 = manager.create_job(JobType.PUBLISH_SINGLE, {"snap": "1"})
    ctrl1.update_status(JobStatus.RUNNING)

    # Submitting another snapshot job must raise ConflictError
    with pytest.raises(ConflictError) as exc_info:
        manager.create_job(JobType.PUBLISH_SEQUENCE, {"seq": "1"})
    assert "snapshot_publish" in str(exc_info.value)
    assert "Only one active job per lane" in str(exc_info.value)

    # But submitting a slice job (different lane) is allowed
    ctrl2 = manager.create_job(JobType.SLICE_SEQUENCE, {"slice": "1"})
    assert ctrl2.job_id != ctrl1.job_id

    # And submitting a topology publish job (different lane) is allowed
    ctrl3 = manager.create_job(JobType.PUBLISH_TOPOLOGY, {"topo": "1"})
    assert ctrl3.job_id != ctrl1.job_id

    # Once ctrl1 finishes, snapshot_publish lane is freed
    ctrl1.update_status(JobStatus.COMPLETED)
    ctrl4 = manager.create_job(JobType.PUBLISH_SEQUENCE, {"seq": "2"})
    assert ctrl4.status == JobStatus.PENDING


def test_job_controller_pause_resume_stop_lifecycle(temp_state_dir: Path):
    manager = JobManager(state_dir=temp_state_dir)
    ctrl = manager.create_job(JobType.PUBLISH_SEQUENCE, {"seq": "test"})
    ctrl.update_status(JobStatus.RUNNING)

    # Request pause
    ctrl.request_pause()
    assert ctrl.status == JobStatus.PAUSE_REQUESTED
    assert ctrl.is_pause_requested()

    # Wait at barrier -> becomes PAUSED
    stopped = False
    import threading
    def _simulate_worker():
        nonlocal stopped
        stopped = ctrl.wait_if_paused()

    t = threading.Thread(target=_simulate_worker)
    t.start()
    import time
    time.sleep(0.05)
    assert ctrl.status == JobStatus.PAUSED

    # Resume
    ctrl.request_resume()
    t.join(timeout=1.0)
    assert not stopped
    assert ctrl.status == JobStatus.RUNNING

    # Stop requested
    ctrl.request_stop()
    assert ctrl.is_stop_requested()
    assert ctrl.status == JobStatus.STOP_REQUESTED
    assert ctrl.wait_if_paused() is True


def test_job_controller_events_subscription(temp_state_dir: Path):
    manager = JobManager(state_dir=temp_state_dir)
    ctrl = manager.create_job(JobType.SLICE_SEQUENCE, {})
    q = ctrl.subscribe()

    ctrl.update_status(JobStatus.RUNNING, "Starting...")
    ctrl.update_progress(1, 5, "Step 1")

    ev1 = q.get(timeout=1.0)
    assert ev1["event_type"] == "status_changed"
    assert ev1["data"]["to"] == "RUNNING"

    ev2 = q.get(timeout=1.0)
    assert ev2["event_type"] == "progress"
    assert ev2["data"]["current"] == 1
    assert ev2["data"]["total"] == 5

    ctrl.unsubscribe(q)


def test_slice_job_execution(temp_state_dir: Path, tmp_path: Path):
    # Locate actual alarm export
    root = Path(__file__).resolve().parents[1]
    csv_p = root / "datasets" / "raw" / "alarm" / "alarm_data.csv"
    if not csv_p.is_file():
        pytest.skip("alarm_data.csv not found for slice integration test")

    manager = JobManager(state_dir=temp_state_dir)
    out_dir = tmp_path / "sliced_test"

    record = manager.submit_slice_job(
        alarm_csv_path=csv_p,
        output_dir=out_dir,
        scenario_id="pytest_seq",
        num_snapshots=2,
        step_minutes=10,
        window_minutes=20,
    )

    # Wait for completion
    ctrl = manager.get_controller(record.job_id)
    assert ctrl is not None
    import time
    t0 = time.time()
    while ctrl.status in {JobStatus.PENDING, JobStatus.RUNNING} and time.time() - t0 < 5.0:
        time.sleep(0.05)

    assert ctrl.status == JobStatus.COMPLETED
    assert ctrl.record.result is not None
    assert ctrl.record.result["snapshot_count"] == 2
    assert (out_dir / "sequence.yaml").is_file()
    assert (out_dir / "snapshot_000.json").is_file()
    assert (out_dir / "snapshot_001.json").is_file()


@patch("nocpro_mock.jobs.job_manager.AIOKafkaProducer")
def test_sequence_publish_mocked_kafka(mock_producer_cls, temp_state_dir: Path, tmp_path: Path):
    mock_producer = AsyncMock()
    mock_producer_cls.return_value = mock_producer

    # Prepare a minimal sequence directory
    seq_dir = tmp_path / "mock_seq"
    seq_dir.mkdir()
    (seq_dir / "sequence.yaml").write_text(
        "scenario_id: test_seq\nsequence_type: EVOLUTION\nseed: 42\nsnapshots:\n  - snap_0.json\n  - snap_1.json\nexpected_transitions:\n  - from: snap_0.json\n    to: snap_1.json\n    expected_event: CONTINUE\n",
        encoding="utf-8",
    )

    from nocpro_mock.contract import MockSnapshotPackage, Snapshot, SnapshotStatus, SourceKind, package_to_json
    for i in range(2):
        pkg = MockSnapshotPackage(
            snapshot=Snapshot(
                snapshot_id=f"snap_{i}",
                snapshot_version="1",
                snapshot_time="2026-01-01T00:00:00Z",
                status=SnapshotStatus.COMPLETE,
                source="test",
                source_kind=SourceKind.SYNTHETIC_TEST,
                produced_at="2026-01-01T00:00:00Z",
            )
        )
        (seq_dir / f"snap_{i}.json").write_text(package_to_json(pkg), encoding="utf-8")

    manager = JobManager(state_dir=temp_state_dir)
    record = manager.submit_sequence_publish_job(
        sequence_path=seq_dir,
        bootstrap_servers="localhost:9092",
        delay_seconds=0.01,
        mode="paced",
    )

    ctrl = manager.get_controller(record.job_id)
    assert ctrl is not None
    import time
    t0 = time.time()
    while ctrl.status in {JobStatus.PENDING, JobStatus.RUNNING} and time.time() - t0 < 5.0:
        time.sleep(0.05)

    assert ctrl.status == JobStatus.COMPLETED
    assert ctrl.record.result is not None
    assert ctrl.record.result["published_count"] == 2
    # Ensure producer was started and stopped exactly once
    mock_producer.start.assert_awaited_once()
    mock_producer.stop.assert_awaited_once()


@patch("nocpro_mock.jobs.job_manager.AIOKafkaProducer")
def test_sequence_publish_pause_resume_stop(mock_producer_cls, temp_state_dir: Path, tmp_path: Path):
    mock_producer = AsyncMock()
    mock_producer_cls.return_value = mock_producer

    seq_dir = tmp_path / "mock_seq_pause"
    seq_dir.mkdir()
    (seq_dir / "sequence.yaml").write_text(
        "scenario_id: test_seq_p\nsequence_type: EVOLUTION\nseed: 42\nsnapshots:\n  - snap_0.json\n  - snap_1.json\n  - snap_2.json\nexpected_transitions:\n  - from: snap_0.json\n    to: snap_1.json\n    expected_event: CONTINUE\n  - from: snap_1.json\n    to: snap_2.json\n    expected_event: CONTINUE\n",
        encoding="utf-8",
    )

    from nocpro_mock.contract import MockSnapshotPackage, Snapshot, SnapshotStatus, SourceKind, package_to_json
    for i in range(3):
        pkg = MockSnapshotPackage(
            snapshot=Snapshot(
                snapshot_id=f"snap_{i}",
                snapshot_version="1",
                snapshot_time="2026-01-01T00:00:00Z",
                status=SnapshotStatus.COMPLETE,
                source="test",
                source_kind=SourceKind.SYNTHETIC_TEST,
                produced_at="2026-01-01T00:00:00Z",
            )
        )
        (seq_dir / f"snap_{i}.json").write_text(package_to_json(pkg), encoding="utf-8")

    manager = JobManager(state_dir=temp_state_dir)
    record = manager.submit_sequence_publish_job(
        sequence_path=seq_dir,
        bootstrap_servers="localhost:9092",
        delay_seconds=0.2,
        mode="paced",
    )

    ctrl = manager.get_controller(record.job_id)
    assert ctrl is not None
    import time
    # Wait until running
    while ctrl.status == JobStatus.PENDING:
        time.sleep(0.01)

    # Pause after first snapshot
    ctrl.request_pause()
    time.sleep(0.1)
    assert ctrl.status in {JobStatus.PAUSE_REQUESTED, JobStatus.PAUSED}

    # If paused, resume
    if ctrl.status == JobStatus.PAUSED:
        ctrl.request_resume()
        assert ctrl.status == JobStatus.RUNNING

    # Stop during remaining stream
    ctrl.request_stop()
    t0 = time.time()
    while ctrl.status in {JobStatus.RUNNING, JobStatus.STOP_REQUESTED, JobStatus.PAUSED} and time.time() - t0 < 3.0:
        time.sleep(0.02)

    assert ctrl.status in {JobStatus.STOPPED, JobStatus.COMPLETED}
    mock_producer.stop.assert_awaited_once()


@patch("nocpro_mock.jobs.job_manager.AIOKafkaProducer")
def test_topology_publish_job(mock_producer_cls, temp_state_dir: Path, tmp_path: Path):
    mock_producer = AsyncMock()
    mock_producer_cls.return_value = mock_producer

    topo_csv = tmp_path / "topoIP.csv"
    topo_csv.write_text("device_code,device_code_relation,source_class\nDEV_A,DEV_B,SITE_ROUTER\nDEV_B,DEV_C,SITE_ROUTER\n")

    manager = JobManager(state_dir=temp_state_dir)
    record = manager.submit_topology_publish_job(
        profile_id="IP_NETWORK",
        source_path=topo_csv,
        bootstrap_servers="localhost:9092",
    )

    ctrl = manager.get_controller(record.job_id)
    assert ctrl is not None
    import time
    t0 = time.time()
    while ctrl.status in {JobStatus.PENDING, JobStatus.RUNNING} and time.time() - t0 < 5.0:
        time.sleep(0.05)

    assert ctrl.status == JobStatus.COMPLETED
    assert ctrl.record.result is not None
    assert ctrl.record.result["profile_id"] == "IP_NETWORK"
    assert ctrl.record.result["topology_version"].startswith("ip-")
    mock_producer.start.assert_awaited_once()
    mock_producer.stop.assert_awaited_once()
