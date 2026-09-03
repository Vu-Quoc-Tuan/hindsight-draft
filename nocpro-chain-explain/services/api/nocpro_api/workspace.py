"""In-process repository/service boundary used by the HTTP adapter."""

from __future__ import annotations

import os
import asyncio
from concurrent.futures import Future
from pathlib import Path
from threading import RLock
from typing import Any

from channels import evaluate_pair_channels
from history import HistoricalEvidenceModel, HistoricalTaxonomy
from configuration import AnalysisConfig, load_analysis_config
from libs.contracts import IngestedPackage, load_validated_package
from tier1a import CacheTier, SnapshotPrecompute, Tier1Cache, precompute_snapshot
from tier1b import analyze_chain_configured
from tier2 import (
    AUDIT_ANALYSIS_VERSION,
    SimilarityQueryContext,
    Tier2JobManager,
    chain_membership_fingerprint,
)
from tier2.counterfactual import (
    CounterfactualJobManager,
    artifact_fingerprint,
    review_identity,
)


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config" / "thresholds" / "v1.yaml"


class SnapshotNotLoaded(RuntimeError):
    pass


class Workspace:
    """Owns current snapshot, reusable index/cache and Tier-2 executor."""

    def __init__(self, *, config_path: Path | None = None) -> None:
        selected_config = config_path or Path(
            os.environ.get("ANALYSIS_CONFIG_PATH", str(DEFAULT_CONFIG))
        )
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
        self._persistence_loop = None
        self._review_persistence_futures: list[Future] = []
        self._audit_persistence_futures: list[Future] = []

    def close(self) -> None:
        self.review_jobs.shutdown()
        self.review_jobs.set_state_listener(None)
        self.jobs.set_artifact_listener(None)
        self.jobs.shutdown()

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
            self.historical_model = None
            self.historical_taxonomy = None
            self.historical_unavailable_reason = self.config.historical_evidence_reason

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
        )

    def submit_deep_dive(self, chain_id: str):
        similarity_context = None
        if (
            self.similarity_index is not None
            and chain_id in self.lineage_by_chain
        ):
            similarity_context = SimilarityQueryContext(
                index=self.similarity_index,
                target_lineage_component_id=self.lineage_by_chain[chain_id],
            )
        return self.jobs.submit(
            self.require_package(),
            chain_id,
            analysis_config=self.config,
            similarity_context=similarity_context,
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
            from .persistence import StoredEvolution

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
