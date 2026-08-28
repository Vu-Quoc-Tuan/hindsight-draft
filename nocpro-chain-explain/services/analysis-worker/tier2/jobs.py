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
from libs.contracts import IngestedPackage
from tier1a import CacheKey, CacheTier, Tier1Cache

from .audit_analysis import (
    AuditExecutionPolicy,
    SimilarityQueryContext,
    analyze_structural_audit,
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
        self._inflight_by_key: dict[tuple[str, str, str, str], str] = {}

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
        key = self.cache.key_for(
            CacheTier.TIER_2,
            member_ids=members,
            snapshot_id=package.snapshot.snapshot_id,
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
