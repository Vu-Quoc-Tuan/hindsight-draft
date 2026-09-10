"""Unit tests for NocPro Mock Web UI and API endpoints."""

from __future__ import annotations

import json
from pathlib import Path
import urllib.request
import urllib.error
import pytest

from nocpro_mock.ui.server import start_server_in_thread


@pytest.fixture(scope="module")
def ui_server():
    server, base_url = start_server_in_thread(host="127.0.0.1", port=0, default_kafka="127.0.0.1:59999")
    yield base_url
    server.shutdown()
    server.server_close()


def _request_json(url: str, method: str = "GET", data: dict | None = None, timeout: float = 15.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8") if data is not None else None

    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as response:
            status = response.status
            content = json.loads(response.read().decode("utf-8"))
            return status, content
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            content = json.loads(exc.read().decode("utf-8"))
        except Exception:
            content = {"error": str(exc)}
        return status, content


def test_ui_index_html(ui_server: str):
    req = urllib.request.Request(f"{ui_server}/")
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
        assert "text/html" in response.headers.get("Content-Type", "")
        html = response.read().decode("utf-8")
        assert "NOCPRO MOCK" in html
        assert "Push to Kafka" in html
        assert "btn-push-kafka" in html


def test_api_status(ui_server: str):
    status, data = _request_json(f"{ui_server}/api/status")
    assert status == 200
    assert data["ok"] is True
    assert "datasets" in data
    assert "sequences" in data
    assert "defaults" in data
    assert data["defaults"]["kafka_topic"] == "nocpro.snapshot.v1"


def test_api_check_kafka(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/check-kafka",
        method="POST",
        data={},
    )
    assert status == 200
    assert data["ok"] is False  # expected offline on unused port
    assert "bootstrap" in data


def test_api_rejects_client_selected_kafka_destination(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/check-kafka",
        method="POST",
        data={"kafka_bootstrap": "127.0.0.1:65432"},
    )
    assert status == 400
    assert "configured by the Mock server" in data["error"]


def test_api_preview_golden(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/preview",
        method="POST",
        data={
            "mode": "golden",
            "snapshot_version": "1",
            "with_topology": False,
        },
    )
    assert status == 200
    assert data["ok"] is True
    preview = data["preview"]
    assert preview["snapshot_id"] == "snapshot_golden_2214039"
    assert preview["counts"]["chains"] > 0
    assert preview["counts"]["alarms"] == 0
    assert preview["contract_valid"] is True
    assert len(preview["sha256_checksum"]) == 64
    assert len(preview["sample_chains"]) > 0


@pytest.mark.realdata
def test_api_preview_real(ui_server: str, alarm_csv):
    status, data = _request_json(
        f"{ui_server}/api/preview",
        method="POST",
        data={
            "mode": "real",
            "snapshot_id": "test_real_001",
            "snapshot_version": "1",
            "limit": 10,
        },
    )
    assert status == 200
    assert data["ok"] is True
    preview = data["preview"]
    assert preview["snapshot_id"] == "test_real_001"
    assert preview["counts"]["alarms"] == 10
    assert len(preview["sample_alarms"]) == 10


def test_api_preview_sequence(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/preview",
        method="POST",
        data={
            "mode": "sequence",
            "sequence_path": "docs/examples/synthetic/history_positive_lift",
            "sequence_snapshot": "snapshot_000.json",
        },
    )
    assert status == 200
    assert data["ok"] is True
    preview = data["preview"]
    assert preview["counts"]["alarms"] > 0
    assert preview["counts"]["chains"] > 0


def test_api_preview_missing_file_error(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/preview",
        method="POST",
        data={
            "mode": "sequence",
            "sequence_path": "docs/examples/synthetic/does_not_exist",
            "sequence_snapshot": "missing.json",
        },
    )
    assert status == 400
    assert data["ok"] is False
    assert "not found" in data["error"].lower()


def test_api_preview_rejects_paths_outside_mock_datasets(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/preview",
        method="POST",
        data={"mode": "real", "alarm_csv": "/etc/passwd"},
    )
    assert status == 400
    assert "outside approved" in data["error"].lower()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "mode": "sequence",
            "sequence_path": "docs/examples/synthetic/history_positive_lift",
            "sequence_snapshot": "/etc/passwd",
        },
        {
            "mode": "sequence",
            "sequence_path": "docs/examples/synthetic/history_positive_lift",
            "sequence_snapshot": "../../golden_2214039/system_metadata.json",
        },
        {"mode": "golden", "fixture_dir": "/etc"},
    ],
)
def test_api_preview_rejects_path_escape_after_mode_specific_resolution(
    ui_server: str, payload: dict
):
    status, data = _request_json(f"{ui_server}/api/preview", method="POST", data=payload)
    assert status == 400
    assert "outside approved" in data["error"].lower() or "relative file" in data["error"].lower()


