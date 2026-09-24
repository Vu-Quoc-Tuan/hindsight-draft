"""In-process repository/service boundary used by the HTTP adapter."""

from __future__ import annotations

import os
import json
import hashlib
import asyncio
import logging
from concurrent.futures import Future
from dataclasses import asdict, dataclass, replace
from types import SimpleNamespace

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Sequence

logger = logging.getLogger(__name__)

from channels import evaluate_pair_channels
from evolution import GlobalEpisodeDag, LineageConfig, LineageNodeKey
from history import HistoricalEvidenceModel, HistoricalTaxonomy
from temporal_delay import FrozenDelayModel
from .review_learning_service import ReviewLearningService
from .review_principal import ReviewerPrincipal, verify_domain_authorization
from review_learning.contracts import (
    ImmutableReviewSnapshotContext,
    ReviewDecision,
    ReviewSessionNotFound,
    normalize_review_decision,
)
from .persistence import StoredEvolution, StoredEvolutionNode, StoredEvolutionEdge
from configuration import (
    AnalysisConfig,
    ConfiguredValue,
    ParameterSource,
    PARAMETER_RULES,
    load_analysis_config,
)
from libs.contracts import IngestedPackage, load_validated_package
from libs.contracts.analysis_identity import (
    analysis_identity_from_review,
)
from libs.contracts.topology_identity import effective_topology_version, snapshot_topology_profile
from .observability import active_observability
from tier1a import CacheTier, SnapshotPrecompute, Tier1Cache, precompute_snapshot
from tier1b import analyze_chain_configured
from tier2 import (
    AUDIT_ANALYSIS_VERSION,
    AuditVisualization,
    ReviewAuditArtifact,
    SimilarityQueryContext,
    Tier2JobManager,
    Tier2JobView,
    chain_membership_fingerprint,
    unavailable_audit_visualization,
)
from tier2.counterfactual import (
    CounterfactualJobManager,
    CounterfactualJobView as DomainCounterfactualJobView,
    artifact_fingerprint,
    review_identity,
    ReviewIdentity,
)
from tier2.counterfactual.public_contract import public_review_result


def _record_quality_submission(stage: str, submission: Any) -> None:
    observability = active_observability()
    if observability is None or submission is None:
        return
    cache_hit = bool(getattr(submission, "cache_hit", False))
    deduplicated = bool(getattr(submission, "deduplicated", False))
    observability.record_counter(
        "cache.hit" if cache_hit else "cache.miss",
        attributes={
            "stage": stage,
            "cache.state": (
                "hit" if cache_hit else "deduplicated" if deduplicated else "miss"
            ),
        },
    )
    if not cache_hit and not deduplicated and getattr(submission, "job_id", None):
        observability.record_counter(
            "quality.job.submitted", attributes={"stage": stage}
        )


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config" / "thresholds" / "v1.yaml"


