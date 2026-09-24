"""Small, optional OpenTelemetry boundary for API latency diagnostics.

Telemetry is disabled by default. Attributes are allow-listed and never include
snapshot IDs, chain IDs, fingerprints, alarm values, request bodies, or prompts.
"""

from __future__ import annotations

from contextlib import contextmanager
import contextvars
import logging
import math
import os
from threading import Lock
from typing import Any, Iterator


LOGGER = logging.getLogger(__name__)
_SAFE_ATTRIBUTE_KEYS = {
    "http.route",
    "http.request.method",
    "http.response.status_code",
    "stage",
    "workload",
    "cache.state",
}
_HISTOGRAM_NAMES = (
    "api.request.duration",
    "db.read.duration",
    "analysis.queue.wait",
    "analysis.compute.duration",
    "provider.duration",
    "event_loop.lag",
    "quality.freshness.lag",
)
_COUNTER_NAMES = (
    "analysis.queue.rejected",
    "quality.job.submitted",
    "cache.hit",
    "cache.miss",
)
_ACTIVE: contextvars.ContextVar["RuntimeObservability | None"] = contextvars.ContextVar(
    "nocpro_active_observability", default=None
)
_manager_lock = Lock()
_process_runtime: "RuntimeObservability | None" = None
_process_references = 0


def _safe_attributes(attributes: dict[str, Any] | None) -> dict[str, str | int | float | bool]:
    result: dict[str, str | int | float | bool] = {}
    for key, value in (attributes or {}).items():
        if key not in _SAFE_ATTRIBUTE_KEYS or not isinstance(value, (str, int, float, bool)):
            continue
        if isinstance(value, str) and len(value) > 128:
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        result[key] = value
    return result


class RuntimeObservability:
    """One process runtime; the disabled instance has no SDK dependency."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        server_timing: bool = False,
        tracer: Any = None,
        meter: Any = None,
        trace_api: Any = None,
        context_api: Any = None,
        propagator: Any = None,
        tracer_provider: Any = None,
        meter_provider: Any = None,
    ) -> None:
        self.enabled = enabled
        self.server_timing = server_timing
        self._tracer = tracer
        self._meter = meter
        self._trace_api = trace_api
        self._context_api = context_api
        self._propagator = propagator
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._histograms: dict[str, Any] = {}
        self._counters: dict[str, Any] = {}
        if enabled and meter is not None:
            for name in _HISTOGRAM_NAMES:
                self._histograms[name] = meter.create_histogram(name, unit="s")
            for name in _COUNTER_NAMES:
                self._counters[name] = meter.create_counter(name)

    @classmethod
    def disabled_from_environment(cls) -> "RuntimeObservability":
        return cls(
            server_timing=os.environ.get("NOCPRO_SERVER_TIMING_ENABLED", "false").lower()
            in {"1", "true", "yes"}
        )

    @classmethod
    def configure_from_environment(cls) -> "RuntimeObservability":
        server_timing = os.environ.get("NOCPRO_SERVER_TIMING_ENABLED", "false").lower() in {
            "1", "true", "yes"
        }
        if os.environ.get("NOCPRO_TELEMETRY_ENABLED", "false").lower() not in {
            "1", "true", "yes"
        }:
            return cls(server_timing=server_timing)

        try:
            from opentelemetry import context as context_api
            from opentelemetry import trace as trace_api
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.trace.propagation.tracecontext import (
                TraceContextTextMapPropagator,
            )

            build_version = os.environ.get("HINDSIGHT_BUILD_VERSION", "unknown")
            if (
                not build_version
                or len(build_version) > 64
                or not all(char.isalnum() or char in ".-_+" for char in build_version)
            ):
                build_version = "unknown"
            resource = Resource.create(
                {
                    "service.name": "hindsight-nocpro-api",
                    "service.version": build_version,
                }
            )
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(timeout=2.0),
                    max_queue_size=256,
                    max_export_batch_size=64,
                    schedule_delay_millis=1_000,
                    export_timeout_millis=2_000,
                )
            )
            metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(timeout=2.0),
                export_interval_millis=10_000,
                export_timeout_millis=2_000,
            )
            meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
            return cls(
                enabled=True,
                server_timing=server_timing,
                tracer=tracer_provider.get_tracer("nocpro.api"),
                meter=meter_provider.get_meter("nocpro.api"),
                trace_api=trace_api,
                context_api=context_api,
                propagator=TraceContextTextMapPropagator(),
                tracer_provider=tracer_provider,
                meter_provider=meter_provider,
            )
        except Exception:
            # Exporter/SDK configuration must never prevent the API from serving.
            LOGGER.warning("OpenTelemetry could not be configured; continuing without telemetry")
            return cls(server_timing=server_timing)

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
        if not self.enabled or self._tracer is None:
            yield None
            return
        with self._tracer.start_as_current_span(name) as span:
            for key, value in _safe_attributes(attributes).items():
                span.set_attribute(key, value)
            try:
                yield span
            except BaseException:
                try:
                    span.set_status(self._trace_api.Status(self._trace_api.StatusCode.ERROR))
                except Exception:
                    pass
                raise

    def attach_remote_context(self, headers: Any) -> Any:
        if not self.enabled or self._propagator is None:
            return None
        try:
            carrier = {
                key.lower(): value
                for key, value in headers.items()
                if key.lower() in {"traceparent", "tracestate"}
            }
            return self._context_api.attach(self._propagator.extract(carrier))
        except Exception:
            return None

    def detach_remote_context(self, token: Any) -> None:
        if token is None or self._context_api is None:
            return
        try:
            self._context_api.detach(token)
        except Exception:
            pass

    def record_duration(
        self,
        name: str,
        seconds: float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or name not in self._histograms:
            return
        if not math.isfinite(seconds) or seconds < 0:
            return
        try:
            self._histograms[name].record(seconds, attributes=_safe_attributes(attributes))
        except Exception:
            LOGGER.debug("OpenTelemetry metric recording failed")

    def record_counter(
        self,
        name: str,
        value: int = 1,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or name not in self._counters or value < 0:
            return
        try:
            self._counters[name].add(value, attributes=_safe_attributes(attributes))
        except Exception:
            LOGGER.debug("OpenTelemetry counter recording failed")

    def shutdown(self) -> None:
        for provider in (self._meter_provider, self._tracer_provider):
            if provider is None:
                continue
            try:
                provider.force_flush(timeout_millis=500)
                provider.shutdown()
            except Exception:
                LOGGER.warning("OpenTelemetry shutdown did not complete cleanly")


def acquire_observability() -> RuntimeObservability:
    """Share a single SDK provider pair across app instances in this process."""
    global _process_runtime, _process_references
    with _manager_lock:
        if _process_runtime is None:
            _process_runtime = RuntimeObservability.configure_from_environment()
        _process_references += 1
        return _process_runtime


def release_observability(runtime: RuntimeObservability) -> None:
    global _process_runtime, _process_references
    should_close = False
    with _manager_lock:
        if runtime is not _process_runtime:
            return
        _process_references = max(0, _process_references - 1)
        if _process_references == 0:
            _process_runtime = None
            should_close = True
    if should_close:
        runtime.shutdown()


def set_active_observability(runtime: RuntimeObservability):
    return _ACTIVE.set(runtime)


def reset_active_observability(token: contextvars.Token) -> None:
    _ACTIVE.reset(token)


def active_observability() -> RuntimeObservability | None:
    active = _ACTIVE.get()
    if active is not None:
        return active
    with _manager_lock:
        return _process_runtime
