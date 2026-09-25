"""Tests for the Analysis Configuration and Calibration API endpoints."""

from __future__ import annotations

import asyncio
import os
import httpx2
import pytest
from sqlalchemy.engine import make_url

from nocpro_api import create_app


@pytest.fixture
def app():
    return create_app()


def test_get_config(app) -> None:
    async def exercise() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/api/v1/config")
            assert resp.status_code == 200
            data = resp.json()
            assert "config_version" in data
            assert "status" in data
            assert "editable_parameters" in data
            assert "parameters_detail" in data
            
            params = data["editable_parameters"]
            assert "s_min" in params
            assert "s_weak" in params
            assert "rho" in params
            assert "gap_seconds" in params
            assert params["s_min"] == 0.6
            assert params["s_weak"] == 0.3
            assert params["rho"] == 0.2
            assert params["gap_seconds"] == 120

    asyncio.run(exercise())


def test_update_config_valid_and_cache_isolation(app) -> None:
    async def exercise() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Update parameters
            resp = await client.post(
                "/api/v1/config",
                json={
                    "parameters": {
                        "s_min": 0.65,
                        "s_weak": 0.35,
                        "gap_seconds": 90,
                    }
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "custom-1" in data["config_version"]
            assert data["editable_parameters"]["s_min"] == 0.65
            assert data["editable_parameters"]["s_weak"] == 0.35
            assert data["editable_parameters"]["gap_seconds"] == 90

            # 2. Update again -> increment version
            resp2 = await client.post(
                "/api/v1/config",
                json={
                    "parameters": {
                        "s_min": 0.70,
                    }
                },
            )
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert "custom-2" in data2["config_version"]
            assert data2["editable_parameters"]["s_min"] == 0.70
            assert data2["editable_parameters"]["s_weak"] == 0.35

            # 3. Reset back to baseline
            resp_reset = await client.post("/api/v1/config/reset")
            assert resp_reset.status_code == 200
            data_reset = resp_reset.json()
            assert "custom" not in data_reset["config_version"]
            assert data_reset["editable_parameters"]["s_min"] == 0.6
            assert data_reset["editable_parameters"]["s_weak"] == 0.3

    asyncio.run(exercise())


def test_update_config_validation_failures(app) -> None:
    async def exercise() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # s_weak > s_min must fail
            resp = await client.post(
                "/api/v1/config",
                json={
                    "parameters": {
                        "s_min": 0.20,
                        "s_weak": 0.50,
                    }
                },
            )
            assert resp.status_code == 422

            # Out of bounds (> 1.0) must fail
            resp2 = await client.post(
                "/api/v1/config",
                json={
                    "parameters": {
                        "s_min": 1.50,
                    }
                },
            )
            assert resp2.status_code == 422

            # Negative gap_seconds must fail
            resp3 = await client.post(
                "/api/v1/config",
                json={
                    "parameters": {
                        "gap_seconds": -10,
                    }
                },
            )
            assert resp3.status_code == 422

    asyncio.run(exercise())


@pytest.mark.postgres
def test_calibrate_config_endpoint(app, monkeypatch, tmp_path) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if make_url(database_url).get_backend_name() != "postgresql":
        pytest.skip("TEST_DATABASE_URL must point to PostgreSQL")

    from benchmarks import calibrate_thresholds

    monkeypatch.setattr(calibrate_thresholds, "DEFAULT_DATABASE_URL", database_url)
    temp_yaml = tmp_path / "calibrated.yaml"
    temp_report = tmp_path / "calibration_report.json"
    monkeypatch.setattr(calibrate_thresholds, "DEFAULT_REPORT_JSON", temp_report)
    monkeypatch.setenv("NOCPRO_CALIBRATED_OUTPUT_PATH", str(temp_yaml))

    async def exercise() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post("/api/v1/config/calibrate")
            assert resp.status_code == 200
            data = resp.json()
            assert "timestamp" in data
            assert "database_url_masked" in data
            assert "calibrated_parameters" in data
            assert len(data["calibrated_parameters"]) > 0

            # Verify active config updated
            config_resp = await client.get("/api/v1/config")
            assert config_resp.status_code == 200
            config_data = config_resp.json()
            assert "v1-calibrated" in config_data["config_version"]
            assert temp_yaml.exists()
            assert temp_report.exists()

    asyncio.run(exercise())
