from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx2

from nocpro_api import create_app
from nocpro_api.observability import (
    RuntimeObservability,
    _safe_attributes,
)
import nocpro_api.quality_freshness as quality_freshness
import nocpro_api.workspace as workspace_module
from nocpro_api.workspace import Workspace


def test_safe_attributes_drop_identifiers_and_unbounded_values() -> None:
    safe = _safe_attributes(
        {
            "http.route": "/api/v1/chains/{chain_id}/overview-cards",
            "http.request.method": "GET",
            "http.response.status_code": 200,
            "chain_id": "CHAIN-1",
            "snapshot_id": "SNAPSHOT-1",
            "fingerprint": "f" * 64,
            "alarm_value": "private payload",
            "stage": "overview-projection",
            "provider.prompt": "private prompt",
        }
    )
    assert safe == {
        "http.route": "/api/v1/chains/{chain_id}/overview-cards",
        "http.request.method": "GET",
        "http.response.status_code": 200,
        "stage": "overview-projection",
    }


def test_disabled_runtime_is_noop_and_server_timing_is_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("NOCPRO_TELEMETRY_ENABLED", "false")
    monkeypatch.setenv("NOCPRO_SERVER_TIMING_ENABLED", "false")
    runtime = RuntimeObservability.configure_from_environment()
    assert runtime.enabled is False
    assert runtime.server_timing is False
    runtime.record_duration("api.request.duration", 1.0, {"chain_id": "C1"})
    with runtime.span("test.span", {"snapshot_id": "S1"}) as span:
        assert span is None
    runtime.shutdown()


def test_optional_opentelemetry_extra_configures_one_runtime(monkeypatch) -> None:
    if (
        importlib.util.find_spec("opentelemetry") is None
        or importlib.util.find_spec("opentelemetry.sdk") is None
    ):
        import pytest

        pytest.skip("install the optional observability extra to exercise OTLP configuration")
    monkeypatch.setenv("NOCPRO_TELEMETRY_ENABLED", "true")
    runtime = RuntimeObservability.configure_from_environment()
    assert runtime.enabled is True
    assert runtime._tracer_provider is not None
    assert runtime._meter_provider is not None
    runtime.record_duration("api.request.duration", 0.001, {"http.route": "/api/v1/health"})
    runtime.shutdown()


def test_server_timing_header_is_disabled_by_default_and_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("TEST_DATABASE_URL", "")
    monkeypatch.setenv("AUTO_SEED_DEFAULT_SNAPSHOT", "false")
    monkeypatch.setenv("AUTO_CALIBRATE_ON_STARTUP", "false")
    monkeypatch.setenv("NOCPRO_TELEMETRY_ENABLED", "false")

    async def request(enabled: bool) -> str | None:
        monkeypatch.setenv("NOCPRO_SERVER_TIMING_ENABLED", "true" if enabled else "false")
        service = Workspace()
        app = create_app(workspace=service)
        try:
            async with app.router.lifespan_context(app):
                transport = httpx2.ASGITransport(app=app)
                async with httpx2.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    response = await client.get("/api/v1/health")
                    assert response.status_code == 200
                    assert response.json() == {"status": "ok"}
                    return response.headers.get("server-timing")
        finally:
            service.close()

    assert asyncio.run(request(False)) is None
    timing = asyncio.run(request(True))
    assert timing is not None
    assert timing.startswith("app;dur=")
    assert "CHAIN" not in timing and "SNAPSHOT" not in timing


def test_quality_freshness_metric_records_age_and_only_safe_attributes(monkeypatch) -> None:
    class RecordingObservability:
        def __init__(self):
            self.durations = []

        def record_duration(self, name, seconds, attributes):
            self.durations.append((name, seconds, attributes))

    recorder = RecordingObservability()
    monkeypatch.setattr(quality_freshness, "active_observability", lambda: recorder)
    row = SimpleNamespace(
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=7),
        snapshot_id="must-not-be-a-label",
        chain_id="must-not-be-a-label-either",
    )

    quality_freshness.record_quality_freshness_lag(
        row, stage="overview", state="current"
    )

    assert len(recorder.durations) == 1
    name, seconds, attributes = recorder.durations[0]
    assert name == "quality.freshness.lag"
    assert 6 <= seconds < 9
    assert attributes == {"stage": "overview", "cache.state": "current"}


def test_quality_freshness_skips_future_and_timezone_naive_timestamps(monkeypatch) -> None:
    class RecordingObservability:
        def __init__(self):
            self.durations = []

        def record_duration(self, *args, **kwargs):
            self.durations.append((args, kwargs))

    recorder = RecordingObservability()
    monkeypatch.setattr(quality_freshness, "active_observability", lambda: recorder)
    quality_freshness.record_quality_freshness_lag(
        SimpleNamespace(updated_at=datetime.now(timezone.utc) + timedelta(seconds=2)),
        stage="overview",
        state="current",
    )
    quality_freshness.record_quality_freshness_lag(
        SimpleNamespace(updated_at=datetime.now()),
        stage="overview",
        state="current",
    )
    assert recorder.durations == []


def test_quality_submission_metrics_distinguish_hit_dedup_and_new_job(monkeypatch) -> None:
    class RecordingObservability:
        def __init__(self):
            self.counters = []

        def record_counter(self, name, value=1, attributes=None):
            self.counters.append((name, value, attributes))

    recorder = RecordingObservability()
    monkeypatch.setattr(workspace_module, "active_observability", lambda: recorder)
    workspace_module._record_quality_submission(
        "review", SimpleNamespace(job_id="cache-hit", cache_hit=True, deduplicated=False)
    )
    workspace_module._record_quality_submission(
        "review", SimpleNamespace(job_id="same-running-job", cache_hit=False, deduplicated=True)
    )
    workspace_module._record_quality_submission(
        "deep-dive", SimpleNamespace(job_id="new-job", cache_hit=False, deduplicated=False)
    )

    assert recorder.counters == [
        ("cache.hit", 1, {"stage": "review", "cache.state": "hit"}),
        ("cache.miss", 1, {"stage": "review", "cache.state": "deduplicated"}),
        ("cache.miss", 1, {"stage": "deep-dive", "cache.state": "miss"}),
        ("quality.job.submitted", 1, {"stage": "deep-dive"}),
    ]