def test_api_rejects_non_object_json_payload(ui_server: str):
    req = urllib.request.Request(f"{ui_server}/api/preview", method="POST", data=b"[]")
    req.add_header("Content-Type", "application/json")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(req, timeout=5)
    assert error.value.code == 400
    assert "object" in error.value.read().decode("utf-8").lower()


@pytest.mark.parametrize("chunk_target_bytes", [0, -1, "not-a-number", 4 * 1024 * 1024 + 1])
def test_api_rejects_invalid_chunk_target_bytes(ui_server: str, chunk_target_bytes: object):
    status, data = _request_json(
        f"{ui_server}/api/preview",
        method="POST",
        data={"mode": "golden", "chunk_target_bytes": chunk_target_bytes},
    )
    assert status == 400
    assert "chunk_target_bytes" in data["error"]


def test_mock_preview_template_does_not_interpolate_untrusted_fields_as_html():
    from nocpro_mock.ui.server import ASSETS_DIR

    source = (ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    for unsafe_interpolation in (
        "${a.alarm_id}",
        "${a.alarm_name}",
        "${a.device_code}",
        "${a.node_reference}",
        "${c.chain_id}",
        "${c.chain_name}",
        "${text}</span>",
    ):
        assert unsafe_interpolation not in source


def test_api_publish_unreachable_kafka(ui_server: str):
    # Publishing to an unreachable port should fail gracefully without crashing server
    status, data = _request_json(
        f"{ui_server}/api/publish",
        method="POST",
        data={
            "mode": "golden",
            "snapshot_version": "1",
        },
    )
    assert status == 500
    assert data["ok"] is False
    assert "kafka publish failed" in data["error"].lower()


def test_api_topology_profiles(ui_server: str):
    status, data = _request_json(f"{ui_server}/api/topology/profiles")
    assert status == 200
    assert "profiles" in data
    assert len(data["profiles"]) == 3
    profile_ids = {p["profile_id"] for p in data["profiles"]}
    assert "ALARM_ONLY" in profile_ids
    assert "IP_NETWORK" in profile_ids
    assert "IT_SERVICES" in profile_ids


def test_api_topology_projection(ui_server: str):
    # Test with profile_id
    status, data = _request_json(f"{ui_server}/api/topology/projection?profile_id=ALARM_ONLY")
    assert status == 200
    assert data["status"] == "UNAVAILABLE"
    assert data["reason"] == "TOPOLOGY_NOT_PROVIDED_BY_DATASET_PROFILE"

    # Test with profile parameter alias
    status, data = _request_json(f"{ui_server}/api/topology/projection?profile=ALARM_ONLY")
    assert status == 200
    assert data["status"] == "UNAVAILABLE"

    # Test missing profile parameter
    status, data = _request_json(f"{ui_server}/api/topology/projection")
    assert status == 400
    assert "required" in data["error"].lower()


def test_ui_contains_topology_and_slicer_components(ui_server: str):
    req = urllib.request.Request(f"{ui_server}/")
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
        html = response.read().decode("utf-8")
        assert "nav-btn-topology" in html
        assert "nav-btn-slicer" in html
        assert "view-topology-section" in html
        assert "view-slicer-section" in html
        assert "btn-run-slicer" in html
        assert "btn-stream-sequence" in html
        assert "select-slicer-alarm-csv" in html
        assert "alarmIT.csv" in html
        assert "IT_SERVICES" in html
        assert "snapshot-select" in html
        assert "btn-publish-single-snapshot" in html
        assert "Topology Explorer" in html
        assert "Sequence Slicer" in html


def test_api_slice_sequence_rejects_invalid_scenario_id(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/slice-sequence",
        method="POST",
        data={"scenario_id": "../../../invalid_scenario"},
    )
    assert status == 400
    assert "scenario_id" in data["error"]


def test_api_slice_sequence_rejects_missing_alarm_file(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/slice-sequence",
        method="POST",
        data={"scenario_id": "test_seq", "alarm_csv": "datasets/raw/alarm/missing.csv"},
    )
    assert status == 400
    assert "not found" in data["error"].lower()


@pytest.mark.realdata
def test_api_slice_sequence_valid(ui_server: str, alarm_csv):
    status, data = _request_json(
        f"{ui_server}/api/slice-sequence",
        method="POST",
        data={
            "scenario_id": "test_ui_evolution_seq",
            "num_snapshots": 2,
            "step_minutes": 5,
            "window_minutes": 10,
            "max_chains": 10,
        },
    )
    assert status == 200
    assert data["ok"] is True
    assert "summary" in data
    assert data["summary"]["snapshot_count"] == 2
    assert data["summary"]["total_distinct_alarms"] > 0
    assert "sequences" in data
    seq_ids = [s["id"] for s in data["sequences"]]
    assert "test_ui_evolution_seq" in seq_ids


def test_api_publish_sequence_rejects_missing_directory(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/publish-sequence",
        method="POST",
        data={"sequence_path": "docs/examples/synthetic/does_not_exist"},
    )
    assert status == 400
    assert "not found" in data["error"].lower()


def test_api_publish_sequence_rejects_custom_bootstrap(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/publish-sequence",
        method="POST",
        data={
            "sequence_path": "docs/examples/synthetic/history_positive_lift",
            "kafka_bootstrap": "127.0.0.1:9999",
        },
    )
    assert status == 400
    assert "configured by the Mock server" in data["error"]


def test_api_publish_sequence_unreachable_kafka(ui_server: str):
    status, data = _request_json(
        f"{ui_server}/api/publish-sequence",
        method="POST",
        data={"sequence_path": "docs/examples/synthetic/history_positive_lift"},
    )
    assert status == 500
    assert data["ok"] is False
    assert "kafka publish failed" in data["error"].lower()


def test_api_mock_studio_subpath_normalization(ui_server: str):
    status, data = _request_json(f"{ui_server}/mock-studio/api/status")
    assert status == 200
    assert data["ok"] is True
    assert "datasets" in data


def test_mock_studio_trailing_slash_redirect(ui_server: str):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def http_error_301(self, req, fp, code, msg, headers):
            return fp

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(f"{ui_server}/mock-studio")
    try:
        resp = opener.open(req)
        assert resp.status in (301, 308)
        assert resp.headers.get("Location") == "/mock-studio/"
    except urllib.error.HTTPError as err:
        assert err.code in (301, 308)
        assert err.headers.get("Location") == "/mock-studio/"


def test_api_datasets(ui_server: str):
    status, data = _request_json(f"{ui_server}/api/datasets")
    assert status == 200
    assert data["ok"] is True
    assert "datasets" in data
    ids = [d["id"] for d in data["datasets"]]
    assert "alarm_data" in ids
    assert "alarm_ip" in ids
    assert "alarm_it" in ids
    assert "topo_ip" not in ids
    assert "topo_it" not in ids


def test_api_topology_metadata(ui_server: str):
    status, data = _request_json(f"{ui_server}/api/topology/metadata?profile_id=IP_NETWORK")
    assert status == 200
    assert data["ok"] is True
    meta = data["metadata"]
    assert meta["profile_id"] == "IP_NETWORK"
    assert meta["capabilities"]["relation_model"] == "PHYSICAL_ADJACENCY"
    assert meta["capabilities"]["p2_eligible"] is False
    assert meta["capabilities"]["alarm_mapping"] == "PARTIAL_EXACT"
    assert meta["stats"]["node_count"] == 99780
    assert meta["stats"]["edge_count"] == 110916
    assert meta["stats"]["alias_count"] == 0

    # IT Services
    status_it, data_it = _request_json(f"{ui_server}/api/topology/metadata?profile_id=IT_SERVICES")
    assert status_it == 200
    meta_it = data_it["metadata"]
    assert meta_it["capabilities"]["relation_model"] == "SOURCE_RELATION"
    assert meta_it["capabilities"]["alarm_mapping"] == "UNAVAILABLE"
    assert meta_it["stats"]["node_count"] == 128322
    assert meta_it["stats"]["edge_count"] == 218635
    assert meta_it["stats"]["alias_count"] == 111472
    assert meta_it["canonical_version"].startswith("it-")


def test_api_jobs_lifecycle_and_conflict(ui_server: str):
    # Submit a slice job
    status, data = _request_json(
        f"{ui_server}/api/slice-jobs",
        method="POST",
        data={
            "scenario_id": "test_api_slice_01",
            "num_snapshots": 1,
            "step_minutes": 5,
            "window_minutes": 15,
        },
    )
    assert status in (202, 409)
    if status == 202:
        job = data["job"]
        job_id = job["job_id"]

        # Query job
        status_q, data_q = _request_json(f"{ui_server}/api/jobs/{job_id}")
        assert status_q == 200
        assert data_q["job"]["job_id"] == job_id

        # Query list
        status_l, data_l = _request_json(f"{ui_server}/api/jobs")
        assert status_l == 200
        assert any(j["job_id"] == job_id for j in data_l["jobs"])


def test_api_alarms_and_facets_and_detail(ui_server: str):
    # Query facets
    status_f, data_f = _request_json(f"{ui_server}/api/alarm-facets?dataset_id=alarm_data")
    assert status_f == 200
    assert data_f["ok"] is True
    assert "facets" in data_f

    # Query alarms
    status_a, data_a = _request_json(f"{ui_server}/api/alarms?dataset_id=alarm_data&limit=10")
    assert status_a == 200
    assert data_a["ok"] is True
    assert len(data_a["items"]) > 0
    assert data_a["sort"] == {
        "field": "canonical_start_time",
        "direction": "ASC",
        "nulls": "LAST",
        "tie_breaker": "logical_row",
    }
    column_keys = [column["key"] for column in data_a["columns"]]
    assert "alarm_id" in column_keys
    assert "content" not in column_keys
    assert all(all(key in item for key in column_keys) for item in data_a["items"])
    sort_keys = [
        (item["canonical_start_time"] is None, item["canonical_start_time"] or "", item["logical_row"])
        for item in data_a["items"]
    ]
    assert sort_keys == sorted(sort_keys)
    first_item = data_a["items"][0]
    row_id = first_item["logical_row"]

    # Query detail
    status_d, data_d = _request_json(f"{ui_server}/api/alarms/alarm_data/{row_id}")
    assert status_d == 200
    assert data_d["ok"] is True
    assert "canonical" in data_d["detail"]
    assert "raw" in data_d["detail"]
    assert len(data_d["detail"]["raw"]) >= 20
    # ALARM_ONLY has UNAVAILABLE mapping capability invariant
    assert first_item["mapping_status"] == "UNAVAILABLE"
    assert data_a["dataset_id"] == "alarm_data"

    # Query with mapping_status filter
    status_m, data_m = _request_json(f"{ui_server}/api/alarms?dataset_id=alarm_data&mapping_status=UNAVAILABLE&limit=5")
    assert status_m == 200
    assert data_m["ok"] is True
    assert len(data_m["items"]) > 0
    assert all(item["mapping_status"] == "UNAVAILABLE" for item in data_m["items"])

    # Query with non-matching mapping_status
    status_none, data_none = _request_json(f"{ui_server}/api/alarms?dataset_id=alarm_data&mapping_status=EXACT&limit=5")
    assert status_none == 200
    assert len(data_none["items"]) == 0

    # Query with time filter
    start_val = first_item["canonical_start_time"]
    if start_val:
        import urllib.parse
        status_t, data_t = _request_json(f"{ui_server}/api/alarms?dataset_id=alarm_data&start_time={urllib.parse.quote(start_val)}&limit=5")
        assert status_t == 200
        assert all(item["canonical_start_time"] >= start_val for item in data_t["items"])


def test_api_slice_job_it_services(ui_server: str):
    # Slice job accepts IT_SERVICES
    status, data = _request_json(
        f"{ui_server}/api/slice-jobs",
        method="POST",
        data={
            "scenario_id": "test_api_it_slice_01",
            "profile_id": "IT_SERVICES",
            "alarm_csv": "datasets/raw/alarm/alarmIT.csv",
            "num_snapshots": 1,
            "step_minutes": 5,
            "window_minutes": 15,
        },
    )
    assert status in (202, 409)
    if status == 202:
        assert data["ok"] is True
        assert data["job"]["params"]["profile_id"] == "IT_SERVICES"


@pytest.mark.realdata
def test_api_alarms_real_ip_dataset(ui_server: str):
    if not Path("datasets/raw/alarm/alarmIP.csv").is_file():
        pytest.skip("alarmIP.csv missing")
    status_ip, data_ip = _request_json(f"{ui_server}/api/alarms?dataset_id=alarm_ip&limit=5", timeout=60.0)
    assert status_ip == 200
    assert data_ip["ok"] is True
    assert data_ip["dataset_id"] == "alarm_ip"
    assert len(data_ip["items"]) > 0


def test_api_csrf_and_origin_protection(ui_server: str):
    # Cross-site mutating request rejected
    req = urllib.request.Request(
        f"{ui_server}/api/check-kafka",
        data=b"{}",
        headers={"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 403

    # Untrusted origin rejected
    req2 = urllib.request.Request(
        f"{ui_server}/api/check-kafka",
        data=b"{}",
        headers={"Content-Type": "application/json", "Origin": "http://evil-attacker.com"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc2:
        urllib.request.urlopen(req2)
    assert exc2.value.code == 403


def test_api_sse_stream_initial_init_event(ui_server: str):
    # Submit job
    status, data = _request_json(
        f"{ui_server}/api/slice-jobs",
        method="POST",
        data={"scenario_id": "test_sse_init", "num_snapshots": 1},
    )
    assert status in (202, 409)
    if status == 202:
        job_id = data["job"]["job_id"]
        # Connect to SSE
        req = urllib.request.Request(f"{ui_server}/api/jobs/{job_id}/events")
        with urllib.request.urlopen(req, timeout=5) as resp:
            line1 = resp.readline().decode("utf-8")
            assert "event: init" in line1
