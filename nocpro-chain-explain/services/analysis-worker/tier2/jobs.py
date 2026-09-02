"""Asynchronous, cached, per-chain Tier-2 job boundary (ADR-0023).

The manager is deliberately transport-agnostic.  An HTTP adapter may expose its
job IDs through polling or SSE later, while the analysis core retains the same
per-chain/cache semantics and Tier-1B never waits on this executor.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from channels import EMPTY_TAXONOMY, AlarmTaxonomy
from configuration import DependencyScopeConfig, PropagationConfig
from libs.contracts import IngestedPackage
from tier1a import CacheKey, CacheTier, Tier1Cache

from .audit_analysis import (
    AuditExecutionPolicy,
    SimilarityQueryContext,
    analyze_structural_audit,
)
from .topology_hypotheses.propagation import _configured_values
from .topology_hypotheses.scope_overlap import _limits


def _p2_cache_stamp(analysis_config: Any) -> str | None:
    """Return a deterministic stamp for every available P2 sub-config.

    Propagation has an explicit version, but the version alone is not enough:
    an operator can construct two envelopes with the same version while
    changing a value or its provenance.  Scope currently has no independent
    version field, so its configured values and provenance are included to
    prevent changing either ceiling from reusing an old Tier-2 result.  An
    absent/incomplete production P2 envelope contributes no suffix; this keeps
    the existing shipped ``v1`` cache identity while the result remains
    structured ``UNAVAILABLE``.
    """
    p2 = getattr(analysis_config, "p2_topology", None)
    if p2 is None:
        return None
    parts: list[str] = []
    propagation = getattr(p2, "propagation", None)
    if isinstance(propagation, PropagationConfig):
        numeric = _configured_values(propagation)
        propagation_fields = (
            (
                "restart_probability",
                propagation.restart_probability,
            ),
            (
                "convergence_tolerance",
                propagation.convergence_tolerance,
            ),
            ("max_iterations", propagation.max_iterations),
            ("decay_parameter", propagation.decay_parameter),
            ("score_threshold", propagation.score_threshold),
            ("max_candidate_edges", propagation.max_candidate_edges),
        )
        # Incomplete/unsupported envelopes deliberately produce no
        # propagation suffix.  That makes them unable to collide with a
        # complete available envelope, even when config_version is reused.
        if numeric is not None:
            identities = [
                f"{name}[path={getattr(configured, 'path')!r},"
                f"value={getattr(configured, 'value')!r},"
                f"source={getattr(getattr(configured, 'source'), 'value', getattr(configured, 'source'))!r}]"
                for name, configured in propagation_fields
            ]
            parts.append(
                "propagation:"
                f"version={propagation.config_version.strip()!r},"
                f"decay_type={propagation.decay_type!r},"
                + ",".join(identities)
            )
    scope = getattr(p2, "dependency_scope", None)
    if scope is None:
        pass
    elif isinstance(scope, DependencyScopeConfig) and _limits(scope) is not None:
        values = []
        for name in ("max_scope_resources", "max_materialized_resources"):
            configured = getattr(scope, name, None)
            if configured is None:
                continue
            source = getattr(getattr(configured, "source", None), "value", None)
            values.append(
                f"{name}={getattr(configured, 'value', None)!r}"
                f"[path={getattr(configured, 'path', None)!r},"
                f"source={source or getattr(configured, 'source', None)!r}]"
            )
        if values:
            parts.append("scope:" + ",".join(values))
    else:
        # Keep absent scope unsuffixed, but distinguish a concrete malformed
        # scope object from a valid propagation-only envelope.
        parts.append("scope:INVALID")
    return ";".join(parts) or None


def _attribution_evaluation_cache_stamp(analysis_config: Any) -> str:
    config = getattr(analysis_config, "attribution_evaluation", None)
    if config is None:
        reason = getattr(
            analysis_config,
            "attribution_evaluation_reason",
            "ATTRIBUTION_EVALUATION_CONFIG_INCOMPLETE",
        )
        return f"UNAVAILABLE:{reason}"
    seed = config.random_seed
    repetitions = config.random_repetitions
    return (
        f"algorithm={config.randomization_algorithm!r},"
        f"seed={seed.value!r}[source={seed.source.value!r}],"
        f"repetitions={repetitions.value!r}[source={repetitions.source.value!r}]"
    )


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Tier2Submission:
    job_id: str
    cache_hit: bool
    deduplicated: bool


@dataclass(frozen=True)
class Tier2JobView:
    job_id: str
    chain_id: str
    status: JobStatus
    progress_percent: int
    cache_hit: bool
    cache_key: CacheKey
    result: Any | None = None
    error: str | None = None


@dataclass
class _MutableJob:
    job_id: str
    chain_id: str
    status: JobStatus
    progress_percent: int
    cache_hit: bool
    cache_key: CacheKey
    result: Any | None = None
    error: str | None = None

    def view(self) -> Tier2JobView:
        return Tier2JobView(
            job_id=self.job_id,
            chain_id=self.chain_id,
            status=self.status,
            progress_percent=self.progress_percent,
            cache_hit=self.cache_hit,
            cache_key=self.cache_key,
            result=self.result,
            error=self.error,
        )


class Tier2JobManager:
    """Submit deep analysis without blocking Tier-1B interaction."""

    def __init__(
        self,
        *,
        cache: Tier1Cache | None = None,
        analyzer: Callable[..., Any] = analyze_structural_audit,
        max_workers: int = 2,
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self.cache = cache if cache is not None else Tier1Cache()
        self._analyzer = analyzer
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="nocpro-tier2"
        )
        self._lock = RLock()
        self._jobs: dict[str, _MutableJob] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._inflight_by_key: dict[tuple[str, str, str, str, str], str] = {}

    def submit(
        self,
        package: IngestedPackage,
        chain_id: str,
        *,
        analysis_config,
        taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
        dependency_edges: list[tuple[str, str, float]] | None = None,
        failure_domains: list[tuple[str, frozenset[str]]] | None = None,
        cross_block_negative_evidence: bool = False,
        similarity_context: SimilarityQueryContext | None = None,
    ) -> Tier2Submission:
        if chain_id not in package.chains:
            raise KeyError(f"unknown chain_id {chain_id!r}")
        members = set(package.members_of(chain_id))
        run_config_version = analysis_config.config_version
        if similarity_context is not None:
            run_config_version = (
                f"{run_config_version}|similarity:"
                f"{similarity_context.model.model_version}"
            )
        p2_stamp = _p2_cache_stamp(analysis_config)
        if p2_stamp is not None:
            run_config_version = f"{run_config_version}|p2:{p2_stamp}"
        run_config_version = (
            f"{run_config_version}|attribution-evaluation:"
            f"{_attribution_evaluation_cache_stamp(analysis_config)}"
        )
        key = self.cache.key_for(
            CacheTier.TIER_2,
            member_ids=members,
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            config_version=run_config_version,
        )
        cached = self.cache.get(key)
        if cached is not None:
            job_id = uuid4().hex
            with self._lock:
                self._jobs[job_id] = _MutableJob(
                    job_id=job_id,
                    chain_id=chain_id,
                    status=JobStatus.SUCCEEDED,
                    progress_percent=100,
                    cache_hit=True,
                    cache_key=key,
                    result=cached,
                )
            return Tier2Submission(job_id, cache_hit=True, deduplicated=False)

        key_tuple = key.as_tuple()
        with self._lock:
            existing = self._inflight_by_key.get(key_tuple)
            if existing is not None:
                return Tier2Submission(
                    existing, cache_hit=False, deduplicated=True
                )

            job_id = uuid4().hex
            self._jobs[job_id] = _MutableJob(
                job_id=job_id,
                chain_id=chain_id,
                status=JobStatus.QUEUED,
                progress_percent=5,
                cache_hit=False,
                cache_key=key,
            )
            self._inflight_by_key[key_tuple] = job_id
            future = self._executor.submit(
                self._run,
                job_id,
                package,
                chain_id,
                analysis_config,
                taxonomy,
                dependency_edges,
                failure_domains,
                cross_block_negative_evidence,
                similarity_context,
            )
            self._futures[job_id] = future
        return Tier2Submission(job_id, cache_hit=False, deduplicated=False)

    def _run(
        self,
        job_id: str,
        package: IngestedPackage,
        chain_id: str,
        analysis_config,
        taxonomy: AlarmTaxonomy,
        dependency_edges: list[tuple[str, str, float]] | None,
        failure_domains: list[tuple[str, frozenset[str]]] | None,
        cross_block_negative_evidence: bool,
        similarity_context: SimilarityQueryContext | None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.RUNNING
            job.progress_percent = 20
        try:
            result = self._analyzer(
                package,
                chain_id,
                policy=AuditExecutionPolicy(
                    exact_max_members=int(
                        analysis_config.value("audit.exact_max_members")
                    )
                ),
                mining_config=analysis_config.mining_config(),
                epsilon=float(
                    analysis_config.value("audit.global_weak_baseline")
                ),
                rho=float(analysis_config.value("audit.rho")),
                min_side_size=int(
                    analysis_config.value("audit.min_side_size")
                ),
                small_chain_threshold=int(
                    analysis_config.value("audit.small_chain_threshold")
                ),
                taxonomy=taxonomy,
                dependency_edges=dependency_edges,
                failure_domains=failure_domains,
                cross_block_negative_evidence=cross_block_negative_evidence,
                similarity_context=similarity_context,
                similarity_top_k=int(
                    analysis_config.value("similar_chains.result_top_k")
                ),
                p2_topology_config=getattr(analysis_config, "p2_topology", None),
                attribution_evaluation_config=getattr(
                    analysis_config, "attribution_evaluation", None
                ),
            )
        except Exception as exc:  # job boundary: failures become observable state
            with self._lock:
                job = self._jobs[job_id]
                job.status = JobStatus.FAILED
                job.progress_percent = 100
                job.error = f"{type(exc).__name__}: {exc}"
                self._inflight_by_key.pop(job.cache_key.as_tuple(), None)
            return

        if hasattr(result, "parameter_provenance"):
            result.parameter_provenance = {
                path: configured.source.value
                for path, configured in analysis_config.parameters.items()
            }

        with self._lock:
            job = self._jobs[job_id]
            self.cache.put(
                job.cache_key, result, snapshot_chain_id=job.chain_id
            )
            job.result = result
            job.status = JobStatus.SUCCEEDED
            job.progress_percent = 100
            self._inflight_by_key.pop(job.cache_key.as_tuple(), None)

    def get(self, job_id: str) -> Tier2JobView:
        with self._lock:
            try:
                return self._jobs[job_id].view()
            except KeyError as exc:
                raise KeyError(f"unknown Tier-2 job_id {job_id!r}") from exc

    def latest_succeeded(
        self, snapshot_id: str, snapshot_version: str, chain_id: str
    ) -> Tier2JobView | None:
        """Return an already-computed Audit artifact without triggering Tier-2."""
        with self._lock:
            matches = [
                job.view()
                for job in self._jobs.values()
                if job.chain_id == chain_id
                and job.cache_key.snapshot_id == snapshot_id
                and job.cache_key.snapshot_version == snapshot_version
                and job.status is JobStatus.SUCCEEDED
            ]
        return matches[-1] if matches else None

    def wait(self, job_id: str, *, timeout: float | None = None) -> Tier2JobView:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"unknown Tier-2 job_id {job_id!r}")
            future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get(job_id)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def __enter__(self) -> "Tier2JobManager":
        return self

    def __exit__(self, *args) -> None:
        self.shutdown()
