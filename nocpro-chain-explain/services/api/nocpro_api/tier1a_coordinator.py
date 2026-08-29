from __future__ import annotations

import os
import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from evolution import LineageConfig, LineageNodeKey, OutOfOrderLineageError
from libs.contracts import ContractIngestError, load_validated_package
from similar_chains import (
    CorpusPolicy,
    ModelUpdatePolicy,
    TimedChainFingerprint,
    TaxonomyStatus,
    build_fingerprint,
    materialize_similarity_index,
)

from .persistence import SnapshotRepository


class Tier1ACoordinator:
    """Durably claim Tier-1A once, while keeping Tier-1B lazy in Workspace."""

    def __init__(
        self,
        repository: SnapshotRepository,
        workspace,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 120,
        max_attempts: int = 5,
        backoff_base_seconds: int = 2,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.worker_id = worker_id or f"{os.getpid()}-{uuid4().hex}"
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds

    async def run(self, snapshot_id: str, snapshot_version: str):
        """Process logical-oldest jobs until the requested snapshot is READY."""
        target = (snapshot_id, snapshot_version)
        while True:
            completed = await self.run_pending_once()
            if completed is None:
                return None
            identity, precompute = completed
            if identity == target:
                return precompute

    async def run_pending_once(self):
        claim = await self.repository.claim_next_tier1a(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            max_attempts=self.max_attempts,
        )
        if claim is None:
            return None
        try:
            package, precompute = self.workspace.compute_snapshot(claim.payload)
            renewed = await self.repository.heartbeat_tier1a(
                claim.snapshot_id,
                claim.snapshot_version,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if not renewed:
                raise RuntimeError("Tier-1A lease ownership was lost")
            summary: dict[str, Any] = {
                "snapshot_id": precompute.snapshot_id,
                "snapshot_version": claim.snapshot_version,
                "alarm_count": precompute.alarm_count,
                "chain_count": precompute.chain_count,
                "singleton_count": precompute.singleton_count,
                "config_version": precompute.config_version,
            }
            await self.repository.finish_tier1a(
                claim.snapshot_id,
                claim.snapshot_version,
                result=summary,
                worker_id=self.worker_id,
            )
            active_payload = await self.repository.latest_ready_payload()
            if active_payload is not None:
                active_id = (
                    active_payload["snapshot"]["snapshot_id"],
                    active_payload["snapshot"]["snapshot_version"],
                )
                if active_id == (claim.snapshot_id, claim.snapshot_version):
                    self.workspace.activate_snapshot(package, precompute)
                else:
                    active_package, active_precompute = self.workspace.compute_snapshot(
                        active_payload
                    )
                    self.workspace.activate_snapshot(active_package, active_precompute)
            return (claim.snapshot_id, claim.snapshot_version), precompute
        except Exception as exc:
            await self.repository.record_tier1a_failure(
                claim.snapshot_id,
                claim.snapshot_version,
                error=str(exc),
                worker_id=self.worker_id,
                max_attempts=self.max_attempts,
                backoff_base_seconds=self.backoff_base_seconds,
            )
            raise

    async def hydrate_active(self):
        """Serve the latest logical READY immediately after process startup."""
        payload = await self.repository.latest_ready_payload()
        if payload is None:
            return None
        identity = (
            payload["snapshot"]["snapshot_id"],
            payload["snapshot"]["snapshot_version"],
        )
        if self.workspace.active_identity() == identity:
            precompute = self.workspace.precompute
        else:
            package, precompute = self.workspace.compute_snapshot(payload)
            self.workspace.activate_snapshot(package, precompute)
        if self.workspace.similarity_index is None:
            index = await self.repository.load_similarity_index(identity[0])
            if index is not None:
                lineages = await self.repository.canonical_lineages(identity[0])
                self.workspace.attach_similarity(index, lineages)
        return precompute

    async def run_lineage_pending_once(self):
        claim = await self.repository.claim_next_lineage(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return None
        try:
            if (
                claim.previous_payload is not None
                and claim.previous_lineage_status != "READY"
            ):
                await self.repository.mark_lineage_unavailable(
                    claim,
                    "PREVIOUS_LOGICAL_SNAPSHOT_LINEAGE_NOT_READY",
                )
                return claim.snapshot_id, claim.snapshot_version
            current = load_validated_package(claim.payload)
            previous = (
                load_validated_package(claim.previous_payload)
                if claim.previous_payload is not None
                else None
            )
            dag = await self.repository.load_episode_dag()
            dag.apply_snapshot(
                current,
                previous=previous,
                config=LineageConfig(
                    config_version=self.workspace.config.config_version,
                    m_min=int(self.workspace.config.value("lineage.min_intersection")),
                    beta_parent=float(self.workspace.config.value("lineage.beta_parent")),
                    beta_child=float(self.workspace.config.value("lineage.beta_child")),
                    small_chain_jaccard=float(
                        self.workspace.config.value("lineage.small_chain_jaccard")
                    ),
                ),
            )
            await self.repository.finish_lineage(claim, dag)
            return claim.snapshot_id, claim.snapshot_version
        except OutOfOrderLineageError as exc:
            await self.repository.mark_lineage_unavailable(claim, str(exc))
            return claim.snapshot_id, claim.snapshot_version
        except ContractIngestError as exc:
            await self.repository.mark_lineage_unavailable(
                claim, f"LEGACY_CONTRACT_INVALID: {exc}"
            )
            return claim.snapshot_id, claim.snapshot_version
        except Exception as exc:
            await self.repository.release_lineage(claim, str(exc))
            raise

    async def run_similarity_pending_once(self):
        claim = await self.repository.claim_next_similarity(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return None
        try:
            package, precompute = self.workspace.compute_snapshot(claim.payload)
            dag = await self.repository.load_episode_dag()
            cutoff = package.snapshot.snapshot_time
            cutoff_time = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
            if cutoff_time.tzinfo is None:
                cutoff_time = cutoff_time.replace(tzinfo=timezone.utc)
            history = await self.repository.load_similarity_history(
                cutoff=cutoff_time,
                dag=dag,
            )
            lineage_by_chain: dict[str, str] = {}
            current_fingerprints: list[TimedChainFingerprint] = []
            for chain_id in sorted(package.chains):
                canonical = dag.canonical_lineage(
                    LineageNodeKey(package.snapshot.snapshot_id, chain_id)
                )
                if canonical is None:
                    raise RuntimeError("LINEAGE_NOT_READY")
                lineage_by_chain[chain_id] = canonical
                summary = precompute.chains[chain_id]
                fingerprint = build_fingerprint(
                    f"{package.snapshot.snapshot_id}::{chain_id}",
                    package.alarms_of(chain_id),
                    lineage_component_id=canonical,
                    identity_descriptors=summary.descriptors.identity,
                    duration_seconds=package.chains[chain_id].event_span_seconds,
                    top_descriptor_predicates=int(
                        self.workspace.config.value(
                            "similar_chains.top_descriptor_predicates"
                        )
                    ),
                )
                current_fingerprints.append(
                    TimedChainFingerprint(
                        fingerprint,
                        cutoff,
                        package.snapshot.snapshot_id,
                    )
                )
            version_material = (
                f"{package.snapshot.snapshot_id}\0"
                f"{package.snapshot.snapshot_version}\0{cutoff}"
            ).encode("utf-8")
            model_version = (
                f"sim_{hashlib.sha256(version_material).hexdigest()[:24]}"
            )
            index = materialize_similarity_index(
                history,
                model_version=model_version,
                trained_until_exclusive=cutoff,
                corpus_policy=CorpusPolicy.HISTORY_BEFORE_SNAPSHOT,
                model_update_policy=ModelUpdatePolicy.SNAPSHOT_VERSIONED,
                taxonomy_policy="NO_REAL_TAXONOMY_SOURCE",
                taxonomy_status=TaxonomyStatus.UNAVAILABLE,
                taxonomy_reason="ALARM_TAXONOMY_NOT_USED_BY_SOURCE",
                top_descriptor_predicates=int(
                    self.workspace.config.value(
                        "similar_chains.top_descriptor_predicates"
                    )
                ),
            )
            await self.repository.finish_similarity(
                claim, index, current_fingerprints
            )
            if self.workspace.active_identity() == (
                claim.snapshot_id,
                claim.snapshot_version,
            ):
                self.workspace.attach_similarity(index, lineage_by_chain)
            return claim.snapshot_id, claim.snapshot_version
        except Exception as exc:
            await self.repository.release_similarity(claim, str(exc))
            raise
