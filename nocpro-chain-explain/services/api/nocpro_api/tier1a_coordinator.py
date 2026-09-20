from __future__ import annotations

import logging
import os
import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

LOGGER = logging.getLogger(__name__)

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
from configuration import ChunkRetentionMode
from history import (
    HistoricalEvidenceConfig,
    build_historical_model,
    episodes_from_lineage_prefix,
)
from temporal_delay import DelayEstimator, DelayModelConfig, build_delay_model, lineage_prefix_fingerprint, observations_from_lineage_prefix

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
        chunk_retention_mode: ChunkRetentionMode = ChunkRetentionMode.KEEP,
        topology_repository: Any = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.worker_id = worker_id or f"{os.getpid()}-{uuid4().hex}"
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds
        self.chunk_retention_mode = chunk_retention_mode
        self.topology_repository = topology_repository

    async def _hydrate_payload_topology_if_needed(self, payload: dict[str, Any]) -> None:
        if not self.topology_repository or not isinstance(payload, dict):
            return
        raw_snapshot = payload.get("snapshot")
        if not isinstance(raw_snapshot, dict):
            return
        topo_ref = raw_snapshot.get("topology_ref")
        profile_id = topo_ref.get("profile_id") if isinstance(topo_ref, dict) else getattr(topo_ref, "profile_id", None)
        version = topo_ref.get("topology_version") if isinstance(topo_ref, dict) else getattr(topo_ref, "topology_version", None)
        
        # If topology_ref missing, auto-detect profile from snapshot_id
        if not profile_id:
            snap_id = raw_snapshot.get("snapshot_id", "")
            if "_it_" in snap_id:
                profile_id = "IT_SERVICES"
            elif "_ip_" in snap_id:
                profile_id = "IP_NETWORK"

        if profile_id and not version:
            active_rec = await self.topology_repository.get_active_version(profile_id)
            if active_rec:
                version = active_rec.topology_version
                raw_snapshot["topology_ref"] = {
                    "profile_id": profile_id,
                    "topology_version": version,
                    "source_version": getattr(active_rec, "source_version", ""),
                }

        if not profile_id or not version:
            return

        topology = payload.setdefault("topology", {})
        alarms = payload.get("alarms") or []

        # Ensure canonical_start_time is UTC timezone-qualified
        for a in alarms:
            if isinstance(a, dict):
                cst = a.get("canonical_start_time")
                if cst and isinstance(cst, str) and not cst.endswith("Z") and "+" not in cst:
                    a["canonical_start_time"] = f"{cst}Z"

        # Resolve alarm devices to canonical resource IDs
        existing_mappings: list[dict[str, Any]] = list(topology.get("mappings") or [])
        mapped_alarm_ids = {m.get("alarm_id") for m in existing_mappings if isinstance(m, dict)}
        seed_resources: set[str] = set()

        for a in alarms:
            if not isinstance(a, dict):
                continue
            alarm_id = a.get("alarm_id")
            dev = a.get("device_code") or a.get("device")
            if not alarm_id or not dev:
                continue
            
            if alarm_id not in mapped_alarm_ids:
                res = await self.topology_repository.resolve_identifier(profile_id, str(dev).strip())
                if res and res.get("resource_id"):
                    rid = res["resource_id"]
                    seed_resources.add(rid)
                    existing_mappings.append({
                        "alarm_id": alarm_id,
                        "resource_id": rid,
                        "mapping_status": "VERIFIED_ALIAS",
                        "mapping_method": "VERIFIED_ALIAS_TABLE",
                        "topology_layer": "IT",
                        "source_version": version,
                    })
                    mapped_alarm_ids.add(alarm_id)
                else:
                    seed_resources.add(str(dev).strip().upper())
            else:
                for m in existing_mappings:
                    if isinstance(m, dict) and m.get("alarm_id") == alarm_id and m.get("resource_id"):
                        seed_resources.add(m["resource_id"])

        topology["mappings"] = existing_mappings

        if not topology.get("edges"):
            hydrated = await self.topology_repository.hydrate_graph_for_analysis(
                profile_id,
                version,
                resource_ids=seed_resources or None,
            )
            if hydrated:
                topology["edges"] = hydrated.get("edges", [])
                if not topology.get("nodes"):
                    topology["nodes"] = hydrated.get("nodes", [])
                topology.pop("alias_resolution", None)

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
            if isinstance(claim.payload, dict):
                await self._hydrate_payload_topology_if_needed(claim.payload)
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
                delete_chunks_after_ready=(
                    self.chunk_retention_mode
                    is ChunkRetentionMode.DELETE_AFTER_READY
                ),
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
        """Hydrate a snapshot only when this process has no active selection.

        Recovery runs periodically.  It must not replace a snapshot explicitly
        selected through the catalog merely because another READY snapshot has
        a later logical time in the durable history.
        """
        identity = self.workspace.active_identity()
        if identity is not None:
            precompute = self.workspace.precompute
        else:
            payload = await self.repository.latest_ready_payload()
            if payload is None:
                return None
            identity = (
                payload["snapshot"]["snapshot_id"],
                payload["snapshot"]["snapshot_version"],
            )
            if isinstance(payload, dict):
                await self._hydrate_payload_topology_if_needed(payload)
            package, precompute = self.workspace.compute_snapshot(payload)
            self.workspace.activate_snapshot(package, precompute)
        if self.workspace.similarity_index is None:
            index = await self.repository.load_similarity_index(*identity)
            if index is not None:
                lineages = await self.repository.canonical_lineages(*identity)
                self.workspace.attach_similarity(index, lineages)
        if self.workspace.historical_model is None:
            historical = await self.repository.load_historical_evidence_model(*identity)
            if historical is not None:
                model, taxonomy = historical
                self.workspace.attach_historical_model(model, taxonomy)
        if self.workspace.temporal_delay_model is None:
            temporal = await self.repository.load_temporal_delay_model(*identity)
            if temporal is not None:
                model, taxonomy = temporal
                self.workspace.attach_temporal_delay_model(model, taxonomy)
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
                    LineageNodeKey(
                        package.snapshot.snapshot_id,
                        package.snapshot.snapshot_version,
                        chain_id,
                    )
                )
                if canonical is None:
                    raise RuntimeError("LINEAGE_NOT_READY")
                lineage_by_chain[chain_id] = canonical
                summary = precompute.chains[chain_id]
                fingerprint = build_fingerprint(
                    (
                        f"{package.snapshot.snapshot_id}::"
                        f"{package.snapshot.snapshot_version}::{chain_id}"
                    ),
                    package.alarms_of(chain_id),
                    lineage_component_id=canonical,
                    identity_descriptors=summary.descriptors.identity,
                    duration_seconds=package.chains[chain_id].event_span_seconds,
                    top_descriptor_predicates=int(
                        self.workspace.config.value(
                            "similar_chains.top_descriptor_predicates"
                        )
                    ),
                    # Current source exports do not carry an authoritative
                    # Similar-Chains taxonomy.  Do not reinterpret their raw
                    # fields as one while the persisted model says unavailable.
                    include_taxonomy_terms=False,
                )
                current_fingerprints.append(
                    TimedChainFingerprint(
                        fingerprint,
                        cutoff,
                        package.snapshot.snapshot_id,
                        package.snapshot.snapshot_version,
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
            await self.build_historical_model_for_snapshot(
                package=package,
                dag=dag,
            )
            await self.build_temporal_delay_model_for_snapshot(package=package, dag=dag)
            return claim.snapshot_id, claim.snapshot_version
        except Exception as exc:
            await self.repository.release_similarity(claim, str(exc))
            raise

    async def build_historical_model_for_snapshot(self, *, package, dag) -> bool:
        """Materialize H from the strict lineage prefix when capability exists.

        H is deliberately independent from Similar Chains semantically.  This
        call is merely scheduled after lineage/similarity in the existing
        recovery loop, where the verified DAG is already available.  Missing
        taxonomy or incomplete configuration is a domain capability absence,
        never a fallback to free-text inference.
        """
        policy = self.workspace.config.historical_evidence
        taxonomy = self.workspace.historical_taxonomy_source
        if policy is None or taxonomy is None:
            return False
        existing = await self.repository.load_historical_evidence_model(
            package.snapshot.snapshot_id,
            package.snapshot.snapshot_version,
        )
        if existing is None:
            cutoff = package.snapshot.snapshot_time
            cutoff_time = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
            if cutoff_time.tzinfo is None:
                cutoff_time = cutoff_time.replace(tzinfo=timezone.utc)
            packages = await self.repository.load_historical_packages(cutoff=cutoff_time)
            episodes, prefix_fingerprint = episodes_from_lineage_prefix(
                packages,
                dag=dag,
                cutoff=cutoff,
                taxonomy=taxonomy,
            )
            model = build_historical_model(
                episodes,
                training_cutoff=cutoff,
                lineage_prefix_fingerprint=prefix_fingerprint,
                taxonomy=taxonomy,
                config=HistoricalEvidenceConfig(
                    config_version=self.workspace.config.config_version,
                    min_support=int(policy.min_support.value),
                    lambda_h=float(policy.lambda_h.value),
                    lift_cap=float(policy.lift_cap.value),
                ),
            )
            await self.repository.persist_historical_evidence_model(
                snapshot_id=package.snapshot.snapshot_id,
                snapshot_version=package.snapshot.snapshot_version,
                model=model,
                taxonomy=taxonomy,
            )
        else:
            model, taxonomy = existing
        if self.workspace.active_identity() == (
            package.snapshot.snapshot_id,
            package.snapshot.snapshot_version,
        ):
            self.workspace.attach_historical_model(model, taxonomy)
        return True

    async def build_temporal_delay_model_for_snapshot(self, *, package, dag) -> bool:
        policy = self.workspace.config.temporal_delay
        taxonomy = self.workspace.historical_taxonomy_source
        if policy is None or taxonomy is None:
            return False
        existing = await self.repository.load_temporal_delay_model(package.snapshot.snapshot_id, package.snapshot.snapshot_version)
        if existing is None:
            cutoff = package.snapshot.snapshot_time
            cutoff_time = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
            if cutoff_time.tzinfo is None:
                cutoff_time = cutoff_time.replace(tzinfo=timezone.utc)
            packages = await self.repository.load_historical_packages(cutoff=cutoff_time)
            observations = observations_from_lineage_prefix(packages, dag=dag, cutoff=cutoff, taxonomy=taxonomy)
            model = build_delay_model(
                observations, training_cutoff=cutoff,
                lineage_prefix_fingerprint=lineage_prefix_fingerprint(packages, dag=dag, cutoff=cutoff),
                taxonomy_source_id=taxonomy.source_id, taxonomy_source_version=taxonomy.source_version,
                config=DelayModelConfig(
                    self.workspace.config.config_version,
                    int(policy.min_relation_episodes.value),
                    int(policy.model_selection_min_episodes.value),
                    float(policy.validation_fraction.value),
                    int(policy.model_selection_seed.value),
                    policy.local_mass_halfwidth_candidates_seconds,
                    policy.histogram_bin_width_candidates_seconds,
                    policy.kde_bandwidth_candidates_seconds,
                    DelayEstimator(policy.fallback_model)
                    if policy.fallback_model is not None
                    else None,
                    policy.fallback_local_mass_halfwidth_seconds,
                    policy.fallback_histogram_bin_width_seconds,
                    policy.fallback_kde_bandwidth_seconds,
                ),
            )
            await self.repository.persist_temporal_delay_model(snapshot_id=package.snapshot.snapshot_id, snapshot_version=package.snapshot.snapshot_version, model=model, taxonomy=taxonomy)
        else:
            model, taxonomy = existing
        if self.workspace.active_identity() == (package.snapshot.snapshot_id, package.snapshot.snapshot_version):
            self.workspace.attach_temporal_delay_model(model, taxonomy)
        return True

    async def wake_pending_topology(self, profile_id: str, topology_version: str) -> None:
        """Wake any stalled snapshots waiting for this topology version and process them."""
        LOGGER.info("Waking stalled snapshots waiting for topology %s:%s", profile_id, topology_version)
        try:
            while await self.run_pending_once() is not None:
                pass
            await self.hydrate_active()
        except Exception:
            LOGGER.exception("Error processing snapshots woken by topology %s:%s", profile_id, topology_version)

