"""Snapshot-bound async job and compatible-cache boundary for Review."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from channels.cross_chain import CrossChainEvidence
from libs.contracts import IngestedPackage
from tier2.jobs import JobStatus

from .analysis import analyze_counterfactual_review
from .models import ExternalValidationArtifact, ReviewIdentity
from .public_contract import public_review_result


ENGINE_VERSION = "counterfactual-p1-v1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, CrossChainEvidence):
        return value.as_payload()
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        values = [_jsonable(item) for item in value]
        return sorted(values, key=lambda item: json.dumps(item, sort_keys=True)) if isinstance(value, (set, frozenset)) else values
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _semantic_artifact(value: Any) -> Any:
    serialized = _jsonable(value)
    if isinstance(serialized, dict):
        return {
            key: _semantic_artifact(item)
            for key, item in serialized.items()
            if key not in {"phase_durations"}
        }
    if isinstance(serialized, list):
        return [_semantic_artifact(item) for item in serialized]
    return serialized


def artifact_fingerprint(value: Any) -> str:
    """Hash semantic content while excluding non-reproducible run telemetry."""
    payload = json.dumps(
        _semantic_artifact(value), sort_keys=True, separators=(",", ":")
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def review_identity(
    package: IngestedPackage,
    chain_id: str,
    *,
    analysis_version: str,
    config_version: str,
    tier1b_artifact: Any,
    audit_artifact: Any | None,
    external_artifact: ExternalValidationArtifact | None,
) -> ReviewIdentity:
    alarm_universe = artifact_fingerprint(tuple(sorted(package.alarms)))
    return ReviewIdentity(
        snapshot_id=package.snapshot.snapshot_id,
        snapshot_version=package.snapshot.snapshot_version,
        chain_id=chain_id,
        alarm_universe_fingerprint=alarm_universe,
        analysis_version=analysis_version,
        engine_version=ENGINE_VERSION,
        config_version=config_version,
        tier1b_artifact_fingerprint=artifact_fingerprint(tier1b_artifact),
        structural_audit_artifact_fingerprint=(
            getattr(audit_artifact, "artifact_fingerprint", None)
            or artifact_fingerprint(audit_artifact)
            if audit_artifact is not None
            else None
        ),
        external_validation_artifact_fingerprint=(
            external_artifact.fingerprint if external_artifact is not None else None
        ),
    )


@dataclass(frozen=True)
class CounterfactualSubmission:
    job_id: str
    cache_hit: bool
    deduplicated: bool


@dataclass(frozen=True)
class CounterfactualJobView:
    job_id: str
    chain_id: str
    identity: ReviewIdentity
    status: JobStatus
    progress_percent: int
    cache_hit: bool
    result: Any | None = None
    error: str | None = None

    @property
    def cache_fingerprint(self) -> str:
        return artifact_fingerprint(self.identity.cache_tuple())

    def persistence_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "snapshot_id": self.identity.snapshot_id,
            "snapshot_version": self.identity.snapshot_version,
            "chain_id": self.chain_id,
            "cache_fingerprint": self.cache_fingerprint,
            "status": self.status.value,
            "progress_percent": self.progress_percent,
            "cache_hit": self.cache_hit,
            "identity": _jsonable(self.identity),
            "result": (
                public_review_result(self.result)
                if self.result is not None
                else None
            ),
            "error": self.error,
        }


@dataclass
class _MutableJob:
    job_id: str
    chain_id: str
    identity: ReviewIdentity
    status: JobStatus
    progress_percent: int
    cache_hit: bool
    result: Any | None = None
    error: str | None = None

    def view(self) -> CounterfactualJobView:
        return CounterfactualJobView(**vars(self))


class CounterfactualJobManager:
    """Separate Review executor; Tier-2 Audit never triggers this manager."""

    def __init__(
        self,
        *,
        analyzer: Callable[..., Any] = analyze_counterfactual_review,
        max_workers: int = 2,
        metric_computer=None,
        state_listener: Callable[[CounterfactualJobView], None] | None = None,
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._analyzer = analyzer
        self._metric_computer = metric_computer
        self._state_listener = state_listener
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="nocpro-counterfactual"
        )
        self._lock = RLock()
        self._jobs: dict[str, _MutableJob] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._inflight_by_key: dict[tuple[str, ...], str] = {}
        self._cache: dict[tuple[str, ...], Any] = {}
        self._latest_succeeded: dict[tuple[str, str, str], str] = {}

    def set_state_listener(
        self, listener: Callable[[CounterfactualJobView], None] | None
    ) -> None:
        with self._lock:
            self._state_listener = listener

    def _notify(self, view: CounterfactualJobView) -> None:
        listener = self._state_listener
        if listener is not None:
            listener(view)

    def submit(
        self,
        package: IngestedPackage,
        chain_id: str,
        *,
        tier1b_artifact,
        audit_artifact,
        analysis_config,
        external_artifact: ExternalValidationArtifact | None = None,
    ) -> CounterfactualSubmission:
        if chain_id not in package.chains:
            raise KeyError(f"unknown chain_id {chain_id!r}")
        config = getattr(analysis_config, "counterfactual", None)
        config_version = (
            config.config_version if config is not None else "UNAVAILABLE"
        )
        identity = review_identity(
            package,
            chain_id,
            analysis_version=analysis_config.config_version,
            config_version=config_version,
            tier1b_artifact=tier1b_artifact,
            audit_artifact=audit_artifact,
            external_artifact=external_artifact,
        )
        key = identity.cache_tuple()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                job_id = uuid4().hex
                self._jobs[job_id] = _MutableJob(
                    job_id=job_id,
                    chain_id=chain_id,
                    identity=identity,
                    status=JobStatus.SUCCEEDED,
                    progress_percent=100,
                    cache_hit=True,
                    result=cached,
                )
                submission = CounterfactualSubmission(job_id, True, False)
                cached_view = self._jobs[job_id].view()
                self._latest_succeeded[
                    (identity.snapshot_id, identity.snapshot_version, chain_id)
                ] = job_id
                self._notify(cached_view)
                return submission
            existing = self._inflight_by_key.get(key)
            if existing is not None:
                return CounterfactualSubmission(existing, False, True)
            job_id = uuid4().hex
            self._jobs[job_id] = _MutableJob(
                job_id=job_id,
                chain_id=chain_id,
                identity=identity,
                status=JobStatus.QUEUED,
                progress_percent=5,
                cache_hit=False,
            )
            self._inflight_by_key[key] = job_id
            queued_view = self._jobs[job_id].view()
            self._notify(queued_view)
            self._futures[job_id] = self._executor.submit(
                self._run,
                job_id,
                package,
                tier1b_artifact,
                audit_artifact,
                analysis_config,
                external_artifact,
            )
        return CounterfactualSubmission(job_id, False, False)

    def _run(
        self,
        job_id: str,
        package: IngestedPackage,
        tier1b_artifact,
        audit_artifact,
        analysis_config,
        external_artifact,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.RUNNING
            job.progress_percent = 20
            running_view = job.view()
        self._notify(running_view)
        try:
            result = self._analyzer(
                package,
                job.chain_id,
                identity=job.identity,
                tier1b_artifact=tier1b_artifact,
                audit_artifact=audit_artifact,
                analysis_config=analysis_config,
                config=getattr(analysis_config, "counterfactual", None),
                config_reason=getattr(
                    analysis_config,
                    "counterfactual_reason",
                    "COUNTERFACTUAL_CONFIG_INCOMPLETE",
                ),
                external_artifact=external_artifact,
                metric_computer=self._metric_computer,
            )
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job.status = JobStatus.FAILED
                job.progress_percent = 100
                job.error = f"{type(exc).__name__}: {exc}"
                self._inflight_by_key.pop(job.identity.cache_tuple(), None)
                failed_view = job.view()
                # Publish terminal persistence before another thread can
                # observe the terminal in-memory state.
                self._notify(failed_view)
            return
        with self._lock:
            job = self._jobs[job_id]
            key = job.identity.cache_tuple()
            self._cache[key] = result
            job.result = result
            job.status = JobStatus.SUCCEEDED
            job.progress_percent = 100
            self._inflight_by_key.pop(key, None)
            self._latest_succeeded[
                (job.identity.snapshot_id, job.identity.snapshot_version, job.chain_id)
            ] = job_id
            succeeded_view = job.view()
            # Keep the manager lock until the listener has enqueued the
            # terminal persistence write. API reads can then flush it before
            # returning SUCCEEDED.
            self._notify(succeeded_view)

    def get(self, job_id: str) -> CounterfactualJobView:
        with self._lock:
            try:
                return self._jobs[job_id].view()
            except KeyError as exc:
                raise KeyError(f"unknown Counterfactual job_id {job_id!r}") from exc

    def latest(
        self, snapshot_id: str, snapshot_version: str, chain_id: str
    ) -> CounterfactualJobView | None:
        with self._lock:
            job_id = self._latest_succeeded.get(
                (snapshot_id, snapshot_version, chain_id)
            )
            return self._jobs[job_id].view() if job_id is not None else None

    def latest_compatible(
        self, identity: ReviewIdentity
    ) -> CounterfactualJobView | None:
        with self._lock:
            matches = [
                job.view()
                for job in self._jobs.values()
                if job.status is JobStatus.SUCCEEDED
                and job.identity.cache_tuple() == identity.cache_tuple()
            ]
        return matches[-1] if matches else None

    def wait(self, job_id: str, *, timeout: float | None = None) -> CounterfactualJobView:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"unknown Counterfactual job_id {job_id!r}")
            future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get(job_id)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
