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
        self._local_evolution_dag: GlobalEpisodeDag | None = None

    def _get_or_build_local_evolution_dag(self) -> GlobalEpisodeDag | None:
        if self._local_evolution_dag is not None:
            return self._local_evolution_dag
        try:
            mock_root = Path(
                os.environ.get(
                    "NOCPRO_MOCK_ROOT",
                    str(ROOT.parent / "nocpro-mock"),
                )
            )
            evo_dir = mock_root / "datasets" / "generated" / "real_ip_evolution_sample"
            if not evo_dir.exists():
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
            for fname in ["snapshot_000.json", "snapshot_001.json", "snapshot_002.json"]:
                fpath = evo_dir / fname
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
            await asyncio.gather(
                *(asyncio.wrap_future(future) for future in pending),
                return_exceptions=False,
            )

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
        self._persistence_loop = asyncio.get_running_loop()

        def persist_review_state(view) -> None:
            future = asyncio.run_coroutine_threadsafe(
                repository.persist_counterfactual_job(view.persistence_payload()),
                self._persistence_loop,
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
        raise RuntimeError("snapshot already persisted but is not active in this process")

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
        self, payload: dict[str, Any]
    ) -> tuple[IngestedPackage, SnapshotPrecompute]:
        """Build Tier-1A state without changing the currently served snapshot."""
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
        return self.review_jobs.submit(
            package,
            chain_id,
            tier1b_artifact=tier1b_artifact,
            audit_artifact=audit_artifact,
            analysis_config=self.config,
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
        self, job_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        job = None
        try:
            job = self.review_jobs.get(job_id)
        except KeyError:
            if self.repository is not None:
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

        candidate_id = payload["candidate_id"]
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
        # Legacy artifacts could contain fully materialized recommendation
        # candidates. They are still operator-facing only when explicitly
        # present in that recommendations list.
        for reference in result_dict.get("recommendations", []):
            if isinstance(reference, dict) and reference.get("operation"):
                evaluated.setdefault(str(reference["candidate_id"]), reference)

        if candidate_id not in recommendation_ids:
            raise ValueError(
                f"candidate_id {candidate_id!r} is not an operator-facing recommendation "
                f"for review job {job_id!r}"
            )
        candidate = evaluated.get(candidate_id)
        if candidate is None:
            raise ValueError(
                f"candidate_id {candidate_id!r} is referenced by recommendations "
                "but its evaluated detail is unavailable"
            )

        operation = candidate.get("operation", "UNKNOWN")
        partition_delta = candidate.get("partition_delta", {})

        decision = payload["decision"].upper()
        if decision not in {"APPROVED", "REJECTED", "ACCEPTED"}:
            raise ValueError(f"invalid decision {payload['decision']!r}")

        chain_id = getattr(job, "chain_id", None) or result_dict.get("identity", {}).get("chain_id")
        snapshot_id = result_dict.get("identity", {}).get("snapshot_id") or (
            getattr(job, "identity", {}).get("snapshot_id") if hasattr(job, "identity") else None
        )
        snapshot_version = result_dict.get("identity", {}).get("snapshot_version") or (
            getattr(job, "identity", {}).get("snapshot_version") if hasattr(job, "identity") else "1"
        )

        feedback_id = f"fb_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        record: dict[str, Any] = {
            "feedback_id": feedback_id,
            "job_id": job_id,
            "snapshot_id": str(snapshot_id or ""),
            "snapshot_version": str(snapshot_version or "1"),
            "chain_id": str(chain_id or ""),
            "candidate_id": candidate_id,
            "operation": operation,
            "decision": decision,
            "operator_id": payload.get("operator_id") or "viettel_operator",
            "reason": payload.get("reason"),
            "partition_delta": partition_delta,
            "created_at": now,
        }

        self.operator_feedbacks.append(record)

        if self.repository is not None:
            persisted = await self.repository.persist_operator_feedback(record)
            return persisted

        return record

    async def list_operator_feedback(
        self, job_id: str | None = None, chain_id: str | None = None
    ) -> list[Any]:
        if self.repository is not None:
            if job_id is not None:
                return await self.repository.operator_feedback_for_job(job_id)
            if chain_id is not None:
                return await self.repository.operator_feedback_for_chain(chain_id)

        results = self.operator_feedbacks
        if job_id is not None:
            results = [f for f in results if f.get("job_id") == job_id]
        if chain_id is not None:
            results = [f for f in results if f.get("chain_id") == chain_id]
        return results
