"""In-process repository/service boundary used by the HTTP adapter."""

from __future__ import annotations

import os
import json
import hashlib
import asyncio
import uuid
from concurrent.futures import Future
from dataclasses import asdict, dataclass, replace

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

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
from tier1a import CacheTier, SnapshotPrecompute, Tier1Cache, precompute_snapshot
from tier1b import analyze_chain_configured
from tier2 import (
    AUDIT_ANALYSIS_VERSION,
    AuditVisualization,
    ReviewAuditArtifact,
    SimilarityQueryContext,
    Tier2JobManager,
    chain_membership_fingerprint,
    unavailable_audit_visualization,
)
from tier2.counterfactual import (
    CounterfactualJobManager,
    CounterfactualJobView as DomainCounterfactualJobView,
    artifact_fingerprint,
    review_identity,
)
from tier2.counterfactual.public_contract import public_review_result


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
        self.jobs = Tier2JobManager(cache=self.cache)
        self.review_jobs = CounterfactualJobManager()
        self.package: IngestedPackage | None = None
        self.precompute: SnapshotPrecompute | None = None
        self._lock = RLock()
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
        self._local_evolution_dag: GlobalEpisodeDag | None = None

    def _get_job_persistence_lock(self, job_id: str) -> asyncio.Lock:
        lock = self._job_persistence_locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            self._job_persistence_locks[job_id] = lock
        return lock

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

    def update_parameters(self, overrides: dict[str, float | int]) -> dict[str, Any]:
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

        with self._lock:
            self._custom_config_counter += 1
            param_str = json.dumps(
                sorted((str(k), float(v) if isinstance(v, (int, float)) else str(v)) for k, v in normalized_overrides.items()),
                sort_keys=True,
            )
            param_hash = hashlib.sha256(param_str.encode("utf-8")).hexdigest()[:8]
            base_ver = self.config.config_version.split("-custom-")[0]
            new_version = f"{base_ver}-custom-{self._custom_config_counter}-{param_hash}"

            new_parameters = dict(self.config.parameters)
            for path, val in normalized_overrides.items():
                new_parameters[path] = ConfiguredValue(
                    path=path,
                    value=val,
                    source=ParameterSource.SYSTEM_PROVIDED,
                )

            self.config = replace(
                self.config,
                config_version=new_version,
                parameters=new_parameters,
            )
            self.cache.entries.clear()
            self.jobs.cache.entries.clear()

        return self.get_active_parameters()

    def reset_parameters(self) -> dict[str, Any]:
        with self._lock:
            # Reset strictly to the initial startup base configuration (e.g. v1.yaml)
            self.config = load_analysis_config(self._base_config_path)
            self.cache.entries.clear()
            self.jobs.cache.entries.clear()
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
            self.cache.entries.clear()
            self.jobs.cache.entries.clear()

        return asdict(report)


    def close(self) -> None:
        self.review_jobs.shutdown()
        self.review_jobs.set_state_listener(None)
        self.jobs.shutdown()
        self.jobs.set_state_listener(None)
        self.jobs.set_artifact_listener(None)

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
                    async with self._get_job_persistence_lock(view.job_id):
                        await repository.persist_succeeded_job_and_review_bundle(
                            view.persistence_payload(), session, exposures
                        )
                        self.review_learning.register_persisted_bundle(session, exposures)

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
                    async with self._get_job_persistence_lock(view.job_id):
                        await repository.persist_counterfactual_job(view.persistence_payload())

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
            future = asyncio.run_coroutine_threadsafe(
                repository.persist_deep_dive_job(
                    {
                        **public,
                        "snapshot_id": view.cache_key.snapshot_id,
                        "snapshot_version": view.cache_key.snapshot_version,
                        "cache_fingerprint": _cache_key_fingerprint(view.cache_key),
                    }
                ),
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
        if (
            self.precompute is not None
            and self.package is not None
            and self.package.snapshot.snapshot_id == result.snapshot_id
            and self.package.snapshot.snapshot_version == result.snapshot_version
        ):
            return self.precompute
        # An explicit catalog selection is allowed to reactivate an identical
        # durable snapshot.  ``ingest_direct`` has already checked that the
        # identity and canonical payload are an exact match, so recomputing
        # the local Tier-1A view is safe and does not mutate evidence rows.
        package, precompute = self.compute_snapshot(payload)
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
            self.package = package
            self.precompute = result
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
        return self.jobs.submit(
            package,
            chain_id,
            analysis_config=self.config,
            similarity_context=similarity_context,
        )

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
        job = self.jobs.latest_succeeded(
            package.snapshot.snapshot_id,
            package.snapshot.snapshot_version,
            chain_id,
        )
        artifact = job.audit_artifact if job is not None else None
        if artifact is not None and not artifact.is_compatible(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id=chain_id,
            members=members,
            analysis_version=AUDIT_ANALYSIS_VERSION,
            analysis_config_version=self.config.config_version,
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
        audit_view = self.jobs.latest_succeeded(
            package.snapshot.snapshot_id,
            package.snapshot.snapshot_version,
            chain_id,
        )
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
            )
        if audit_artifact is not None and not audit_artifact.is_compatible(
            snapshot_id=package.snapshot.snapshot_id,
            snapshot_version=package.snapshot.snapshot_version,
            chain_id=chain_id,
            members=members,
            analysis_version=AUDIT_ANALYSIS_VERSION,
            analysis_config_version=self.config.config_version,
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
        package, tier1b_artifact, audit_artifact, _ = await self._review_context(
            chain_id
        )
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
        return self.review_jobs.submit(
            package,
            chain_id,
            tier1b_artifact=tier1b_artifact,
            audit_artifact=audit_artifact,
            analysis_config=self.config,
            lineage_component_id=lineage_id,
        )

    async def latest_review(self, chain_id: str):
        _, _, _, identity = await self._review_context(chain_id)
        in_memory = self.review_jobs.latest_compatible(identity)
        if in_memory is not None or self.repository is None:
            return in_memory
        return await self.repository.latest_compatible_counterfactual_job(
            snapshot_id=identity.snapshot_id,
            snapshot_version=identity.snapshot_version,
            chain_id=chain_id,
            cache_fingerprint=artifact_fingerprint(identity.cache_tuple()),
        )

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
                    if member_edges:
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
        else:
            if not candidate_id or (candidate_id not in recommendation_ids and candidate_id not in evaluated):
                raise ValueError(
                    f"candidate_id {candidate_id!r} is not an operator-facing recommendation "
                    f"for review job {job_id!r}"
                )
            candidate = evaluated.get(candidate_id, {})

        operation = candidate.get("operation", "UNKNOWN")
        partition_delta = candidate.get("partition_delta", {})

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
            "job_id": job_id,
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

    async def find_similar_cases_for_candidate(
        self, job_id: str, candidate_id: str, *, principal: ReviewerPrincipal, top_k: int = 5
    ) -> list[Any]:
        return await self.review_learning.find_similar_cases_for_candidate(
            job_id=job_id,
            candidate_id=candidate_id,
            principal=principal,
            top_k=top_k,
            package=self.package,
        )