def _parse_iso_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cache_key_fingerprint(cache_key) -> str:
    encoded = json.dumps(cache_key.as_tuple(), separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    """Fingerprint the exact immutable activation input without serializing objects."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _topology_version(value: Any) -> str | None:
    raw_snapshot = value.get("snapshot") if isinstance(value, dict) else getattr(value, "snapshot", None)
    topo_ref = raw_snapshot.get("topology_ref") if isinstance(raw_snapshot, dict) else getattr(raw_snapshot, "topology_ref", None)
    if isinstance(topo_ref, dict):
        version = topo_ref.get("topology_version")
        if version is not None:
            return str(version)
    version = getattr(topo_ref, "topology_version", None)
    if version is None:
        topology = value.get("topology") if isinstance(value, dict) else getattr(value, "topology", None)
        version = topology.get("topology_version") if isinstance(topology, dict) else None
    return str(version) if version is not None else None


@dataclass(frozen=True)
class _PreparedActivation:
    package: IngestedPackage
    precompute: SnapshotPrecompute
    payload_fingerprint: str
    config_version: str
    topology_version: str | None


@dataclass(frozen=True)
class AuditVisualizationLookup:
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    audit_artifact: ReviewAuditArtifact | None
    visualization: AuditVisualization

EDITABLE_PARAMETER_METADATA: list[dict[str, Any]] = [
    {
        "key": "s_min",
        "path": "role.s_min",
        "label": "s_min (Core Support)",
        "description": "Minimum membership support for core role assignment",
        "min": 0.1,
        "max": 1.0,
        "step": 0.05,
    },
    {
        "key": "s_weak",
        "path": "role.s_weak",
        "label": "s_weak (Weak Support)",
        "description": "Weak boundary membership support threshold",
        "min": 0.05,
        "max": 0.9,
        "step": 0.05,
    },
    {
        "key": "rho",
        "path": "audit.rho",
        "label": "rho (Balance Ratio)",
        "description": "Balance constraint ratio for candidate cuts (|S| / |V|)",
        "min": 0.01,
        "max": 0.49,
        "step": 0.01,
    },
    {
        "key": "gap_seconds",
        "path": "temporal.burst.gap_seconds",
        "label": "gap_seconds (Burst Gap)",
        "description": "Silent temporal burst gap in seconds between alarms",
        "min": 10,
        "max": 600,
        "step": 10,
    },
    {
        "key": "c_min",
        "path": "role.c_min",
        "label": "c_min (Core Clustering)",
        "description": "Minimum clustering coefficient for core role assignment",
        "min": 0.1,
        "max": 1.0,
        "step": 0.05,
    },
    {
        "key": "r_min",
        "path": "role.r_min",
        "label": "r_min (Core Representativeness)",
        "description": "Minimum representativeness score for core alarms",
        "min": 0.1,
        "max": 1.0,
        "step": 0.05,
    },
    {
        "key": "global_weak_baseline",
        "path": "audit.global_weak_baseline",
        "label": "global_weak_baseline (Conductance Baseline)",
        "description": "Global fallback baseline for conductance threshold epsilon",
        "min": 0.05,
        "max": 1.0,
        "step": 0.05,
    },
]

KEY_TO_PATH = {item["key"]: item["path"] for item in EDITABLE_PARAMETER_METADATA}


class SnapshotNotLoaded(RuntimeError):
    pass


class Workspace:
    """Owns current snapshot, reusable index/cache and Tier-2 executor."""

    def __init__(self, *, config_path: Path | None = None) -> None:
        selected_config = config_path or Path(
            os.environ.get("ANALYSIS_CONFIG_PATH", str(DEFAULT_CONFIG))
        )
        self._base_config_path = selected_config
        self._custom_config_counter = 0
        self.config: AnalysisConfig = load_analysis_config(selected_config)
        self.cache = Tier1Cache()
        tier2_workers = int(os.environ.get("TIER2_MAX_WORKERS", "1"))
        self.jobs = Tier2JobManager(cache=self.cache, max_workers=tier2_workers)
        review_workers = int(
            os.environ.get("NOCPRO_COUNTERFACTUAL_MAX_WORKERS", "1")
        )
        self.review_jobs = CounterfactualJobManager(max_workers=review_workers)
        self.package: IngestedPackage | None = None
        self.precompute: SnapshotPrecompute | None = None
        # Keep a tiny activation cache for recently selected immutable
        # snapshots.  Re-selecting a READY catalog item should promote the
        # prepared Tier-1A objects instead of reparsing the full payload.
        self._prepared_snapshot_cache: dict[
            tuple[str, str], tuple[IngestedPackage, SnapshotPrecompute]
        ] = {}
        # Snapshot-wide quality workers prepare immutable packages in an
        # isolated Workspace.  Keep a small exact-identity handoff so a later
        # UI selection can promote that work without reparsing the full JSON.
        # This is an in-memory object registry (not pickle/serialized state),
        # bounded to avoid turning the portfolio into an unbounded cache.
        self._prepared_activation_cache: dict[tuple[str, str], _PreparedActivation] = {}
        # Portfolio deployments commonly expose more than four immutable
        # snapshots.  Keep enough warm activations for a normal local catalog
        # while retaining an explicit bound; operators with larger payloads
        # can lower this through NOCPRO_PREPARED_ACTIVATION_CACHE_SIZE.
        self._prepared_activation_cache_limit = max(
            1, int(os.environ.get("NOCPRO_PREPARED_ACTIVATION_CACHE_SIZE", "16"))
        )
        self._precomputed_snapshots: set[tuple[str, str, str | None]] = set()
        self.auto_chain_quality = os.environ.get(
            "NOCPRO_AUTO_CHAIN_QUALITY", "true"
        ).lower() in {"1", "true", "yes"}
        self._lock = RLock()
        self._activation_generation = 0
        self._analysis_generation = 0
        self.repository = None
        self.coordinator = None
        self.similarity_index = None
        self.lineage_by_chain: dict[str, str] = {}
        self.historical_model: HistoricalEvidenceModel | None = None
        self.historical_taxonomy: HistoricalTaxonomy | None = None
        # This is deliberately separate from the snapshot-bound frozen model.
        # An operator/integration may attach an authoritative taxonomy source
        # once; each H model still persists the exact version it consumed.
        self.historical_taxonomy_source: HistoricalTaxonomy | None = None
        self.historical_unavailable_reason = self.config.historical_evidence_reason
        self.temporal_delay_model: FrozenDelayModel | None = None
        self.temporal_delay_taxonomy: HistoricalTaxonomy | None = None
        self.temporal_delay_unavailable_reason = self.config.temporal_delay_reason
        self._persistence_loop = None
        self._review_persistence_futures: list[Future] = []
        self._audit_persistence_futures: list[Future] = []
        self._deep_dive_persistence_futures: list[Future] = []
        self._quality_resume_task: asyncio.Task[Any] | None = None
        # When PostgreSQL is available, app.py assigns all automatic quality
        # work to the snapshot-wide runner.  The active UI workspace remains
        # available for explicit/on-demand inspection but must not enqueue a
        # second copy of the same chain jobs when /chains is opened.
        self._quality_background_owner = False
        self._analysis_persistence_semaphore: asyncio.Semaphore | None = None
        self._closing = False
        self.operator_feedbacks: list[dict[str, Any]] = []
        self._job_persistence_locks: dict[str, asyncio.Lock] = {}
        ranker_art_dir = os.environ.get("NOCPRO_REVIEW_RANKER_ARTIFACT_DIR")
        enforce_gov = os.environ.get("NOCPRO_REVIEW_RANKER_ENFORCE_GOVERNANCE", "1").lower() in {"1", "true", "yes"}
        signing_key = os.environ.get("NOCPRO_GOVERNANCE_SIGNING_KEY")
        abstention_thresh_raw = os.environ.get("NOCPRO_REVIEW_RANKER_ABSTENTION_THRESHOLD")

        app_env = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
        is_production = app_env in {"production", "prod"}
        if is_production and not enforce_gov:
            raise RuntimeError(
                f"Production environment detected (APP_ENV={app_env}), but NOCPRO_REVIEW_RANKER_ENFORCE_GOVERNANCE is disabled! "
                "Disabling ranker governance in production is strictly forbidden."
            )
        if is_production and abstention_thresh_raw is not None:
            raise RuntimeError(
                "Production must use the signed artifact abstention threshold; "
                "NOCPRO_REVIEW_RANKER_ABSTENTION_THRESHOLD is not permitted."
            )
        abstention_thresh = float(abstention_thresh_raw) if abstention_thresh_raw is not None else None
        if abstention_thresh is not None:
            logger.warning(
                "Deployment environment override applied for review ranker abstention threshold: %s",
                abstention_thresh,
            )

        self.review_learning: ReviewLearningService = ReviewLearningService(
            repository=None,
            ranker_artifact_dir=ranker_art_dir,
            enforce_production_governance=enforce_gov,
            signing_key=signing_key,
            abstention_threshold=abstention_thresh,
        )
        if (
            not is_production
            and os.environ.get("NOCPRO_ENABLE_DEMO_FIXTURES", "").lower() in {"1", "true", "yes"}
            and len(self.review_learning._review_cases) == 0
        ):
            self._seed_dev_review_cases()
        self._local_evolution_dag: GlobalEpisodeDag | None = None

    def _get_job_persistence_lock(self, job_id: str) -> asyncio.Lock:
        with self._lock:
            lock = self._job_persistence_locks.get(job_id)
            if lock is None:
                if len(self._job_persistence_locks) > 1000:
                    oldest_keys = list(self._job_persistence_locks.keys())[:200]
                    for k in oldest_keys:
                        del self._job_persistence_locks[k]
                lock = asyncio.Lock()
                self._job_persistence_locks[job_id] = lock
            return lock

    def _release_job_persistence_lock(self, job_id: str) -> None:
        with self._lock:
            self._job_persistence_locks.pop(job_id, None)

    def _get_or_build_local_evolution_dag(self) -> GlobalEpisodeDag | None:
        if self._local_evolution_dag is not None:
            return self._local_evolution_dag
        try:
            presets_dir = Path(
                os.environ.get(
                    "NOCPRO_PRESETS_DIR",
                    str(ROOT / "config" / "presets"),
                )
            )
            evo_files = [
                presets_dir / "real_alarm_evolution_v1_snap_000.json",
                presets_dir / "real_alarm_evolution_v1_snap_001.json",
                presets_dir / "real_alarm_evolution_v1_snap_002.json",
            ]
            if not any(f.exists() for f in evo_files):
                mock_sample_dir = ROOT.parent / "nocpro-mock" / "datasets" / "generated" / "real_ip_evolution_sample"
                evo_files = [
                    mock_sample_dir / "snapshot_000.json",
                    mock_sample_dir / "snapshot_001.json",
                    mock_sample_dir / "snapshot_002.json",
                ]
            if not any(f.exists() for f in evo_files):
                return None
            try:
                m_min = int(self.config.value("lineage.min_intersection"))
            except Exception:
                m_min = 1
            dag = GlobalEpisodeDag()
            cfg = LineageConfig(
                config_version=self.config.config_version,
                m_min=m_min,
            )
            prev_pkg = None
            for fpath in evo_files:
                if fpath.exists():
                    with open(fpath, encoding="utf-8") as f:
                        data = json.load(f)
                    pkg = load_validated_package(data)
                    dag.apply_snapshot(pkg, previous=prev_pkg, config=cfg)
                    prev_pkg = pkg
            self._local_evolution_dag = dag
            return dag
        except Exception:
            return None

    def get_active_parameters(self) -> dict[str, Any]:
        editable = {}
        details = []
        for item in EDITABLE_PARAMETER_METADATA:
            path = item["path"]
            configured = self.config.parameter(path)
            editable[item["key"]] = configured.value
            details.append(
                {
                    "path": path,
                    "key": item["key"],
                    "label": item["label"],
                    "value": configured.value,
                    "source": configured.source.value,
                    "min": item.get("min"),
                    "max": item.get("max"),
                    "step": item.get("step"),
                    "description": item.get("description"),
                }
            )
        return {
            "config_version": self.config.config_version,
            "status": self.config.status,
            "editable_parameters": editable,
            "parameters_detail": details,
        }

    def _normalize_parameter_overrides(
        self, overrides: dict[str, float | int]
    ) -> dict[str, float | int]:
        normalized_overrides: dict[str, float | int] = {}
        for raw_key, raw_val in overrides.items():
            path = KEY_TO_PATH.get(raw_key, raw_key)
            rule = PARAMETER_RULES.get(path)
            if rule is None:
                raise ValueError(f"Unknown or non-configurable parameter {raw_key!r}")
            norm_val = rule.validate(path, raw_val)
            normalized_overrides[path] = norm_val

        # Cross parameter validations
        cur_s_min = normalized_overrides.get("role.s_min", self.config.value("role.s_min"))
        cur_s_weak = normalized_overrides.get("role.s_weak", self.config.value("role.s_weak"))
        if cur_s_weak > cur_s_min:
            raise ValueError(f"role.s_weak ({cur_s_weak}) must be <= role.s_min ({cur_s_min})")
        return normalized_overrides

    def _config_with_overrides(
        self,
        overrides: dict[str, float | int],
        *,
        config_version: str,
    ) -> AnalysisConfig:
        normalized_overrides = self._normalize_parameter_overrides(overrides)
        new_parameters = dict(self.config.parameters)
        for path, val in normalized_overrides.items():
            new_parameters[path] = ConfiguredValue(
                path=path,
                value=val,
                source=ParameterSource.SYSTEM_PROVIDED,
            )
        return replace(
            self.config,
            config_version=config_version,
            parameters=new_parameters,
        )

    def update_parameters(self, overrides: dict[str, float | int]) -> dict[str, Any]:
        normalized_overrides = self._normalize_parameter_overrides(overrides)

        with self._lock:
            self._custom_config_counter += 1
            param_str = json.dumps(
                sorted((str(k), float(v) if isinstance(v, (int, float)) else str(v)) for k, v in normalized_overrides.items()),
                sort_keys=True,
            )
            param_hash = hashlib.sha256(param_str.encode("utf-8")).hexdigest()[:8]
            base_ver = self.config.config_version.split("-custom-")[0]
            new_version = f"{base_ver}-custom-{self._custom_config_counter}-{param_hash}"

            self.config = self._config_with_overrides(
                normalized_overrides, config_version=new_version
            )
            self._analysis_generation += 1
            self.cache.entries.clear()
            self.jobs.cache.entries.clear()
            self._prepared_snapshot_cache.clear()
            self._prepared_activation_cache.clear()

        return self.get_active_parameters()

    def reset_parameters(self) -> dict[str, Any]:
        with self._lock:
            # Reset strictly to the initial startup base configuration (e.g. v1.yaml)
            self.config = load_analysis_config(self._base_config_path)
            self._analysis_generation += 1
            self.cache.entries.clear()
            self.jobs.cache.entries.clear()
            self._prepared_snapshot_cache.clear()
            self._prepared_activation_cache.clear()
        return self.get_active_parameters()

    async def calibrate_from_database(
        self,
        database_url: str | None = None,
        include_fixtures: bool = False,
        output_yaml: Path | None = None,
    ) -> dict[str, Any]:
        from benchmarks.calibrate_thresholds import calibrate_from_postgres

        env_output = os.environ.get("NOCPRO_CALIBRATED_OUTPUT_PATH")
        calibrated_output = output_yaml or (Path(env_output) if env_output else ROOT / "config" / "thresholds" / "calibrated.yaml")
        report = await calibrate_from_postgres(
            database_url=database_url,
            output_yaml=calibrated_output,
            include_fixtures=include_fixtures,
        )
        with self._lock:
            self.config = load_analysis_config(calibrated_output)
            self._analysis_generation += 1
            self.cache.entries.clear()
            self.jobs.cache.entries.clear()
            self._prepared_snapshot_cache.clear()
            self._prepared_activation_cache.clear()

        return asdict(report)


    def close(self) -> None:
        self._closing = True
        if self._quality_resume_task is not None and not self._quality_resume_task.done():
            self._quality_resume_task.cancel()
        self.review_jobs.set_state_listener(None)
        self.jobs.set_state_listener(None)
        self.jobs.set_artifact_listener(None)
        # Terminal artifacts are persisted as jobs finish. During reload or
        # shutdown, queued deterministic work can be recreated idempotently;
        # draining the entire snapshot queue would make API shutdown take
        # minutes and keep the development server unavailable.
        self.review_jobs.shutdown(wait=False, cancel_futures=True)
        self.jobs.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            self._prepared_snapshot_cache.clear()
            self._prepared_activation_cache.clear()

    def set_quality_background_owner(self, enabled: bool = True) -> None:
        """Delegate automatic snapshot quality scheduling to a background runner."""
        self._quality_background_owner = bool(enabled)

    async def flush_audit_persistence(self) -> None:
        with self._lock:
            pending = list(self._audit_persistence_futures)
            self._audit_persistence_futures.clear()
        if pending:
            await asyncio.gather(
                *(asyncio.wrap_future(future) for future in pending),
                return_exceptions=False,
            )

    async def flush_review_persistence(self) -> None:
        with self._lock:
            pending = list(self._review_persistence_futures)
            self._review_persistence_futures.clear()
        if pending:
            for future in pending:
                await asyncio.wrap_future(future)

    async def flush_deep_dive_persistence(self) -> None:
        with self._lock:
            pending = list(self._deep_dive_persistence_futures)
            self._deep_dive_persistence_futures.clear()
        if pending:
            await asyncio.gather(
                *(asyncio.wrap_future(future) for future in pending),
                return_exceptions=False,
            )

    def attach_persistence(self, repository, coordinator) -> None:
        self.repository = repository
        self.coordinator = coordinator
        self.review_learning.repository = repository
        self._persistence_loop = asyncio.get_running_loop()
        self._analysis_persistence_semaphore = asyncio.Semaphore(
            int(os.environ.get("NOCPRO_ANALYSIS_PERSISTENCE_CONCURRENCY", "4"))
        )

        def persist_review_state(view) -> None:
            status_val = view.status.value if hasattr(view.status, "value") else str(view.status)
            if status_val == "SUCCEEDED" and view.result is not None:
                lineage_id = getattr(view, "lineage_component_id", None) or self.lineage_by_chain.get(view.chain_id)
                if lineage_id is None and self.package is not None:
                    dag = self._get_or_build_local_evolution_dag()
                    if dag is not None:
                        k = LineageNodeKey(
                            self.package.snapshot.snapshot_id,
                            self.package.snapshot.snapshot_version,
                            view.chain_id,
                        )
                        lineage_id = dag.canonical_lineage(k)
                        if lineage_id:
                            self.lineage_by_chain[view.chain_id] = lineage_id
                if lineage_id is None or lineage_id.startswith("fallback_lineage:"):
                    lineage_id = "LINEAGE_UNAVAILABLE"

                raw_source_kind = (
                    getattr(self.package.snapshot, "source_kind", None)
                    if self.package and getattr(self.package, "snapshot", None)
                    else None
                )
                if raw_source_kind in {"REAL_LIVE", "REAL_EXPORT_REPLAY"}:
                    source_k = raw_source_kind
                elif hasattr(raw_source_kind, "value") and raw_source_kind.value in {"REAL_LIVE", "REAL_EXPORT_REPLAY"}:
                    source_k = raw_source_kind.value
                else:
                    source_k = "SOURCE_KIND_UNAVAILABLE"

                domain_val = getattr(view.identity, "domain", None) if hasattr(view, "identity") else None
                if not domain_val and self.package is not None:
                    if getattr(self.package, "topology", None) and isinstance(self.package.topology, dict):
                        domain_val = self.package.topology.get("domain")
                if not domain_val:
                    domain_val = "UNKNOWN_DOMAIN"

                snapshot_obs_at = (
                    getattr(self.package.snapshot, "observed_at", None)
                    or getattr(self.package.snapshot, "snapshot_time", None)
                    or getattr(self.package.snapshot, "produced_at", None)
                ) if (self.package and getattr(self.package, "snapshot", None)) else None
                job_comp_at = getattr(view, "completed_at", None) or datetime.now(timezone.utc)
                rev_time = job_comp_at

                context = ImmutableReviewSnapshotContext(
                    snapshot_id=str(getattr(view.identity, "snapshot_id", "") or (self.package.snapshot.snapshot_id if self.package else "")),
                    snapshot_version=str(getattr(view.identity, "snapshot_version", "1") or (self.package.snapshot.snapshot_version if self.package else "1")),
                    chain_id=str(view.chain_id),
                    review_time=rev_time,
                    snapshot_observed_at=snapshot_obs_at,
                    job_completed_at=job_comp_at,
                    review_domain=domain_val,
                    generator_version="v1",
                    config_version="v1",
                    exposure_policy_version="ALL_EVALUATED",
                    source_kind=source_k,
                    lineage_component_id=lineage_id,
                )
                session, exposures = self.review_learning.prepare_review_bundle(
                    job_id=view.job_id,
                    job_view=view,
                    package=self.package,
                    delay_model=self.temporal_delay_model,
                    taxonomy=self.temporal_delay_taxonomy or self.historical_taxonomy_source,
                    config_version="v1",
                    exposure_policy="ALL_EVALUATED",
                    context=context,
                )

                async def _persist_atomic() -> None:
                    try:
                        semaphore = self._analysis_persistence_semaphore
                        if semaphore is None:
                            raise RuntimeError("Analysis persistence semaphore is unavailable")
                        async with semaphore:
                            async with self._get_job_persistence_lock(view.job_id):
                                await repository.persist_succeeded_job_and_review_bundle(
                                    view.persistence_payload(), session, exposures
                                )
                                self.review_learning.register_persisted_bundle(session, exposures)
                        try:
                            await self._materialize_chain_quality(view)
                        except Exception:
                            logger.exception(
                                "Failed to materialize deterministic quality for chain %s",
                                view.chain_id,
                            )
                    finally:
                        self._release_job_persistence_lock(view.job_id)

                loop = self._persistence_loop
                if loop is None or loop.is_closed():
                    raise RuntimeError("Persistence event loop is not attached or is closed")

                freeze_future = asyncio.run_coroutine_threadsafe(
                    _persist_atomic(),
                    loop,
                )
                with self._lock:
                    self._review_persistence_futures.append(freeze_future)
            else:
                loop = self._persistence_loop
                if loop is None or loop.is_closed():
                    raise RuntimeError("Persistence event loop is not attached or is closed")

                async def _persist_non_terminal() -> None:
                    try:
                        semaphore = self._analysis_persistence_semaphore
                        if semaphore is None:
                            raise RuntimeError("Analysis persistence semaphore is unavailable")
                        async with semaphore:
                            async with self._get_job_persistence_lock(view.job_id):
                                await repository.persist_counterfactual_job(view.persistence_payload())
                    finally:
                        if status_val in {"FAILED", "INTERRUPTED"}:
                            self._release_job_persistence_lock(view.job_id)

                future = asyncio.run_coroutine_threadsafe(
                    _persist_non_terminal(),
                    loop,
                )
                with self._lock:
                    self._review_persistence_futures.append(future)

        self.review_jobs.set_state_listener(persist_review_state)

        def persist_deep_dive_state(view) -> None:
            from .serializers import job_view

            public = job_view(view).model_dump(mode="json")

            async def _persist_and_continue() -> None:
                semaphore = self._analysis_persistence_semaphore
                if semaphore is None:
                    raise RuntimeError("Analysis persistence semaphore is unavailable")
                async with semaphore:
                    await repository.persist_deep_dive_job(
                        {
                            **public,
                            "snapshot_id": view.cache_key.snapshot_id,
                            "snapshot_version": view.cache_key.snapshot_version,
                            "cache_fingerprint": _cache_key_fingerprint(view.cache_key),
                            "analysis_config_version": view.cache_key.config_version,
                        }
                    )
                status_value = (
                    view.status.value
                    if hasattr(view.status, "value")
                    else str(view.status)
                )
                if status_value != "SUCCEEDED":
                    return
                if self._closing:
                    return
                if not self.auto_chain_quality:
                    return
                package = self.package
                if package is None or (
                    package.snapshot.snapshot_id,
                    package.snapshot.snapshot_version,
                ) != (
                    view.cache_key.snapshot_id,
                    view.cache_key.snapshot_version,
                ):
                    return
                try:
                    await self.submit_review(view.chain_id)
                except Exception:
                    logger.exception(
                        "Failed to continue deterministic review for chain %s",
                        view.chain_id,
                    )

            future = asyncio.run_coroutine_threadsafe(
                _persist_and_continue(),
                self._persistence_loop,
            )
            with self._lock:
                self._deep_dive_persistence_futures.append(future)

        self.jobs.set_state_listener(persist_deep_dive_state)

        def persist_audit_artifact(artifact) -> None:
            future = asyncio.run_coroutine_threadsafe(
                repository.persist_audit_artifact(artifact),
                self._persistence_loop,
            )
            with self._lock:
                self._audit_persistence_futures.append(future)

        self.jobs.set_artifact_listener(persist_audit_artifact)

    async def _materialize_chain_quality(self, review_view) -> None:
        """Persist quality from deterministic artifacts without invoking a provider."""
        if self.repository is None:
            return
        with self._lock:
            package = self.package
            config = self.config
            expected_config_version = config.config_version
            expected_review_config_version = (
                config.counterfactual.config_version
                if config.counterfactual is not None
                else "UNAVAILABLE"
            )
            analysis_generation = self._analysis_generation
        if package is None:
            return
        identity = getattr(review_view, "identity", None)
        snapshot_id = str(getattr(identity, "snapshot_id", ""))
        snapshot_version = str(getattr(identity, "snapshot_version", ""))
        if (
            getattr(identity, "analysis_version", None) != expected_config_version
            or getattr(identity, "config_version", None)
            != expected_review_config_version
            or getattr(identity, "chain_id", None) != str(review_view.chain_id)
        ):
            return
        if (
            package.snapshot.snapshot_id,
            package.snapshot.snapshot_version,
        ) != (snapshot_id, snapshot_version):
            return
        if getattr(identity, "topology_version", None) != _topology_version(package):
            return
        chain_id = str(review_view.chain_id)
        if len(package.members_of(chain_id)) <= 1:
            return

        _, _, current_deep_dive_key = self._deep_dive_context(chain_id)
        deep_dive_view = self.jobs.latest_compatible(current_deep_dive_key)
        if deep_dive_view is not None and getattr(deep_dive_view.status, "value", deep_dive_view.status) != "SUCCEEDED":
            deep_dive_view = None
        if deep_dive_view is None and self.repository is not None:
            deep_dive_view = await self.latest_deep_dive(chain_id)
        from .serializers import job_view

        deep_dive_analysis = deep_dive_view.result if deep_dive_view is not None else None
        deep_dive_source_result = (
            deep_dive_analysis if isinstance(deep_dive_analysis, dict)
            else job_view(deep_dive_view).model_dump(mode="json")["result"]
            if isinstance(deep_dive_view, Tier2JobView) else None
        )
        audit_artifact = getattr(deep_dive_view, "audit_artifact", None)
        # The in-memory Tier-2 view carries the Audit artifact directly, but a
        # restart restores Deep Dive from its JSON row and therefore has no
        # object-level artifact attached.  Read the separately persisted,
        # exact-compatible artifact before materializing deterministic quality;
        # otherwise every restart is incorrectly labelled "P2 chưa chạy".
        if audit_artifact is None and self.repository is not None:
            audit_lookup = await self.latest_audit_visualization(chain_id)
            audit_artifact = audit_lookup.audit_artifact
        if audit_artifact is not None:
            await self.flush_audit_persistence()
        # Use the same public JSON stored by the Review job writer for both
        # quality inputs and the receipt's exact source comparison.
        review_result = (
            dict(review_view.result)
            if isinstance(review_view.result, dict)
            else public_review_result(review_view.result)
        )
        from .cohesion_advisor import (
            CHAIN_QUALITY_PIPELINE_VERSION,
            build_chain_overview_projection,
            extract_cohesion_context,
        )

        context = extract_cohesion_context(
            service=self,
            chain_id=chain_id,
            analysis=self.analyze(chain_id),
            audit_artifact=audit_artifact,
            review_result=review_result,
            deep_dive_analysis=deep_dive_analysis,
        )
        assessment = context.get("quality_assessment") or {}
        recommendations = context.get("recommendations") or {}
        overview_projection = build_chain_overview_projection(context)
        deep_dive_cache_fingerprint = getattr(deep_dive_view, "cache_fingerprint", None)
        if deep_dive_cache_fingerprint is None and deep_dive_view is not None:
            cache_key = getattr(deep_dive_view, "cache_key", None)
            if cache_key is not None:
                deep_dive_cache_fingerprint = _cache_key_fingerprint(cache_key)
        with self._lock:
            if (
                self.package is not package
                or self.config.config_version != expected_config_version
                or (
                    self.config.counterfactual.config_version
                    if self.config.counterfactual is not None
                    else "UNAVAILABLE"
                )
                != expected_review_config_version
            ):
                return
        fingerprint_payload = {
            "pipeline_version": CHAIN_QUALITY_PIPELINE_VERSION,
            "config_version": expected_config_version,
            "review_config_version": expected_review_config_version,
            "snapshot_id": snapshot_id,
            "snapshot_version": snapshot_version,
            "topology_version": _topology_version(package),
            "chain_id": chain_id,
            "deep_dive_job_id": getattr(deep_dive_view, "job_id", None),
            "deep_dive_cache_fingerprint": deep_dive_cache_fingerprint,
            "counterfactual_job_id": review_view.job_id,
            "counterfactual_cache_fingerprint": artifact_fingerprint(
                review_view.identity.cache_tuple()
            ),
        }
        input_fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
            ).hexdigest()
        analysis_identity_result = analysis_identity_from_review(
            identity,
            pipeline_version=CHAIN_QUALITY_PIPELINE_VERSION,
            input_fingerprint=input_fingerprint,
        )
        if not analysis_identity_result.available or analysis_identity_result.identity is None:
            return
        identity_payload = analysis_identity_result.identity.to_payload()
        review_analysis_identity_result = analysis_identity_from_review(
            identity,
            pipeline_version=str(getattr(identity, "engine_version", "") or ""),
            input_fingerprint=str(
                getattr(identity, "tier1b_artifact_fingerprint", "") or ""
            ),
        )
        review_artifact_fingerprint = artifact_fingerprint(identity.cache_tuple())
        projection_payload = {
            **overview_projection,
            "analysis_identity": identity_payload,
            "review_analysis_identity": (
                review_analysis_identity_result.identity.to_payload()
                if review_analysis_identity_result.available
                and review_analysis_identity_result.identity is not None
                else None
            ),
            "review_artifact_revision": {
                "resource_kind": "counterfactual_review",
                "fingerprint": review_artifact_fingerprint,
            },
            "chain_id": chain_id,
            "review_config_version": expected_review_config_version,
            "input_fingerprint": input_fingerprint,
            "snapshot_id": snapshot_id,
            "snapshot_version": snapshot_version,
            "config_version": expected_config_version,
            "topology_version": _topology_version(package),
            "pipeline_version": CHAIN_QUALITY_PIPELINE_VERSION,
        }

        # Evidence links are a projection of the exact artifacts used above.
        # They are additive metadata and deliberately do not feed the quality
        # fingerprint or alter readiness/scoring.
        from .evidence_projection import (
            attach_evidence_references,
            build_evidence_records,
        )

        review_evidence = {
            "job_id": review_view.job_id,
            "status": "SUCCEEDED",
            "analysis_identity": (
                review_analysis_identity_result.identity.to_payload()
                if review_analysis_identity_result.available
                and review_analysis_identity_result.identity is not None
                else None
            ),
            "result": review_result,
        }
        evidence_records = build_evidence_records(
            identity=identity_payload,
            overview_projection=projection_payload,
            pair_evidence=None,
            audit_artifact=audit_artifact,
            review_result=review_evidence,
        )
        attach_evidence_references(
            identity=identity_payload,
            quality_assessment=assessment,
            analytical_findings=context.get("analytical_findings"),
            records=evidence_records,
        )

        # Rebuild the canonical Review context immediately before publication.
        # A config/topology/Audit change while the projection was being built
        # must not let this older generation overwrite the current chain row.
        _, _, _, current_identity = await self._review_context(chain_id)
        if current_identity.cache_tuple() != identity.cache_tuple():
            return
        with self._lock:
            if (
                self._analysis_generation != analysis_generation
                or self.package is not package
                or self.config.config_version != expected_config_version
                or (
                    self.config.counterfactual.config_version
                    if self.config.counterfactual is not None
                    else "UNAVAILABLE"
                )
                != expected_review_config_version
            ):
                return

        latest_review_for_identity = getattr(
            self.repository, "latest_counterfactual_job_for_identity", None
        )
        if callable(latest_review_for_identity):
            persisted_review = await latest_review_for_identity(
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
                chain_id=chain_id,
                cache_fingerprint=artifact_fingerprint(identity.cache_tuple()),
            )
            if persisted_review is None or persisted_review.job_id != review_view.job_id:
                return
        await self.repository.persist_chain_quality_assessment(
            {
                "snapshot_id": snapshot_id,
                "snapshot_version": snapshot_version,
                "chain_id": chain_id,
                "assessment_version": str(
                    assessment.get("method") or "HEURISTIC_V1"
                ),
                "input_fingerprint": input_fingerprint,
                "stage": "DETERMINISTIC_COMPLETE",
                "deep_dive_job_id": getattr(deep_dive_view, "job_id", None),
                "counterfactual_job_id": review_view.job_id,
                "recommendation_status": str(
                    recommendations.get("status") or "NOT_EVALUATED"
                ),
                "assessment": assessment,
                "review_result": review_result,
                "deep_dive_result": deep_dive_source_result,
                "overview_projection": projection_payload,
                "chain_membership_fingerprint": chain_membership_fingerprint(
                    package.members_of(chain_id)
                ),
                "audit_artifact_ref": (
                    {
                        "artifact_id": audit_artifact.artifact_id,
                        "artifact_fingerprint": audit_artifact.artifact_fingerprint,
                    }
                    if isinstance(audit_artifact, ReviewAuditArtifact) else None
                ),
            }
        )

    async def _materialize_persisted_chain_quality_if_available(
        self, chain_id: str
    ) -> bool:
        """Backfill the deterministic Overview projection from persisted P2 data."""
        if self.repository is None or self.package is None:
            return False
        try:
            _, _, _, identity = await self._review_context(chain_id)
            stored = await self.repository.latest_compatible_counterfactual_job(
                snapshot_id=identity.snapshot_id,
                snapshot_version=identity.snapshot_version,
                chain_id=chain_id,
                cache_fingerprint=artifact_fingerprint(identity.cache_tuple()),
            )
            if stored is None or stored.status != "SUCCEEDED" or stored.result is None:
                return False
            if not isinstance(stored.identity, dict):
                return False
            stored_identity_adapter = analysis_identity_from_review(
                stored.identity,
                pipeline_version=str(stored.identity.get("engine_version") or ""),
                input_fingerprint=str(
                    stored.identity.get("tier1b_artifact_fingerprint") or ""
                ),
            )
            if not stored_identity_adapter.available:
                return False
            if (
                stored.identity.get("snapshot_id") != stored.snapshot_id
                or stored.identity.get("snapshot_version") != stored.snapshot_version
                or stored.identity.get("chain_id") != stored.chain_id
            ):
                return False
            stored_identity = (
                ReviewIdentity(**stored.identity)
            )
            if stored_identity.cache_tuple() != identity.cache_tuple():
                return False
            await self._materialize_chain_quality(
                SimpleNamespace(
                    job_id=stored.job_id,
                    chain_id=stored.chain_id,
                    identity=stored_identity,
                    result=stored.result,
                )
            )
            return True
        except Exception:
            logger.debug(
                "Persisted deterministic quality backfill unavailable for chain %s",
                chain_id,
                exc_info=True,
            )
            return False

    async def ingest_snapshot(self, payload: dict[str, Any]) -> SnapshotPrecompute:
        if self.repository is None or self.coordinator is None:
            return self.replace_snapshot(payload)
        result = await self.repository.ingest_direct(payload)
        if result.completed_now:
            precompute = await self.coordinator.run(
                result.snapshot_id, result.snapshot_version
            )
            if precompute is None:
                raise RuntimeError("Tier-1A snapshot claim was not acquired")
            return precompute
        source_snapshot = payload.get("snapshot") or {}
        source_topo_ref = source_snapshot.get("topology_ref") or {}
        expected_topology_version = await effective_topology_version(
            result.snapshot_id,
            pinned_version=_topology_version(payload),
            explicit_profile=source_topo_ref.get("profile_id") if isinstance(source_topo_ref, dict) else None,
            repository=getattr(self.coordinator, "topology_repository", None),
        )
        if (
            self.precompute is not None
            and self.package is not None
            and self.package.snapshot.snapshot_id == result.snapshot_id
            and self.package.snapshot.snapshot_version == result.snapshot_version
            and bool(self.package.topology.get("edges"))
            and _topology_version(self.package) == expected_topology_version
        ):
            return self.precompute
        prepared = self._take_prepared_activation(
            payload, expected_topology_version=expected_topology_version
        )
        if prepared is not None:
            package, precompute = prepared
            self.activate_snapshot(package, precompute)
            return precompute
        identity = (result.snapshot_id, result.snapshot_version)
        cached = self._prepared_snapshot_cache.get(identity)
        if (
            cached is not None
            and cached[1].config_version == self.config.config_version
            and _topology_version(cached[0]) == expected_topology_version
        ):
            package, precompute = cached
            self.activate_snapshot(package, precompute)
            return precompute
        # An explicit catalog selection is allowed to reactivate an identical
        # durable snapshot.  ``ingest_direct`` has already checked that the
        # identity and canonical payload are an exact match, so recomputing
        # the local Tier-1A view is safe and does not mutate evidence rows.
        if self.coordinator is not None and hasattr(
            self.coordinator, "_hydrate_payload_topology_if_needed"
        ):
            hydrated_package = await self.coordinator._hydrate_payload_topology_if_needed(
                payload
            )
        else:
            hydrated_package = None
        package, precompute = await self._compute_snapshot_offloaded(
            hydrated_package or payload
        )
        self.activate_snapshot(package, precompute)
        return precompute

    def current_package(self) -> IngestedPackage | None:
        return self.package

    def require_package(self) -> IngestedPackage:
        if self.package is None:
            raise SnapshotNotLoaded("no snapshot loaded")
        return self.package

    def active_identity(self) -> tuple[str, str] | None:
        with self._lock:
            if self.package is None:
                return None
            return (
                self.package.snapshot.snapshot_id,
                self.package.snapshot.snapshot_version,
            )

    def active_generation(self) -> int:
        with self._lock:
            return self._activation_generation

    def store_prepared_activation(
        self,
        payload: dict[str, Any],
        package: IngestedPackage,
        precompute: SnapshotPrecompute,
        *,
        config_version: str,
    ) -> None:
        """Publish a validated background preparation for exact later reuse."""
        identity = (package.snapshot.snapshot_id, package.snapshot.snapshot_version)
        source_snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
        source_identity = (
            str(source_snapshot.get("snapshot_id")) if isinstance(source_snapshot, dict) else identity[0],
            str(source_snapshot.get("snapshot_version")) if isinstance(source_snapshot, dict) else identity[1],
        )
        if source_identity != identity:
            logger.warning(
                "Rejected prepared activation with mismatched snapshot identity: %s != %s",
                source_identity,
                identity,
            )
            return
        entry = _PreparedActivation(
            package=package,
            precompute=precompute,
            payload_fingerprint=_payload_fingerprint(payload),
            config_version=str(config_version),
            topology_version=_topology_version(package),
        )
        with self._lock:
            self._prepared_activation_cache.pop(identity, None)
            self._prepared_activation_cache[identity] = entry
            while len(self._prepared_activation_cache) > self._prepared_activation_cache_limit:
                oldest = next(iter(self._prepared_activation_cache))
                self._prepared_activation_cache.pop(oldest, None)

    def _take_prepared_activation(
        self, payload: dict[str, Any], *, expected_topology_version: str | None
    ) -> tuple[IngestedPackage, SnapshotPrecompute] | None:
        raw_snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
        if not isinstance(raw_snapshot, dict):
            return None
        identity = (
            str(raw_snapshot.get("snapshot_id")),
            str(raw_snapshot.get("snapshot_version")),
        )
        payload_fingerprint = _payload_fingerprint(payload)
        with self._lock:
            entry = self._prepared_activation_cache.get(identity)
            if entry is None:
                return None
            if entry.config_version != self.config.config_version:
                self._prepared_activation_cache.pop(identity, None)
                return None
            if entry.payload_fingerprint != payload_fingerprint:
                return None
            if entry.topology_version != expected_topology_version:
                return None
            # LRU touch while retaining the immutable prepared object.
            self._prepared_activation_cache.pop(identity, None)
            self._prepared_activation_cache[identity] = entry
            return entry.package, entry.precompute

    async def _compute_snapshot_offloaded(
        self, payload: dict[str, Any]
    ) -> tuple[IngestedPackage, SnapshotPrecompute]:
        """Prepare a reactivated snapshot without retaining the loop default pool."""
        from .blocking_work import run_blocking

        return await run_blocking(
            self.compute_snapshot,
            payload,
            workload="api-read",
            pool=getattr(self, "_blocking_work_pool", None),
        )

    def replace_snapshot(self, payload: dict[str, Any]) -> SnapshotPrecompute:
        package, result = self.compute_snapshot(payload)
        self.activate_snapshot(package, result)
        return result

    def compute_snapshot(
        self, payload: dict[str, Any] | IngestedPackage
    ) -> tuple[IngestedPackage, SnapshotPrecompute]:
        """Build Tier-1A state without changing the currently served snapshot."""
        if isinstance(payload, IngestedPackage):
            package = payload
        else:
            if isinstance(payload, dict) and isinstance(payload.get("topology"), dict):
                payload["topology"].pop("alias_resolution", None)
            package = load_validated_package(payload)
        # Production execution stays on the exact full path while the versioned
        # incremental policy is explicitly disabled.
        result = precompute_snapshot(
            package,
            mining_config=self.config.mining_config(),
            cache=self.cache,
            max_values_per_field=int(
                self.config.value("descriptor.max_values_per_field")
            ),
        )
        return package, result

    def activate_snapshot(
        self, package: IngestedPackage, result: SnapshotPrecompute
    ) -> None:
        """Promote a fully computed READY snapshot for API reads."""
        with self._lock:
            old_package = self.package
            if old_package is not None and (
                old_package.snapshot.snapshot_id != package.snapshot.snapshot_id
                or old_package.snapshot.snapshot_version != package.snapshot.snapshot_version
                or _topology_version(old_package) != _topology_version(package)
            ):
                self.cache.invalidate_snapshot(old_package.snapshot.snapshot_id)
            self.package = package
            self.precompute = result
            self._activation_generation += 1
            self._analysis_generation += 1
            identity = (package.snapshot.snapshot_id, package.snapshot.snapshot_version)
            self._prepared_snapshot_cache.pop(identity, None)
            self._prepared_snapshot_cache[identity] = (package, result)
            while len(self._prepared_snapshot_cache) > 2:
                oldest = next(iter(self._prepared_snapshot_cache))
                self._prepared_snapshot_cache.pop(oldest, None)
            self.similarity_index = None
            self.lineage_by_chain = {}
            if self.repository is None:
                dag = self._get_or_build_local_evolution_dag()
                if dag is not None:
                    for c_id in package.chains:
                        k = LineageNodeKey(
                            package.snapshot.snapshot_id,
                            package.snapshot.snapshot_version,
                            c_id,
                        )
                        can_id = dag.canonical_lineage(k)
                        if can_id:
                            self.lineage_by_chain[c_id] = can_id
            self.historical_model = None
            self.historical_taxonomy = None
            self.historical_unavailable_reason = self.config.historical_evidence_reason
            self.temporal_delay_model = None
            self.temporal_delay_taxonomy = None
            self.temporal_delay_unavailable_reason = self.config.temporal_delay_reason

    def attach_similarity(self, index, lineage_by_chain: dict[str, str]) -> None:
        with self._lock:
            self.similarity_index = index
            self.lineage_by_chain = dict(lineage_by_chain)

    def attach_historical_model(
        self,
        model: HistoricalEvidenceModel,
        taxonomy: HistoricalTaxonomy,
    ) -> None:
        """Attach an already-frozen H artifact for Pair WHY only."""
        with self._lock:
            self.historical_model = model
            self.historical_taxonomy = taxonomy
            self.historical_taxonomy_source = taxonomy
            self.historical_unavailable_reason = None

    def set_historical_taxonomy_source(self, taxonomy: HistoricalTaxonomy) -> None:
        """Attach an authoritative taxonomy source for future frozen H builds.

        This does not make H available for the current snapshot: availability
        still requires a persisted model whose cutoff and provenance match.
        """
        with self._lock:
            self.historical_taxonomy_source = taxonomy

    def attach_temporal_delay_model(self, model: FrozenDelayModel, taxonomy: HistoricalTaxonomy) -> None:
        with self._lock:
            self.temporal_delay_model = model
            self.temporal_delay_taxonomy = taxonomy
            self.temporal_delay_unavailable_reason = None

    def list_chains(self):
        self.require_package()
        if self.precompute is None:
            raise SnapshotNotLoaded("snapshot precompute unavailable")
        return self.precompute

    def analyze(self, chain_id: str):
        package = self.require_package()
        if self.precompute is None:
            raise SnapshotNotLoaded("snapshot precompute unavailable")
        members = set(package.members_of(chain_id))
        key = self.cache.key_for(
            CacheTier.TIER_1B,
            member_ids=members,
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            config_version=self.config.config_version,
            topology_version=_topology_version(package),
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        analysis = analyze_chain_configured(
            package,
            chain_id,
            analysis_config=self.config,
            predicate_index=self.precompute.predicate_index,
        )
        self.cache.put(key, analysis, snapshot_chain_id=chain_id)
        return analysis

    def analyze_with_parameters(self, chain_id: str, overrides: dict[str, float | int]):
        """Analyze a chain using a validated, non-persistent configuration override.

        Threshold exploration must not mutate the active workspace configuration or
        poison the normal Tier-1B cache.  The returned analysis is produced by the
        same configured engine as ``analyze`` but is intentionally not cached.
        """
        package = self.require_package()
        if self.precompute is None:
            raise SnapshotNotLoaded("snapshot precompute unavailable")
        normalized = self._normalize_parameter_overrides(overrides)
        encoded = json.dumps(sorted(normalized.items()), separators=(",", ":"))
        suffix = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:10]
        trial_config = self._config_with_overrides(
            normalized,
            config_version=f"{self.config.config_version}-trial-{suffix}",
        )
        return analyze_chain_configured(
            package,
            chain_id,
            analysis_config=trial_config,
            predicate_index=self.precompute.predicate_index,
        )

    def chain_evidence_availability(self, analysis) -> dict[str, dict[str, str | None]]:
        """Expose only directly observed or attached evidence capabilities.

        A missing upstream ``unavailable_capabilities`` marker is not proof that
        a model, topology mapping, or dependency relation exists.
        """
        stats = analysis.evidence.statistics
        unavailable = {str(item).upper() for item in analysis.graybox.unavailable_capabilities}

        def unavailable_for(*tokens: str) -> str | None:
            return next((item for item in unavailable if any(token in item for token in tokens)), None)

        def channel_state(channel_id: str, fallback: str) -> dict[str, str | None]:
            fits = [fit for (alarm_id, cid), fit in stats.fits.items() if cid == channel_id]
            if any(fit.unavailable_reason is None for fit in fits):
                return {"state": "AVAILABLE", "reason": None}
            reason = next((fit.unavailable_reason for fit in fits if fit.unavailable_reason), None)
            return {"state": "UNAVAILABLE", "reason": reason or fallback}

        return {
            "historical": (
                {"state": "AVAILABLE", "reason": None}
                if self.historical_model is not None and self.historical_taxonomy is not None
                else {"state": "UNAVAILABLE", "reason": self.historical_unavailable_reason or "HISTORICAL_MODEL_UNAVAILABLE"}
            ),
            "temporal_delay": (
                {"state": "AVAILABLE", "reason": None}
                if self.temporal_delay_model is not None and self.temporal_delay_taxonomy is not None
                else {"state": "UNAVAILABLE", "reason": self.temporal_delay_unavailable_reason or unavailable_for("DELAY", "TEMPORAL") or "TEMPORAL_DELAY_MODEL_UNAVAILABLE"}
            ),
            "topology": channel_state("Dep_hop", unavailable_for("TOPOLOGY") or "TOPOLOGY_MAPPING_UNAVAILABLE"),
            "dependency": channel_state("Dep_hop", unavailable_for("DEPENDENCY") or "DEPENDENCY_EVIDENCE_UNAVAILABLE"),
        }

    def pair_why(self, chain_id: str, alarm_a: str, alarm_b: str):
        package = self.require_package()
        return evaluate_pair_channels(
            package,
            chain_id,
            alarm_a,
            alarm_b,
            delay_threshold=float(
                self.config.value("temporal.delay.support_threshold")
            ),
            d_max=int(self.config.value("dependency.max_hop")),
            lambda_dep=float(self.config.value("dependency.lambda_dep")),
            common_dependency_threshold=float(
                self.config.value("dependency.common_support_threshold")
            ),
            silent_gap_seconds=int(
                self.config.value("temporal.burst.gap_seconds")
            ),
            historical_model=self.historical_model,
            historical_taxonomy=self.historical_taxonomy,
            historical_unavailable_reason=self.historical_unavailable_reason,
            include_historical=True,
            temporal_delay_model=self.temporal_delay_model,
            temporal_delay_taxonomy=self.temporal_delay_taxonomy,
            temporal_delay_unavailable_reason=self.temporal_delay_unavailable_reason,
            temporal_delay_threshold_source=self.config.parameters[
                "temporal.delay.support_threshold"
            ].source.value,
            include_temporal_delay=True,
        )

    def _deep_dive_context(self, chain_id: str):
        package = self.require_package()
        similarity_context = None
        if (
            self.similarity_index is not None
            and chain_id in self.lineage_by_chain
        ):
            similarity_context = SimilarityQueryContext(
                index=self.similarity_index,
                target_lineage_component_id=self.lineage_by_chain[chain_id],
            )
        cache_key = self.jobs.cache_key_for(
            package,
            chain_id,
            analysis_config=self.config,
            similarity_context=similarity_context,
        )
        return package, similarity_context, cache_key

    def submit_deep_dive(self, chain_id: str):
        package, similarity_context, _ = self._deep_dive_context(chain_id)
        submission = self.jobs.submit(
            package,
            chain_id,
            analysis_config=self.config,
            similarity_context=similarity_context,
        )
        _record_quality_submission("deep-dive", submission)
        return submission

    def precompute_snapshot_deep_dive(self) -> dict[str, Any]:
        """Precompute Tier-2 Deep Dive in parallel for all multi-member chains in background."""
        if self._quality_background_owner:
            package = self.package
            return {
                "status": "BACKGROUND_WORKER",
                "snapshot": (
                    (package.snapshot.snapshot_id, package.snapshot.snapshot_version)
                    if package is not None
                    else None
                ),
                "submitted": 0,
                "total": 0,
            }
        with self._lock:
            package = self.package
            if package is None:
                return {"status": "NO_SNAPSHOT", "submitted": 0, "total": 0}
            snap_key = (
                package.snapshot.snapshot_id,
                package.snapshot.snapshot_version,
                _topology_version(package),
            )
            if snap_key in self._precomputed_snapshots:
                return {
                    "status": "ALREADY_PRECOMPUTED",
                    "snapshot": snap_key[:2],
                    "topology_version": snap_key[2],
                }
            self._precomputed_snapshots.add(snap_key)

        multi_member_chains = [
            cid for cid in package.chains
            if len(package.members_of(cid)) > 1
        ]
        # Sort so that chains with smaller member counts complete first (quick wins),
        # while larger chains continue computing in background worker pool
        multi_member_chains.sort(key=lambda cid: len(package.members_of(cid)))

        submitted = 0
        cache_hits = 0
        failures: list[dict[str, str]] = []
        for cid in multi_member_chains:
            try:
                sub = self.submit_deep_dive(cid)
                if getattr(sub, "cache_hit", False):
                    cache_hits += 1
                else:
                    submitted += 1
            except Exception as exc:
                failure = {
                    "chain_id": str(cid),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                failures.append(failure)
                # This used to be debug-only, which made the UI show a
                # permanent WAITING chain with no explanation.  Keep the
                # submission non-fatal, but make the exact reason observable
                # so the reconciler can retry it and operators can diagnose it.
                logger.warning(
                    "Failed to submit background deep dive for snapshot %s/%s chain %s: %s",
                    package.snapshot.snapshot_id,
                    package.snapshot.snapshot_version,
                    cid,
                    failure["error"],
                )

        return {
            "status": "QUEUED",
            "total_multi_member": len(multi_member_chains),
            "submitted": submitted,
            "cache_hits": cache_hits,
            "failed": len(failures),
            "failures": failures,
        }

    async def resume_snapshot_quality(self) -> dict[str, Any]:
        """Reconcile deterministic quality work that stopped mid-snapshot.

        ``precompute_snapshot_deep_dive`` is intentionally fire-and-forget,
        but a failed executor task must not leave a chain permanently in the
        UI's ``WAITING`` bucket.  This lightweight reconciliation runs from
        the summary poll: it retries only failed/missing in-process Deep Dive
        jobs and continues a completed Deep Dive into Counterfactual.  A
        persisted quality row wins, so completed chains are never resubmitted.
        """
        if self._quality_background_owner:
            return {
                "status": "BACKGROUND_WORKER",
                "deep_dive_submitted": 0,
                "review_submitted": 0,
            }
        if not self.auto_chain_quality or self.repository is None:
            return {"status": "DISABLED", "deep_dive_submitted": 0, "review_submitted": 0}
        package = self.package
        if package is None:
            return {"status": "NO_SNAPSHOT", "deep_dive_submitted": 0, "review_submitted": 0}

        snapshot_id = package.snapshot.snapshot_id
        snapshot_version = package.snapshot.snapshot_version
        expected_config_version = self.config.config_version
        expected_review_config_version = (
            self.config.counterfactual.config_version
            if self.config.counterfactual is not None
            else "UNAVAILABLE"
        )
        expected_topology_version = _topology_version(package)
        topology_known = snapshot_topology_profile(
            snapshot_id,
            getattr(getattr(package.snapshot, "topology_ref", None), "profile_id", None),
        ) is not None
        from .quality_freshness import terminal_quality_row_is_current
        try:
            assessments = await self.repository.list_chain_quality_assessments(
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
            )
        except Exception:
            logger.debug("Quality reconciliation could not read persisted assessments", exc_info=True)
            assessments = []
        completed = set()
        for row in assessments:
            if terminal_quality_row_is_current(
                row,
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
                config_version=expected_config_version,
                review_config_version=expected_review_config_version,
                topology_version=expected_topology_version,
                topology_version_known=topology_known,
            ):
                completed.add(str(row.chain_id))

        try:
            persisted_active = await self.repository.active_quality_chain_ids(
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
            )
        except Exception:
            logger.debug(
                "Quality reconciliation could not read active persisted jobs",
                exc_info=True,
            )
            persisted_active = set()

        deep_dive_submitted = 0
        review_submitted = 0
        failures: list[dict[str, str]] = []
        for chain_id in package.chains:
            if len(package.members_of(chain_id)) <= 1 or chain_id in completed:
                continue
            try:
                if await self._materialize_persisted_chain_quality_if_available(chain_id):
                    completed.add(str(chain_id))
                    continue
                _, _, cache_key = self._deep_dive_context(chain_id)
                deep_dive = self.jobs.latest_compatible(cache_key)
                if deep_dive is None and self.repository is not None:
                    # A restart may have persisted a completed Deep Dive while
                    # the in-memory Tier-2 manager is empty.  Hydrate that
                    # terminal artifact before deciding to submit duplicate
                    # work; otherwise the portfolio can remain WAITING or
                    # repeatedly recompute the same chain.
                    deep_dive = await self.latest_deep_dive(chain_id)
                deep_status = (
                    getattr(deep_dive.status, "value", str(deep_dive.status))
                    if deep_dive is not None
                    else None
                )
                if deep_status in {None, "FAILED", "INTERRUPTED"}:
                    if chain_id in persisted_active:
                        continue
                    self.submit_deep_dive(chain_id)
                    deep_dive_submitted += 1
                    continue
                if deep_status != "SUCCEEDED":
                    continue

                # _review_context is the canonical source of the current
                # Review identity (including its Tier-1B and compatible Audit
                # fingerprints). Do not infer currentness from only the
                # snapshot/chain tuple or topology field.
                expected_generation = self._analysis_generation
                expected_package = self.package
                expected_analysis_config = self.config.config_version
                expected_review_config = (
                    self.config.counterfactual.config_version
                    if self.config.counterfactual is not None
                    else "UNAVAILABLE"
                )
                _, _, _, expected_review_identity = await self._review_context(chain_id)
                if (
                    self._analysis_generation != expected_generation
                    or self.package is not expected_package
                    or expected_review_identity.snapshot_id != snapshot_id
                    or expected_review_identity.snapshot_version != snapshot_version
                    or expected_review_identity.chain_id != chain_id
                    or expected_review_identity.analysis_version != expected_analysis_config
                    or expected_review_identity.config_version != expected_review_config
                    or expected_review_identity.topology_version != expected_topology_version
                ):
                    # Snapshot/config/topology changed while canonical Audit
                    # context was loading. The next reconciliation pass will
                    # compute against the new generation.
                    continue

                review = self.review_jobs.latest_for_identity(expected_review_identity)
                if review is None and self.repository is not None:
                    repository_lookup = getattr(
                        self.repository,
                        "latest_counterfactual_job_for_identity",
                        None,
                    )
                    if callable(repository_lookup):
                        review = await repository_lookup(
                            snapshot_id=snapshot_id,
                            snapshot_version=snapshot_version,
                            chain_id=chain_id,
                            cache_fingerprint=artifact_fingerprint(
                                expected_review_identity.cache_tuple()
                            ),
                        )
                        if review is not None:
                            stored_identity = getattr(review, "identity", None)
                            adapted_identity = analysis_identity_from_review(
                                stored_identity,
                                pipeline_version=str(
                                    stored_identity.get("engine_version") or ""
                                ) if isinstance(stored_identity, dict) else "",
                                input_fingerprint=str(
                                    stored_identity.get("tier1b_artifact_fingerprint") or ""
                                ) if isinstance(stored_identity, dict) else "",
                            )
                            if (
                                not adapted_identity.available
                                or not isinstance(stored_identity, dict)
                                or stored_identity.get("snapshot_id") != review.snapshot_id
                                or stored_identity.get("snapshot_version") != review.snapshot_version
                                or stored_identity.get("chain_id") != review.chain_id
                            ):
                                review = None
                            else:
                                try:
                                    stored_review_identity = ReviewIdentity(**stored_identity)
                                except (TypeError, ValueError):
                                    review = None
                                else:
                                    if stored_review_identity.cache_tuple() != expected_review_identity.cache_tuple():
                                        review = None
                        if (
                            self._analysis_generation != expected_generation
                            or self.package is not expected_package
                        ):
                            continue
                review_status = (
                    getattr(review.status, "value", str(review.status))
                    if review is not None
                    else None
                )
                if review_status in {"QUEUED", "RUNNING", "SUCCEEDED"}:
                    continue
                submitted_review = await self.submit_review(chain_id)
                if submitted_review is not None:
                    review_submitted += 1
            except Exception as exc:
                failure = {
                    "chain_id": str(chain_id),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                failures.append(failure)
                logger.warning(
                    "Quality reconciliation could not resume snapshot %s/%s chain %s: %s",
                    snapshot_id,
                    snapshot_version,
                    chain_id,
                    failure["error"],
                )
        return {
            "status": "RECONCILED",
            "deep_dive_submitted": deep_dive_submitted,
            "review_submitted": review_submitted,
            "failed": len(failures),
            "failures": failures,
        }

    def schedule_snapshot_quality_resume(self) -> None:
        """Start at most one non-blocking quality reconciliation task."""
        if (
            self._closing
            or self._quality_background_owner
            or not self.auto_chain_quality
            or self.repository is None
        ):
            return
        current = self._quality_resume_task
        if current is not None and not current.done():
            return
        try:
            loop = self._persistence_loop or asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self.resume_snapshot_quality())
        self._quality_resume_task = task

        def _report_failure(done: asyncio.Task[Any]) -> None:
            if done.cancelled():
                return
            try:
                done.result()
            except Exception:
                logger.exception("Background deterministic quality reconciliation failed")

        task.add_done_callback(_report_failure)

    async def deep_dive_job(self, job_id: str):
        try:
            return self.jobs.get(job_id)
        except KeyError:
            if self.repository is None:
                raise
        await self.flush_deep_dive_persistence()
        stored = await self.repository.deep_dive_job(
            job_id, interrupt_active=True
        )
        if stored is None:
            raise KeyError(f"unknown Tier-2 job_id {job_id!r}")
        return stored

    async def latest_deep_dive(self, chain_id: str):
        package, _, cache_key = self._deep_dive_context(chain_id)
        in_memory = self.jobs.latest_compatible(cache_key)
        if in_memory is not None or self.repository is None:
            return in_memory
        await self.flush_deep_dive_persistence()
        return await self.repository.latest_compatible_deep_dive_job(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id=chain_id,
            cache_fingerprint=_cache_key_fingerprint(cache_key),
            interrupt_active=True,
        )

    async def latest_audit_visualization(
        self, chain_id: str
    ) -> AuditVisualizationLookup:
        """Read the latest compatible frozen projection without submitting work."""
        package = self.require_package()
        if chain_id not in package.chains:
            raise KeyError(f"unknown chain_id {chain_id!r}")
        members = package.members_of(chain_id)
        _, _, cache_key = self._deep_dive_context(chain_id)
        job = self.jobs.latest_compatible(cache_key)
        artifact = job.audit_artifact if job is not None else None
        if artifact is not None and not artifact.is_compatible(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id=chain_id,
            members=members,
            analysis_version=AUDIT_ANALYSIS_VERSION,
            analysis_config_version=self.config.config_version,
            topology_version=_topology_version(package),
        ):
            artifact = None
        if artifact is None and self.repository is not None:
            await self.flush_audit_persistence()
            artifact = await self.repository.latest_compatible_audit_artifact(
                snapshot_id=package.snapshot.snapshot_id,
                snapshot_version=package.snapshot.snapshot_version,
                chain_id=chain_id,
                chain_fingerprint=chain_membership_fingerprint(members),
                analysis_version=AUDIT_ANALYSIS_VERSION,
                analysis_config_version=self.config.config_version,
                topology_version=_topology_version(package),
            )
        if artifact is None:
            visualization = unavailable_audit_visualization(
                "AUDIT_ARTIFACT_NOT_AVAILABLE",
                total_node_count=len(members),
            )
        elif artifact.visualization is None:
            visualization = unavailable_audit_visualization(
                "BOUNDED_PUBLIC_AUDIT_GRAPH_ARTIFACT_NOT_AVAILABLE",
                total_node_count=len(members),
            )
        else:
            visualization = artifact.visualization
        return AuditVisualizationLookup(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id=chain_id,
            audit_artifact=artifact,
            visualization=visualization,
        )

    async def _review_context(self, chain_id: str):
        package = self.require_package()
        tier1b_artifact = self.analyze(chain_id)
        _, _, cache_key = self._deep_dive_context(chain_id)
        audit_view = self.jobs.latest_compatible(cache_key)
        audit_artifact = (
            audit_view.audit_artifact if audit_view is not None else None
        )
        members = package.members_of(chain_id)
        if audit_artifact is not None and not audit_artifact.is_compatible(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id=chain_id,
            members=members,
            analysis_version=AUDIT_ANALYSIS_VERSION,
            analysis_config_version=self.config.config_version,
            topology_version=_topology_version(package),
        ):
            audit_artifact = None
        if audit_artifact is None and self.repository is not None:
            await self.flush_audit_persistence()
            audit_artifact = await self.repository.latest_compatible_audit_artifact(
                snapshot_id=package.snapshot.snapshot_id,
                snapshot_version=package.snapshot.snapshot_version,
                chain_id=chain_id,
                chain_fingerprint=chain_membership_fingerprint(members),
                analysis_version=AUDIT_ANALYSIS_VERSION,
                analysis_config_version=self.config.config_version,
                topology_version=_topology_version(package),
            )
        if audit_artifact is not None and not audit_artifact.is_compatible(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id=chain_id,
            members=members,
            analysis_version=AUDIT_ANALYSIS_VERSION,
            analysis_config_version=self.config.config_version,
            topology_version=_topology_version(package),
        ):
            audit_artifact = None
        config = self.config.counterfactual
        identity = review_identity(
            package,
            chain_id,
            analysis_version=self.config.config_version,
            config_version=(
                config.config_version if config is not None else "UNAVAILABLE"
            ),
            tier1b_artifact=tier1b_artifact,
            audit_artifact=audit_artifact,
            external_artifact=None,
        )
        return package, tier1b_artifact, audit_artifact, identity

    async def submit_review(self, chain_id: str):
        if self._closing:
            return None
        with self._lock:
            expected_package = self.package
            expected_config = self.config
            expected_generation = self._analysis_generation
        package, tier1b_artifact, audit_artifact, identity = await self._review_context(chain_id)
        with self._lock:
            if (
                self._closing
                or self.package is not expected_package
                or package is not expected_package
                or self.config is not expected_config
                or self._analysis_generation != expected_generation
                or identity.snapshot_id != package.snapshot.snapshot_id
                or identity.snapshot_version != package.snapshot.snapshot_version
                or identity.chain_id != chain_id
                or identity.analysis_version != expected_config.config_version
                or identity.config_version != (
                    expected_config.counterfactual.config_version
                    if expected_config.counterfactual is not None
                    else "UNAVAILABLE"
                )
                or identity.topology_version != _topology_version(package)
            ):
                return None
        lineage_id = getattr(self, "lineage_by_chain", {}).get(chain_id)
        if lineage_id is None and self.package is not None:
            dag = self._get_or_build_local_evolution_dag()
            if dag is not None:
                k = LineageNodeKey(
                    self.package.snapshot.snapshot_id,
                    self.package.snapshot.snapshot_version,
                    chain_id,
                )
                lineage_id = dag.canonical_lineage(k)
                if lineage_id:
                    self.lineage_by_chain[chain_id] = lineage_id
        if lineage_id is None or lineage_id.startswith("fallback_lineage:"):
            lineage_id = "LINEAGE_UNAVAILABLE"
            self.lineage_by_chain[chain_id] = lineage_id
        if self._closing:
            return None
        with self._lock:
            if (
                self._closing
                or self.package is not expected_package
                or self.config is not expected_config
                or self._analysis_generation != expected_generation
            ):
                return None
        submission = self.review_jobs.submit(
            package,
            chain_id,
            tier1b_artifact=tier1b_artifact,
            audit_artifact=audit_artifact,
            analysis_config=expected_config,
            lineage_component_id=lineage_id,
        )
        _record_quality_submission("review", submission)
        return submission

    async def latest_review(self, chain_id: str):
        _, _, _, identity = await self._review_context(chain_id)
        in_memory = self.review_jobs.latest_compatible(identity)
        if in_memory is not None:
            return in_memory
        if self.repository is None:
            return None
        compatible = await self.repository.latest_compatible_counterfactual_job(
            snapshot_id=identity.snapshot_id,
            snapshot_version=identity.snapshot_version,
            chain_id=chain_id,
            cache_fingerprint=artifact_fingerprint(identity.cache_tuple()),
        )
        if compatible is not None:
            if not isinstance(compatible.identity, dict):
                return None
            adapted = analysis_identity_from_review(
                compatible.identity,
                pipeline_version=str(compatible.identity.get("engine_version") or ""),
                input_fingerprint=str(
                    compatible.identity.get("tier1b_artifact_fingerprint") or ""
                ),
            )
            if not adapted.available:
                return None
            if (
                compatible.identity.get("snapshot_id") != compatible.snapshot_id
                or compatible.identity.get("snapshot_version") != compatible.snapshot_version
                or compatible.identity.get("chain_id") != compatible.chain_id
            ):
                return None
            try:
                stored_identity = ReviewIdentity(**compatible.identity)
            except (TypeError, ValueError):
                return None
            if stored_identity.cache_tuple() != identity.cache_tuple():
                return None
            return compatible
        return None

    async def evolution(self, chain_id: str):
        package = self.require_package()
        if chain_id not in package.chains:
            raise KeyError(f"unknown chain_id {chain_id!r}")
        if self.repository is None:
            dag = self._get_or_build_local_evolution_dag()
            if dag is not None:
                current_key = LineageNodeKey(
                    package.snapshot.snapshot_id,
                    package.snapshot.snapshot_version,
                    chain_id,
                )
                canonical_id = dag.canonical_lineage(current_key)
                current_node = dag.nodes.get(current_key)
                if canonical_id is not None and current_node is not None:
                    member_nodes = [
                        n
                        for n in dag.nodes.values()
                        if dag.canonical_component_id(n.component_id) == canonical_id
                    ]
                    member_keys = {n.key for n in member_nodes}
                    member_edges = [
                        e
                        for (p_k, c_k), e in dag.edges.items()
                        if p_k in member_keys and c_k in member_keys
                    ]
                    if member_nodes:
                        nodes = tuple(
                            StoredEvolutionNode(
                                snapshot_id=n.key.snapshot_id,
                                snapshot_version=n.key.snapshot_version,
                                chain_id=n.key.snapshot_chain_id,
                                snapshot_time=_parse_iso_time(n.snapshot_time),
                                lineage_component_id=dag.canonical_component_id(
                                    n.component_id
                                ),
                                branch_id=n.branch_id,
                                source_kind=getattr(
                                    package.snapshot.source_kind,
                                    "value",
                                    str(package.snapshot.source_kind),
                                ),
                            )
                            for n in sorted(
                                member_nodes,
                                key=lambda x: (x.snapshot_time, x.key.snapshot_chain_id),
                            )
                        )
                        edges = tuple(
                            StoredEvolutionEdge(
                                parent_snapshot_id=e.parent.snapshot_id,
                                parent_snapshot_version=e.parent.snapshot_version,
                                parent_chain_id=e.parent.snapshot_chain_id,
                                child_snapshot_id=e.child.snapshot_id,
                                child_snapshot_version=e.child.snapshot_version,
                                child_chain_id=e.child.snapshot_chain_id,
                                event_type=e.edge_type,
                                overlap_count=e.overlap_count,
                                contain_parent=e.contain_parent,
                                contain_child=e.contain_child,
                            )
                            for e in sorted(
                                member_edges,
                                key=lambda x: (
                                    x.parent.snapshot_chain_id,
                                    x.child.snapshot_chain_id,
                                ),
                            )
                        )
                        return StoredEvolution(
                            status="AVAILABLE",
                            reason=None,
                            source_kind=getattr(
                                package.snapshot.source_kind,
                                "value",
                                str(package.snapshot.source_kind),
                            ),
                            sequence_status="VERIFIED",
                            production_validation="NOT_ESTABLISHED",
                            lineage_component_id=canonical_id,
                            branch_id=current_node.branch_id,
                            snapshot_id=package.snapshot.snapshot_id,
                            snapshot_version=package.snapshot.snapshot_version,
                            chain_id=chain_id,
                            nodes=nodes,
                            edges=edges,
                        )

            return StoredEvolution(
                status="UNAVAILABLE",
                reason="SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE",
                source_kind=getattr(
                    package.snapshot.source_kind,
                    "value",
                    package.snapshot.source_kind,
                ),
                sequence_status="UNAVAILABLE",
                production_validation="NOT_ESTABLISHED",
                lineage_component_id=None,
                branch_id=None,
                snapshot_id=package.snapshot.snapshot_id,
                snapshot_version=package.snapshot.snapshot_version,
                chain_id=chain_id,
            )
        return await self.repository.load_evolution(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id=chain_id,
        )

    async def record_operator_feedback(
        self,
        job_id: str,
        payload: dict[str, Any],
        principal: ReviewerPrincipal | None = None,
    ) -> dict[str, Any]:
        job = None
        try:
            job = self.review_jobs.get(job_id)
        except Exception:
            pass
        if job is None and self.repository is not None:
            job = await self.repository.counterfactual_job(job_id)

        if job is None:
            raise KeyError(f"unknown review job_id {job_id!r}")

        if getattr(job, "result", None) is None:
            raise ValueError("review job has not completed yet or result is unavailable")

        if isinstance(job, DomainCounterfactualJobView):
            result_dict = public_review_result(job.result)
        elif isinstance(job.result, dict):
            result_dict = job.result
        else:
            result_dict = dict(job.result)

        session = await self.review_learning._ensure_session_by_job_hydrated(job_id)
        review_id = self.review_learning.get_review_id_for_job(job_id)
        if session is None and review_id not in self.review_learning._sessions:
            chain_id_val = getattr(job, "chain_id", None) or result_dict.get("identity", {}).get("chain_id") or ""
            snapshot_id_val = result_dict.get("identity", {}).get("snapshot_id") or (
                getattr(job, "identity", {}).get("snapshot_id") if hasattr(job, "identity") else ""
            ) or ""
            snapshot_version_val = result_dict.get("identity", {}).get("snapshot_version") or (
                getattr(job, "identity", {}).get("snapshot_version") if hasattr(job, "identity") else "1"
            ) or "1"
            lineage_id = getattr(job, "lineage_component_id", None) or getattr(self, "lineage_by_chain", {}).get(str(chain_id_val))
            if lineage_id is None and self.package is not None:
                dag = self._get_or_build_local_evolution_dag()
                if dag is not None:
                    k = LineageNodeKey(
                        self.package.snapshot.snapshot_id,
                        self.package.snapshot.snapshot_version,
                        str(chain_id_val),
                    )
                    lineage_id = dag.canonical_lineage(k)
                    if lineage_id:
                        self.lineage_by_chain[str(chain_id_val)] = lineage_id
            if lineage_id is None:
                lineage_id = "LINEAGE_UNAVAILABLE"

            domain_val = getattr(job, "review_domain", None)
            if not domain_val and self.package is not None:
                if getattr(self.package, "topology", None) and isinstance(self.package.topology, dict):
                    domain_val = self.package.topology.get("domain")
            if not domain_val:
                domain_val = "UNKNOWN_DOMAIN"

            snapshot_obs_at = getattr(job, "snapshot_observed_at", None) or (
                (
                    getattr(self.package.snapshot, "observed_at", None)
                    or getattr(self.package.snapshot, "snapshot_time", None)
                    or getattr(self.package.snapshot, "produced_at", None)
                )
                if (self.package and getattr(self.package, "snapshot", None))
                else None
            )
            job_comp_at = getattr(job, "completed_at", None) or datetime.now(timezone.utc)
            rev_time = datetime.now(timezone.utc)
            source_k = getattr(job, "source_kind", None) or "SOURCE_KIND_UNAVAILABLE"

            context = ImmutableReviewSnapshotContext(
                snapshot_id=str(snapshot_id_val),
                snapshot_version=str(snapshot_version_val),
                chain_id=str(chain_id_val),
                review_time=rev_time,
                snapshot_observed_at=snapshot_obs_at,
                job_completed_at=job_comp_at,
                review_domain=domain_val,
                generator_version=getattr(job, "generator_version", "v1") if hasattr(job, "generator_version") else "v1",
                config_version="v1",
                exposure_policy_version="ALL_EVALUATED",
                source_kind=source_k,
                lineage_component_id=lineage_id,
            )
            session = await self.review_learning.freeze_review_bundle(
                job_id=job_id,
                job_view=job,
                package=self.package,
                delay_model=self.temporal_delay_model,
                taxonomy=self.temporal_delay_taxonomy or self.historical_taxonomy_source,
                config_version="v1",
                exposure_policy="ALL_EVALUATED",
                context=context,
            )
        elif session is None:
            session = self.review_learning._sessions.get(review_id)

        try:
            decision = normalize_review_decision(payload["decision"])
        except ValueError as exc:
            raise ValueError(f"invalid decision {payload['decision']!r}") from exc

        candidate_id = payload.get("candidate_id")
        evaluated = {
            str(candidate.get("candidate_id")): candidate
            for candidate in result_dict.get("evaluated_candidates", [])
            if isinstance(candidate, dict) and candidate.get("candidate_id")
        }
        recommendation_ids = {
            str(reference.get("candidate_id"))
            for reference in result_dict.get("recommendations", [])
            if isinstance(reference, dict) and reference.get("candidate_id")
        }
        for reference in result_dict.get("recommendations", []):
            if isinstance(reference, dict) and reference.get("operation"):
                evaluated.setdefault(str(reference["candidate_id"]), reference)

        if decision == ReviewDecision.NONE_ACCEPTABLE:
            candidate_id = None
            candidate = {}
        elif decision == ReviewDecision.MANUAL_CORRECTION and not candidate_id:
            candidate_id = None
            candidate = {}
        else:
            if not candidate_id or (candidate_id not in recommendation_ids and candidate_id not in evaluated):
                raise ValueError(
                    f"candidate_id {candidate_id!r} is not an operator-facing recommendation "
                    f"for review job {job_id!r}"
                )
            candidate = evaluated.get(candidate_id, {})

        mc_dict = payload.get("manual_correction") or {}
        operation = mc_dict.get("operation") or candidate.get("operation", "UNKNOWN")
        partition_delta = mc_dict.get("partition_delta") or candidate.get("partition_delta", {})

        chain_id = getattr(job, "chain_id", None) or result_dict.get("identity", {}).get("chain_id")
        snapshot_id = result_dict.get("identity", {}).get("snapshot_id") or (
            getattr(job, "identity", {}).get("snapshot_id") if hasattr(job, "identity") else None
        )
        snapshot_version = result_dict.get("identity", {}).get("snapshot_version") or (
            getattr(job, "identity", {}).get("snapshot_version") if hasattr(job, "identity") else "1"
        )

        if principal is None:
            subject = (
                os.environ.get("REVIEW_LOCAL_SUBJECT")
                or os.environ.get("LOCAL_DEV_OPERATOR_ID")
                or "local_dev_operator"
            )
            role = (
                os.environ.get("REVIEW_LOCAL_ROLE")
                or os.environ.get("LOCAL_DEV_OPERATOR_ROLE")
                or "PRODUCT_OWNER"
            )
            scope_env = (
                os.environ.get("REVIEW_LOCAL_DOMAIN_SCOPE")
                or os.environ.get("LOCAL_DEV_DOMAIN_SCOPE")
            )
            domain_scope = (
                tuple(s.strip() for s in scope_env.split(",") if s.strip()) if scope_env else ("IP_NETWORK", "IT_SERVICES", "UNKNOWN_DOMAIN")
            )
            principal = ReviewerPrincipal(
                subject=subject,
                role=role,
                domain_scope=domain_scope,
                auth_type="LOCAL_DEV",
            )

        if session is not None:
            verify_domain_authorization(principal, session.review_domain)

        fb = await self.review_learning.record_feedback(
            job_id=job_id,
            submission={**payload, "candidate_id": candidate_id, "decision": decision.value},
            principal=principal,
            package=self.package,
        )

        record: dict[str, Any] = {
            "feedback_id": fb.feedback_id,
            "review_id": fb.review_id,
            "job_id": job_id,
            "snapshot_id": str(snapshot_id or ""),
            "snapshot_version": str(snapshot_version or "1"),
            "chain_id": str(chain_id or ""),
            "candidate_id": fb.candidate_id,
            "operation": operation,
            "decision": fb.decision.value,
            "operator_id": fb.reviewer_subject,
            "confidence": fb.confidence,
            "reviewer_subject": fb.reviewer_subject,
            "reviewer_role": fb.reviewer_role,
            "domain_scope": list(fb.domain_scope),
            "truth_tier": fb.truth_tier.value,
            "reason": fb.reason_text,
            "reason_policy_version": fb.reason_policy_version,
            "reason_codes": list(fb.reason_codes),
            "partition_delta": (
                fb.manual_correction.partition_delta
                if fb.manual_correction is not None
                else partition_delta
            ),
            "created_at": fb.created_at,
        }

        self.operator_feedbacks.append(record)

        return record

    async def list_operator_feedback(
        self,
        job_id: str | None = None,
        chain_id: str | None = None,
        principal: ReviewerPrincipal | None = None,
    ) -> list[Any]:
        # Validate job existence and domain authorization when job_id is specified
        if job_id is not None:
            session = None
            if self.repository is not None:
                session = await self.review_learning._ensure_session_by_job_hydrated(job_id)
            else:
                rev_id = self.review_learning.get_review_id_for_job(job_id)
                session = self.review_learning._sessions.get(rev_id) or self.review_learning._sessions.get(job_id)

            job = None
            try:
                job = self.review_jobs.get(job_id)
            except Exception:
                pass
            if job is None and self.repository is not None:
                job = await self.repository.counterfactual_job(job_id)

            if session is None and job is None:
                raise KeyError(f"unknown review job_id {job_id!r}")

            if principal is not None:
                domain = None
                if session is not None and getattr(session, "review_domain", None):
                    domain = session.review_domain
                elif job is not None:
                    domain = getattr(job, "review_domain", None)
                    if not domain and hasattr(job, "topology") and isinstance(job.topology, dict):
                        domain = job.topology.get("domain")
                if domain is not None:
                    principal.verify_domain_authorization(domain)

        if self.repository is not None:
            pairs = await self.repository.active_review_feedback_with_sessions(
                job_id=job_id, chain_id=chain_id
            )
            if principal is not None:
                for item in pairs:
                    sess = item.get("session")
                    if sess is None:
                        raise ReviewSessionNotFound(
                            "Historical feedback is missing its immutable review-session provenance"
                        )
                    principal.verify_domain_authorization(sess.review_domain)

            results = []
            for item in pairs:
                fb = item["feedback"]
                session = item.get("session")
                operation = ""
                if session is not None and fb.candidate_id:
                    exposures = self.review_learning._exposures.get(session.review_id)
                    if exposures is None:
                        exposures = await self.repository.get_candidate_exposures(session.review_id)
                    operation = next(
                        (exp.operation for exp in exposures if exp.candidate_id == fb.candidate_id),
                        "",
                    )
                results.append({
                    "feedback_id": fb.feedback_id,
                    "review_id": fb.review_id,
                    "job_id": session.job_id if session else (job_id or ""),
                    "snapshot_id": session.snapshot_id if session else "",
                    "snapshot_version": session.snapshot_version if session else "1",
                    "chain_id": session.chain_id if session else (chain_id or ""),
                    "candidate_id": fb.candidate_id or "",
                    "operation": operation,
                    "decision": fb.decision.value if hasattr(fb.decision, "value") else str(fb.decision),
                    "operator_id": fb.reviewer_subject,
                    "confidence": fb.confidence,
                    "reviewer_subject": fb.reviewer_subject,
                    "reviewer_role": fb.reviewer_role,
                    "domain_scope": list(fb.domain_scope),
                    "truth_tier": fb.truth_tier.value if hasattr(fb.truth_tier, "value") else str(fb.truth_tier),
                    "supersedes_feedback_id": fb.supersedes_feedback_id,
                    "reason": fb.reason_text,
                    "reason_policy_version": fb.reason_policy_version,
                    "reason_codes": list(fb.reason_codes),
                    "created_at": fb.created_at,
                })
            return results

        active_ids = set(self.review_learning._active_feedbacks.keys())
        results = [
            f for f in self.operator_feedbacks
            if f.get("feedback_id") in active_ids or "feedback_id" not in f
        ]
        if job_id is not None:
            results = [f for f in results if f.get("job_id") == job_id]
        if chain_id is not None:
            results = [f for f in results if f.get("chain_id") == chain_id]

        if principal is not None:
            for f in results:
                rev_id = f.get("review_id") or self.review_learning.get_review_id_for_job(
                    str(f.get("job_id", ""))
                )
                sess = self.review_learning._sessions.get(rev_id) if rev_id else None
                if sess is None:
                    raise ReviewSessionNotFound(
                        "Historical feedback is missing its immutable review-session provenance"
                    )
                principal.verify_domain_authorization(sess.review_domain)

        return results

    async def record_candidate_display_events(
        self,
        job_id: str,
        events: Sequence[dict[str, Any]],
        principal: ReviewerPrincipal,
    ) -> int:
        return await self.review_learning.record_display_events(
            job_id=job_id, events_payload=events, principal=principal
        )

    async def supersede_operator_feedback(
        self,
        job_id: str,
        supersedes_feedback_id: str,
        payload: dict[str, Any],
        principal: ReviewerPrincipal,
    ) -> dict[str, Any]:
        session = await self.review_learning._ensure_session_by_job_hydrated(job_id)
        if session is not None:
            verify_domain_authorization(principal, session.review_domain)

        fb = await self.review_learning.supersede_feedback(
            job_id=job_id,
            supersedes_feedback_id=supersedes_feedback_id,
            submission=payload,
            principal=principal,
            package=self.package,
        )
        record = {
            "feedback_id": fb.feedback_id,
            "review_id": fb.review_id,
            "job_id": job_id,
            "chain_id": session.chain_id if session is not None else "",
            "candidate_id": fb.candidate_id or "",
            "decision": fb.decision.value,
            "operator_id": fb.reviewer_subject,
            "confidence": fb.confidence,
            "reviewer_subject": fb.reviewer_subject,
            "reviewer_role": fb.reviewer_role,
            "domain_scope": list(fb.domain_scope),
            "truth_tier": fb.truth_tier.value,
            "supersedes_feedback_id": fb.supersedes_feedback_id,
            "reason": fb.reason_text,
            "reason_policy_version": fb.reason_policy_version,
            "reason_codes": list(fb.reason_codes),
            "partition_delta": (
                fb.manual_correction.partition_delta
                if fb.manual_correction is not None
                else ((payload.get("manual_correction") or {}).get("partition_delta", {}))
            ),
            "created_at": fb.created_at,
        }
        self.operator_feedbacks.append(record)
        return record

    async def retract_operator_feedback(
        self,
        job_id: str,
        feedback_id: str,
        principal: ReviewerPrincipal,
        reason: str | None = None,
    ) -> None:
        session = await self.review_learning._ensure_session_by_job_hydrated(job_id)
        if session is not None:
            verify_domain_authorization(principal, session.review_domain)

        await self.review_learning.retract_feedback(
            job_id=job_id,
            feedback_id=feedback_id,
            principal=principal,
            reason=reason,
        )

    def _seed_dev_review_cases(self) -> None:
        """Seed representative historical review cases in development mode for similarity retrieval."""
        try:
            from review_learning.case_fingerprint import (
                FINGERPRINT_SCHEMA_VERSION,
                compute_case_fingerprint_payload,
            )
            from review_learning.contracts import ReviewCase, ReviewDecision, TruthTier

            cases_data = [
                (
                    "case_hist_vlg106_remove_01",
                    "rev_hist_vlg106_01",
                    "fb_hist_01",
                    "REMOVE_MEMBER",
                    ReviewDecision.APPROVE,
                    "lineage_vlg106_ip",
                    {
                        "operation_pattern": {"operation": "REMOVE_MEMBER", "removed_alarm_count": 1},
                        "chain_context": {"alarm_count": 5, "device_count": 3, "unique_alarm_type_count": 3, "failure_domain_count": 1},
                        "temporal_shape": {"status": "AVAILABLE", "coverage_ratio": 0.85, "mean_positive_score": 0.72},
                        "evidence_shape": {"channels_available": 3, "channels_total": 3},
                        "topology_shape": {"status": "AVAILABLE", "relation_type": "SERVICE_DEPENDENCY", "mapping_coverage": 1.0},
                    },
                ),
                (
                    "case_hist_vlg106_split_02",
                    "rev_hist_vlg106_02",
                    "fb_hist_02",
                    "SPLIT_CHAIN",
                    ReviewDecision.APPROVE,
                    "lineage_vlg106_ip",
                    {
                        "operation_pattern": {"operation": "SPLIT_CHAIN", "split_partition_count": 2},
                        "chain_context": {"alarm_count": 8, "device_count": 5, "unique_alarm_type_count": 4, "failure_domain_count": 2},
                        "temporal_shape": {"status": "AVAILABLE", "coverage_ratio": 0.90, "mean_positive_score": 0.81},
                        "evidence_shape": {"channels_available": 3, "channels_total": 3},
                        "topology_shape": {"status": "AVAILABLE", "relation_type": "SERVICE_DEPENDENCY", "mapping_coverage": 0.95},
                    },
                ),
                (
                    "case_hist_bte0049_move_03",
                    "rev_hist_bte0049_03",
                    "fb_hist_03",
                    "MOVE_MEMBER",
                    ReviewDecision.REJECT,
                    "lineage_bte0049_ip",
                    {
                        "operation_pattern": {"operation": "MOVE_MEMBER"},
                        "chain_context": {"alarm_count": 6, "device_count": 4, "unique_alarm_type_count": 3, "failure_domain_count": 1},
                        "temporal_shape": {"status": "AVAILABLE", "coverage_ratio": 0.70, "mean_positive_score": 0.60},
                        "evidence_shape": {"channels_available": 2, "channels_total": 3},
                        "topology_shape": {"status": "AVAILABLE", "relation_type": "SERVICE_DEPENDENCY", "mapping_coverage": 0.80},
                    },
                ),
                (
                    "case_hist_vlg_merge_04",
                    "rev_hist_vlg_04",
                    "fb_hist_04",
                    "MERGE_CHAINS",
                    ReviewDecision.APPROVE,
                    "lineage_vlg_agg_ip",
                    {
                        "operation_pattern": {"operation": "MERGE_CHAINS"},
                        "chain_context": {"alarm_count": 7, "device_count": 4, "unique_alarm_type_count": 3, "failure_domain_count": 2},
                        "temporal_shape": {"status": "AVAILABLE", "coverage_ratio": 0.80, "mean_positive_score": 0.75},
                        "evidence_shape": {"channels_available": 3, "channels_total": 3},
                        "topology_shape": {"status": "AVAILABLE", "relation_type": "SERVICE_DEPENDENCY", "mapping_coverage": 0.90},
                    },
                ),
            ]

            t_base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
            for domain in ("IP_NETWORK", "UNKNOWN_DOMAIN"):
                for cid, rid, fbid, op, decision, lineage_id, blocks in cases_data:
                    full_cid = f"{cid}_{domain.lower()}"
                    payload, f_hash = compute_case_fingerprint_payload(blocks)
                    rc = ReviewCase(
                        case_id=full_cid,
                        review_id=f"{rid}_{domain.lower()}",
                        feedback_id=f"{fbid}_{domain.lower()}",
                        case_time=t_base,
                        lineage_component_id=lineage_id,
                        operation_pattern=op,
                        fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
                        fingerprint_payload=payload,
                        fingerprint_hash=f_hash,
                        case_domain=domain,
                        truth_tier=TruthTier.PO_ASSERTED,
                        decision=decision,
                        status="ACTIVE",
                        created_at=t_base,
                    )
                    self.review_learning._review_cases[full_cid] = rc
        except Exception:
            logger.exception("Failed to seed development review cases")

    async def find_similar_cases_for_candidate(
        self,
        job_id: str,
        candidate_id: str,
        *,
        principal: ReviewerPrincipal,
        top_k: int = 5,
        min_common_blocks: int = 2,
    ) -> list[Any]:
        # Ensure session and exposures are hydrated if job exists in memory or repo
        rev_id = self.review_learning.get_review_id_for_job(job_id)
        if rev_id not in self.review_learning._sessions:
            try:
                job = self.review_jobs.get(job_id)
                if job is not None and getattr(job, "result", None) is not None:
                    session, exposures = self.review_learning.prepare_review_bundle(
                        job_id=job_id,
                        job_view=job,
                        package=self.package,
                    )
                    self.review_learning.register_persisted_bundle(session, exposures)
            except Exception:
                pass
        return await self.review_learning.find_similar_cases_for_candidate(
            job_id=job_id,
            candidate_id=candidate_id,
            principal=principal,
            top_k=top_k,
            min_common_blocks=min_common_blocks,
            package=self.package,
        )

    def get_review_learning_status(self) -> dict[str, Any]:
        manifest = self.review_learning._ranker_manifest
        model = self.review_learning._ranker_model
        loaded = model is not None

        # Read data profile if available
        art_dir = os.environ.get("NOCPRO_REVIEW_RANKER_ARTIFACT_DIR")

        data_profile = None
        if art_dir:
            dp_file = Path(art_dir) / "data_profile.json"
            if dp_file.exists():
                try:
                    with open(dp_file, "r", encoding="utf-8") as f:
                        data_profile = json.load(f)
                except Exception:
                    pass

        # Feature importances with domain descriptions
        feature_importances: list[dict[str, Any]] = []
        if loaded and hasattr(model, "feature_importances_"):
            from review_learning import FEATURE_NAMES
            feature_descriptions = {
                "delta__component_count": "Số lượng phân mảnh / chain sau thay đổi",
                "op__remove": "Thao tác loại bỏ cảnh báo ngoại lai (REMOVE_MEMBER)",
                "delta__audit_verdict_severity": "Mức độ giảm độ nghiêm trọng lỗi audit",
                "delta__weak_member_count": "Giảm số lượng cảnh báo liên kết yếu",
                "temporal__delay_score_mean": "Điểm trễ lan truyền thời gian trung bình",
                "op__move": "Thao tác di chuyển cảnh báo sang chuỗi phù hợp (MOVE_MEMBER)",
                "op__split": "Thao tác tách chuỗi cảnh báo quá dài (SPLIT_CHAIN)",
                "op__merge": "Thao tác hợp nhất các cụm cảnh báo liên kết (MERGE_CHAINS)",
                "delta__conductance": "Độ cô lập cụm cảnh báo (Conductance)",
                "delta__cut_ratio": "Tỷ lệ cắt liên kết biên ngoài cụm (Cut ratio)",
                "delta__max_hop": "Đường kính phân tán topology cực đại",
                "temporal__coverage_ratio": "Tỷ lệ bao phủ quan trắc chuỗi theo thời gian",
                "topology__mapping_coverage": "Tỷ lệ ánh xạ topology thiết bị hạ tầng",
                "delta__external_edge_count": "Số lượng cạnh liên kết ngoại lai",
                "temporal__positive_ratio": "Tỷ lệ tương quan dương theo chuỗi trễ",
                "temporal__min_p_forward": "Xác suất truyền lan tối thiểu về phía trước",
            }
            raw_imps = model.feature_importances_
            for i, val in enumerate(raw_imps):
                f_name = FEATURE_NAMES[i] if i < len(FEATURE_NAMES) else f"feature_{i}"
                if val > 0.0001:
                    feature_importances.append({
                        "feature": f_name,
                        "importance": round(float(val), 4),
                        "description": feature_descriptions.get(f_name, f_name),
                    })
            feature_importances.sort(key=lambda x: x["importance"], reverse=True)

        # Validation Metrics
        metrics_dict: dict[str, Any] = {}
        if manifest and getattr(manifest, "metrics", None):
            m = manifest.metrics
            if hasattr(m, "__dict__"):
                metrics_dict = {
                    k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in m.__dict__.items()
                    if not k.startswith("_")
                }
            elif isinstance(m, dict):
                metrics_dict = m

        # Feedback summary
        active_fb = self.review_learning._active_feedbacks
        action_counts: dict[str, int] = {}
        for fb in active_fb.values():
            action_name = fb.decision.value if hasattr(fb.decision, "value") else str(fb.decision)
            action_counts[action_name] = action_counts.get(action_name, 0) + 1

        return {
            "loaded": loaded,
            "model_version": getattr(manifest, "model_version", None) if manifest else None,
            "model_family": getattr(manifest, "model_family", "xgboost-ranker") if manifest else None,
            "approval_status": getattr(manifest, "approval_status", "DRAFT") if manifest else None,
            "feature_schema_version": getattr(manifest, "feature_schema_version", None) if manifest else None,
            "label_policy_version": getattr(manifest, "label_policy_version", None) if manifest else None,
            "abstention_threshold": float(self.review_learning.abstention_threshold),
            "artifact_sha256": getattr(manifest, "artifact_sha256", None) if manifest else None,
            "created_at": getattr(manifest, "created_at", None) if manifest else None,
            "training_cutoff": getattr(manifest, "training_cutoff", None) if manifest else None,
            "hyperparameters": getattr(manifest, "hyperparameters", {}) if manifest else {},
            "metrics": metrics_dict,
            "feature_importances": feature_importances,
            "data_profile": data_profile,
            "training_available": False,
            "training_reason": "ONLINE_TRAINING_DISABLED: use the audited PostgreSQL batch pipeline after operator-confirmed feedback passes readiness checks.",
            "artifact_source_kind_mix": (data_profile or {}).get("source_kind_mix", {}),
            "artifact_truth_tier_distribution": (data_profile or {}).get("truth_tier_distribution", {}),
            "feedback_summary": {
                "active_feedback_count": len(active_fb),
                "superseded_feedback_count": len(self.review_learning._superseded_feedbacks),
                "action_counts": action_counts,
            },
            "disclaimer": "Historical reference only — not probability or automated recommendation. Model outputs are subject to human operator governance.",
        }

    async def trigger_ranker_training(self) -> dict[str, Any]:
        """Online API training is intentionally disabled to prevent synthetic labels."""
        raise RuntimeError(
            "ONLINE_TRAINING_DISABLED: run the audited PostgreSQL batch pipeline only after confirmed feedback passes readiness checks."
        )
