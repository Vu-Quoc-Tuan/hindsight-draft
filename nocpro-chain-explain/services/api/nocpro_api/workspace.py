"""In-process repository/service boundary used by the HTTP adapter."""

from __future__ import annotations

import os
import asyncio
from concurrent.futures import Future
from pathlib import Path
from threading import RLock
from typing import Any

from channels import evaluate_pair_channels
from configuration import AnalysisConfig, load_analysis_config
from libs.contracts import IngestedPackage, load_validated_package
from tier1a import SnapshotPrecompute, Tier1Cache, precompute_snapshot
from tier1b import analyze_chain_configured
from tier2 import Tier2JobManager
from tier2 import SimilarityQueryContext
from tier2.counterfactual import CounterfactualJobManager


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
        self._persistence_loop = None
        self._review_persistence_futures: list[Future] = []

    def close(self) -> None:
        self.review_jobs.shutdown()
        self.review_jobs.set_state_listener(None)
        self.jobs.shutdown()

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

    def attach_similarity(self, index, lineage_by_chain: dict[str, str]) -> None:
        with self._lock:
            self.similarity_index = index
            self.lineage_by_chain = dict(lineage_by_chain)

    def list_chains(self):
        self.require_package()
        if self.precompute is None:
            raise SnapshotNotLoaded("snapshot precompute unavailable")
        return self.precompute

    def analyze(self, chain_id: str):
        package = self.require_package()
        if self.precompute is None:
            raise SnapshotNotLoaded("snapshot precompute unavailable")
        return analyze_chain_configured(
            package,
            chain_id,
            analysis_config=self.config,
            predicate_index=self.precompute.predicate_index,
        )

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

    def submit_review(self, chain_id: str):
        package = self.require_package()
        tier1b_artifact = self.analyze(chain_id)
        audit_view = self.jobs.latest_succeeded(
            package.snapshot.snapshot_id,
            package.snapshot.snapshot_version,
            chain_id,
        )
        return self.review_jobs.submit(
            package,
            chain_id,
            tier1b_artifact=tier1b_artifact,
            audit_artifact=audit_view.result if audit_view is not None else None,
            analysis_config=self.config,
        )
