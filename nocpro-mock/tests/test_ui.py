"""Unit tests for NocPro Mock Web UI and API endpoints."""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import pytest

from nocpro_mock.ui.server import start_server_in_thread


@pytest.fixture(scope="module")
def ui_server():
    server, base_url = start_server_in_thread(host="127.0.0.1", port=0)
    yield base_url
    server.shutdown()
    server.server_close()


def _request_json(url: str, method: str = "GET", data: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8") if data is not None else None

    try:
        with urllib.request.urlopen(req, data=body, timeout=5) as response:
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
        data={"kafka_bootstrap": "127.0.0.1:65432"},  # unused port
    )
    assert status == 200
    assert data["ok"] is False  # expected offline on unused port
    assert "bootstrap" in data


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


def test_api_preview_real(ui_server: str):
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


def test_api_publish_unreachable_kafka(ui_server: str):
    # Publishing to an unreachable port should fail gracefully without crashing server
    status, data = _request_json(
        f"{ui_server}/api/publish",
        method="POST",
        data={
            "mode": "golden",
            "snapshot_version": "1",
            "kafka_bootstrap": "127.0.0.1:65432",
            "kafka_topic": "test.topic",
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
