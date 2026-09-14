"""Review Learning Service coordinating candidate exposure freezing, feedback, and similarity retrieval."""

import asyncio
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
import uuid

from fastapi import HTTPException, status
from libs.contracts import IngestedPackage
from review_learning.case_fingerprint import (
    extract_candidate_case_blocks,
    compute_case_fingerprint_payload,
)
from review_learning.case_similarity import (
    SimilarCaseMatch,
    find_similar_review_cases,
)
from review_learning.contracts import (
    CandidateDisplayEvent,
    CandidateExposure,
    ManualCorrection,
    ReviewCase,
    ReviewDecision,
    ReviewFeedback,
    ReviewSession,
    TruthTier,
    ReviewSessionNotFound,
    ReviewFeedbackNotFound,
    ReviewDomainForbidden,
    ReviewerRoleForbidden,
    UnknownExposureCandidate,
    ImmutableReviewConflict,
    InactiveFeedbackConflict,
    canonical_fingerprint,
    compute_candidate_fingerprint,
    compute_candidate_set_fingerprint,
    normalize_review_decision,
    validate_manual_correction,
)
from review_learning.features import FEATURE_SCHEMA_VERSION, materialize_candidate_features
from review_learning.temporal_features import summarize_candidate_delay_features
from .persistence.repository import SnapshotRepository
from .review_principal import ReviewerPrincipal, load_reason_policy

logger = logging.getLogger(__name__)


class ReviewLearningService:
    """Manages immutable review sessions, candidate exposures, feedback lifecycle, and case retrieval."""

    def __init__(
        self,
        repository: SnapshotRepository | None = None,
        ranker_artifact_dir: str | Path | None = None,
        enforce_production_governance: bool = True,
        signing_key: str | bytes | None = None,
        abstention_threshold: float | None = None,
    ) -> None:
        self.repository = repository
        self._sessions: dict[str, ReviewSession] = {}
        self._exposures: dict[str, list[CandidateExposure]] = {}
        self._job_to_review_id: dict[str, str] = {}
        self._active_feedbacks: dict[str, ReviewFeedback] = {}
        self._superseded_feedbacks: set[str] = set()
        self._lifecycle_events: list[dict[str, Any]] = []
        self._review_cases: dict[str, ReviewCase] = {}
        self._display_events: list[CandidateDisplayEvent] = []
        self._session_hydration_locks: dict[str, asyncio.Lock] = {}
        self._ranker_model: Any = None
        self._ranker_manifest: Any = None

        app_env = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
        is_production = app_env in {"production", "prod"}
        if is_production and not enforce_production_governance:
            raise RuntimeError(
                f"Production environment detected (APP_ENV={app_env}), but enforce_production_governance=False! "
                "Production requires strict cryptographic governance."
            )

        if ranker_artifact_dir:
            from review_learning import load_production_ranker_artifact, load_ranker_artifact
            if enforce_production_governance:
                self._ranker_model, self._ranker_manifest = load_production_ranker_artifact(
                    ranker_artifact_dir, signing_key=signing_key
                )
            else:
                self._ranker_model, self._ranker_manifest = load_ranker_artifact(ranker_artifact_dir)

        self.abstention_threshold: float = (
            abstention_threshold
            if abstention_threshold is not None
            else getattr(self._ranker_manifest, "abstention_threshold", 0.0)
            if self._ranker_manifest is not None
            else 0.0
        )

    @staticmethod
    def _feedback_truth_tier() -> TruthTier:
        """Current product policy: submitted operator feedback is PO-asserted.

        Identity/domain validation still happens at the route/service boundary;
        this centralizes the deliberately configured default so submit and
        supersede cannot silently diverge.
        """
        return TruthTier.PO_ASSERTED

    def rerank_candidate_exposures(
        self, exposures: list[CandidateExposure]
    ) -> list[CandidateExposure]:
        """Re-rank candidate exposures using the production ranker model if loaded.

        Persists comprehensive ranking audit evidence into each candidate's deterministic_context
        and feature_payload to preserve:
        - ranking_status: RERANKED | ABSTAINED | UNAVAILABLE
        - model_score on each candidate
        - margin: top-1 minus top-2 score margin
        - abstention_threshold
        - abstention_reason
        - ranker_version and artifact_fingerprint
        """
        import dataclasses
        if not exposures:
            return exposures

        # Never let a learned score override deterministic safety eligibility.
        # Keep rejected/dominated records for audit, but exclude them from both
        # prediction and the serving rank space.
        eligible = [
            exp for exp in exposures
            if str(exp.hard_gate_status).upper() == "PASSED"
            and str(exp.deterministic_eligibility).upper() == "HARD_GATES_PASSED"
        ]
        if len(eligible) != len(exposures):
            reranked_eligible = self.rerank_candidate_exposures(eligible) if eligible else []
            by_id = {exp.candidate_id: exp for exp in reranked_eligible}
            result: list[CandidateExposure] = []
            for exp in exposures:
                if exp.candidate_id in by_id:
                    result.append(by_id[exp.candidate_id])
                    continue
                det_ctx = dict(exp.deterministic_context or {})
                feat_payload = dict(exp.feature_payload or {})
                audit_entry = {
                    "ranking_status": "INELIGIBLE_NOT_RERANKED",
                    "model_score": None,
                    "margin": None,
                    "abstention_threshold": float(self.abstention_threshold),
                    "abstention_reason": "DETERMINISTIC_ELIGIBILITY_REQUIRED",
                    "ranker_version": None,
                    "artifact_fingerprint": None,
                }
                det_ctx["ranking_audit"] = audit_entry
                det_ctx["ranking_status"] = audit_entry["ranking_status"]
                feat_payload["ranking_audit"] = audit_entry
                bound_fp = compute_candidate_fingerprint(
                    candidate_id=exp.candidate_id,
                    operation=exp.operation,
                    feature_fingerprint=exp.feature_fingerprint,
                    displayed_rank=exp.displayed_rank,
                    ranking_audit=audit_entry,
                    original_rank=exp.original_rank,
                    delta=det_ctx.get("partition_delta"),
                )
                result.append(dataclasses.replace(exp, candidate_fingerprint=bound_fp, deterministic_context=det_ctx, feature_payload=feat_payload))
            return result

        if self._ranker_model is None:
            unavailable_exposures = []
            for exp in exposures:
                det_ctx = dict(exp.deterministic_context or {})
                feat_payload = dict(exp.feature_payload or {})
                audit_entry = {
                    "ranking_status": "UNAVAILABLE",
                    "model_score": None,
                    "margin": 0.0,
                    "abstention_threshold": float(self.abstention_threshold),
                    "abstention_reason": "MODEL_NOT_LOADED",
                    "ranker_version": None,
                    "artifact_fingerprint": None,
                }
                det_ctx["ranking_audit"] = audit_entry
                det_ctx["ranking_status"] = "UNAVAILABLE"
                det_ctx["margin"] = 0.0
                det_ctx["abstention_threshold"] = float(self.abstention_threshold)
                feat_payload["ranking_audit"] = audit_entry
                bound_fp = compute_candidate_fingerprint(
                    candidate_id=exp.candidate_id,
                    operation=exp.operation,
                    feature_fingerprint=exp.feature_fingerprint,
                    displayed_rank=exp.displayed_rank,
                    ranking_audit=audit_entry,
                    original_rank=exp.original_rank,
                    delta=det_ctx.get("partition_delta"),
                )
                unavailable_exposures.append(dataclasses.replace(
                    exp,
                    candidate_fingerprint=bound_fp,
                    deterministic_context=det_ctx,
                    feature_payload=feat_payload,
                ))
            return unavailable_exposures

        from review_learning.features import FEATURE_NAMES

        feature_matrix: list[list[float]] = []
        for exp in exposures:
            payload = exp.feature_payload or {}
            feat_dict = payload.get("features", payload) if isinstance(payload, dict) else {}
            vec = [float(feat_dict.get(k, 0.0)) if isinstance(feat_dict, dict) else 0.0 for k in FEATURE_NAMES]
            feature_matrix.append(vec)

        scores = list(self._ranker_model.predict(feature_matrix))

        # Abstention check: if confidence margin between top-1 and top-2 is below threshold, abstain
        is_abstained = False
        abstention_reason = None
        margin = 0.0

        if len(scores) >= 2:
            sorted_scores = sorted(scores, reverse=True)
            margin = float(sorted_scores[0] - sorted_scores[1])
            if self.abstention_threshold > 0.0 and margin < self.abstention_threshold:
                is_abstained = True
                abstention_reason = "MARGIN_BELOW_THRESHOLD"
        elif len(scores) == 1:
            margin = float(scores[0])
            if self.abstention_threshold > 0.0 and scores[0] < self.abstention_threshold:
                is_abstained = True
                abstention_reason = "SCORE_BELOW_THRESHOLD"

        model_version = self._ranker_manifest.model_version if self._ranker_manifest else "ranker-v1"
        artifact_fingerprint = getattr(self._ranker_manifest, "artifact_sha256", None) or getattr(self._ranker_manifest, "corpus_fingerprint", None)

        if is_abstained:
            audit_exposures = []
            for idx, exp in enumerate(exposures):
                det_ctx = dict(exp.deterministic_context or {})
                feat_payload = dict(exp.feature_payload or {})
                audit_entry = {
                    "ranking_status": "ABSTAINED",
                    "model_score": float(scores[idx]),
                    "margin": margin,
                    "abstention_threshold": float(self.abstention_threshold),
                    "abstention_reason": abstention_reason,
                    "ranker_version": model_version,
                    "artifact_fingerprint": artifact_fingerprint,
                }
                det_ctx["ranking_audit"] = audit_entry
                det_ctx["ranking_status"] = "ABSTAINED"
                det_ctx["margin"] = margin
                det_ctx["abstention_threshold"] = float(self.abstention_threshold)
                det_ctx["abstention_reason"] = abstention_reason
                feat_payload["ranking_audit"] = audit_entry
                feat_payload["model_score"] = float(scores[idx])
                feat_payload["abstention_reason"] = abstention_reason
                bound_fp = compute_candidate_fingerprint(
                    candidate_id=exp.candidate_id,
                    operation=exp.operation,
                    feature_fingerprint=exp.feature_fingerprint,
                    displayed_rank=exp.displayed_rank,
                    ranking_audit=audit_entry,
                    original_rank=exp.original_rank,
                    delta=det_ctx.get("partition_delta"),
                )
                audit_exposures.append(dataclasses.replace(
                    exp,
                    candidate_fingerprint=bound_fp,
                    deterministic_context=det_ctx,
                    feature_payload=feat_payload,
                ))
            return audit_exposures

        indexed = list(enumerate(exposures))
        indexed.sort(key=lambda item: (-scores[item[0]], item[1].original_rank))

        reranked: list[CandidateExposure] = []
        for new_rank, (old_idx, exp) in enumerate(indexed, 1):
            det_ctx = dict(exp.deterministic_context or {})
            feat_payload = dict(exp.feature_payload or {})
            audit_entry = {
                "ranking_status": "RERANKED",
                "model_score": float(scores[old_idx]),
                "margin": margin,
                "abstention_threshold": float(self.abstention_threshold),
                "abstention_reason": None,
                "ranker_version": model_version,
                "artifact_fingerprint": artifact_fingerprint,
            }
            det_ctx["ranking_audit"] = audit_entry
            det_ctx["ranking_status"] = "RERANKED"
            det_ctx["margin"] = margin
            det_ctx["abstention_threshold"] = float(self.abstention_threshold)
            feat_payload["ranking_audit"] = audit_entry
            feat_payload["model_score"] = float(scores[old_idx])
            bound_fp = compute_candidate_fingerprint(
                candidate_id=exp.candidate_id,
                operation=exp.operation,
                feature_fingerprint=exp.feature_fingerprint,
                displayed_rank=new_rank,
                ranking_audit=audit_entry,
                original_rank=exp.original_rank,
                delta=det_ctx.get("partition_delta"),
            )
            reranked.append(dataclasses.replace(
                exp,
                displayed_rank=new_rank,
                candidate_fingerprint=bound_fp,
                deterministic_context=det_ctx,
                feature_payload=feat_payload,
            ))
        return reranked

    def _get_hydration_lock(self, key: str) -> asyncio.Lock:
        lock = self._session_hydration_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_hydration_locks[key] = lock
        return lock

    async def _ensure_session_hydrated(self, review_id: str) -> ReviewSession | None:
        """Hydrate review session, exposures, and active feedback from repository on cache miss."""
        if review_id in self._sessions and review_id in self._exposures:
            return self._sessions[review_id]
        if self.repository is None:
            return self._sessions.get(review_id)

        async with self._get_hydration_lock(review_id):
            if review_id in self._sessions and review_id in self._exposures:
                return self._sessions[review_id]

            stored_session = await self.repository.get_review_session(review_id)
            if stored_session is None:
                return None

            stored_exposures = await self.repository.get_candidate_exposures(review_id)
            active_fbs = await self.repository.active_review_feedback(review_id=review_id)

            self._sessions[review_id] = stored_session
            self._exposures[review_id] = stored_exposures
            self._job_to_review_id[stored_session.job_id] = review_id
            for fb in active_fbs:
                self._active_feedbacks[fb.feedback_id] = fb

            return stored_session

    async def _ensure_session_by_job_hydrated(self, job_id: str) -> ReviewSession | None:
        """Hydrate session given a job_id."""
        if job_id in self._job_to_review_id:
            review_id = self._job_to_review_id[job_id]
            return await self._ensure_session_hydrated(review_id)
        if self.repository is None:
            review_id = self.get_review_id_for_job(job_id)
            return self._sessions.get(review_id)

        async with self._get_hydration_lock(f"job_{job_id}"):
            if job_id in self._job_to_review_id:
                review_id = self._job_to_review_id[job_id]
                return await self._ensure_session_hydrated(review_id)

            stored_session = await self.repository.get_review_session_by_job_id(job_id)
            if stored_session is None:
                return None

            review_id = stored_session.review_id
            self._job_to_review_id[job_id] = review_id
            return await self._ensure_session_hydrated(review_id)

    def get_review_id_for_job(self, job_id: str) -> str:
        return self._job_to_review_id.get(job_id) or f"rev_{job_id}"

    def prepare_review_bundle(
        self,
        *,
        job_id: str,
        job_view: Any,
        package: IngestedPackage | None,
        delay_model: Any | None = None,
        taxonomy: Any | None = None,
        config_version: str = "v1",
        exposure_policy: str = "ALL_EVALUATED",
        context: Any | None = None,
    ) -> tuple[ReviewSession, list[CandidateExposure]]:
        """Prepare immutable ReviewSession and CandidateExposure list without persisting or mutating cache."""
        review_id = self.get_review_id_for_job(job_id)

        # Extract result dict
        result_dict: dict[str, Any] = {}
        if hasattr(job_view, "result") and job_view.result is not None:
            if isinstance(job_view.result, dict):
                result_dict = job_view.result
            else:
                try:
                    from tier2.counterfactual.public_contract import public_review_result
                    result_dict = public_review_result(job_view.result)
                except Exception:
                    if hasattr(job_view.result, "to_dict"):
                        result_dict = job_view.result.to_dict()
                    elif hasattr(job_view.result, "__dict__"):
                        result_dict = dict(job_view.result.__dict__)
                    else:
                        result_dict = dict(job_view.result)

        identity = getattr(job_view, "identity", {})
        if context is not None:
            snapshot_id = context.snapshot_id
            snapshot_version = context.snapshot_version
            chain_id = context.chain_id
            review_time = context.review_time
            source_kind = context.source_kind
            lineage_component_id = context.lineage_component_id
            generator_ver = context.generator_version
            config_version = context.config_version
            exposure_policy = context.exposure_policy_version
        else:
            if hasattr(identity, "snapshot_id"):
                snapshot_id = identity.snapshot_id
                snapshot_version = identity.snapshot_version
            elif isinstance(identity, dict):
                snapshot_id = identity.get("snapshot_id", "")
                snapshot_version = identity.get("snapshot_version", "1")
            else:
                snapshot_id = result_dict.get("identity", {}).get("snapshot_id", "")
                snapshot_version = result_dict.get("identity", {}).get("snapshot_version", "1")

            chain_id = getattr(job_view, "chain_id", "") or result_dict.get("chain_id", "")
            review_time = datetime.now(timezone.utc)
            source_kind = getattr(job_view, "source_kind", None)
            if not source_kind and package is not None and getattr(package, "snapshot", None):
                source_kind = getattr(package.snapshot, "source_kind", None)
            if source_kind in {"REAL_LIVE", "REAL_EXPORT_REPLAY"}:
                pass
            elif hasattr(source_kind, "value") and source_kind.value in {"REAL_LIVE", "REAL_EXPORT_REPLAY"}:
                source_kind = source_kind.value
            else:
                source_kind = "SOURCE_KIND_UNAVAILABLE"

            lineage_component_id = (
                getattr(job_view, "lineage_component_id", None)
                or (getattr(job_view, "identity", None) and getattr(job_view.identity, "lineage_component_id", None))
                or "LINEAGE_UNAVAILABLE"
            )
            if lineage_component_id.startswith("fallback_lineage:"):
                lineage_component_id = "LINEAGE_UNAVAILABLE"

            generator_ver = getattr(job_view, "generator_version", "v1") if hasattr(job_view, "generator_version") else "v1"

        now = datetime.now(timezone.utc)

        # Collect evaluated candidates (both recommendations and all evaluated)
        candidates_raw: list[dict[str, Any]] = []
        evaluated = result_dict.get("evaluated_candidates", [])
        recommendations = result_dict.get("recommendations", [])

        rec_ids = set()
        for r in recommendations:
            if isinstance(r, dict) and r.get("candidate_id"):
                rec_ids.add(str(r["candidate_id"]))
            elif hasattr(r, "candidate_id"):
                rec_ids.add(str(r.candidate_id))

        seen_cands = set()
        for c in evaluated:
            c_dict = c if isinstance(c, dict) else (asdict(c) if hasattr(c, "__dataclass_fields__") else dict(c.__dict__))
            cid = str(c_dict.get("candidate_id"))
            if cid and cid not in seen_cands:
                candidates_raw.append(c_dict)
                seen_cands.add(cid)

        for r in recommendations:
            r_dict = r if isinstance(r, dict) else (asdict(r) if hasattr(r, "__dataclass_fields__") else dict(r.__dict__))
            cid = str(r_dict.get("candidate_id"))
            if cid and cid not in seen_cands:
                candidates_raw.append(r_dict)
                seen_cands.add(cid)

        # Build candidate exposure list
        exposures: list[CandidateExposure] = []
        candidate_fps: list[str] = []
        alarms_by_id = package.alarms if (package and hasattr(package, "alarms")) else {}
        if package and hasattr(package, "alarms_of"):
            chain_alarms = package.alarms_of(chain_id)
        elif package and hasattr(package, "alarms") and hasattr(package, "members_of"):
            chain_alarms = [package.alarms[aid] for aid in package.members_of(chain_id) if aid in package.alarms]
        else:
            chain_alarms = []

        for rank, cand_dict in enumerate(candidates_raw):
            cid = str(cand_dict.get("candidate_id", f"cand_{rank}"))
            op = str(cand_dict.get("operation", "UNKNOWN"))
            delta = cand_dict.get("partition_delta", {})

            # Deterministic eligibility & hard gate
            public_gate = cand_dict.get("hard_gate_result") or {}
            hard_gate_passed = cand_dict.get(
                "hard_gate_passed",
                str(public_gate.get("status", "PASSED")).upper() == "PASSED",
            )
            recommended = cid in rec_ids or cand_dict.get("recommended", False)
            if not hard_gate_passed:
                eligibility = "HARD_GATE_REJECTED"
                hg_status = "REJECTED"
                pareto = "INELIGIBLE"
            elif recommended:
                eligibility = "HARD_GATES_PASSED"
                hg_status = "PASSED"
                pareto = "FRONTIER_SELECTED"
            else:
                eligibility = "DOMINATED"
                hg_status = "PASSED"
                pareto = "DOMINATED"

            cand_target_chain_id = (
                cand_dict.get("target_chain_id")
                or (cand_dict.get("operation_specific_evidence") and cand_dict.get("operation_specific_evidence", {}).get("target_chain_id"))
                or (cand_dict.get("partition_delta") and cand_dict.get("partition_delta", {}).get("target_chain_id"))
            )
            target_alarm_ids: list[str] = []
            if cand_target_chain_id and package:
                if hasattr(package, "alarms_of"):
                    target_alarm_ids = [str(a.alarm_id) for a in package.alarms_of(cand_target_chain_id)]
                elif hasattr(package, "members_of"):
                    target_alarm_ids = [str(aid) for aid in package.members_of(cand_target_chain_id)]

            # Temporal delay features with changed-pair evaluation
            temporal_shape = summarize_candidate_delay_features(
                candidate=cand_dict,
                chain_alarm_ids=[a.alarm_id for a in chain_alarms],
                alarms_by_id=alarms_by_id,
                delay_model=delay_model,
                taxonomy=taxonomy,
                target_chain_alarm_ids=target_alarm_ids,
            )

            det_context = {
                "raw_score": cand_dict.get("raw_score", 0.0),
                "benefit": cand_dict.get("benefit", 0.0),
                "hard_gate_failures": cand_dict.get("hard_gate_failures", []),
                "partition_delta": delta,
                "metric_deltas": cand_dict.get("metric_deltas", {}),
                "before_metrics": cand_dict.get("before_metrics", {}),
                "after_metrics": cand_dict.get("after_metrics", {}),
                "edit_cost": cand_dict.get("edit_cost", {}),
                "frozen_universe": {
                    "source_chain_id": str(chain_id),
                    "source_alarm_ids": [str(a.alarm_id) for a in chain_alarms],
                    "target_chain_id": str(cand_target_chain_id) if cand_target_chain_id else None,
                    "target_alarm_ids": target_alarm_ids,
                    "snapshot_id": str(snapshot_id),
                    "snapshot_version": str(snapshot_version),
                },
            }
            case_context = {
                "chain_id": chain_id,
                "chain_alarm_count": len(chain_alarms),
            }

            metrics_avail = bool(
                package is not None
                and (det_context.get("metric_deltas") or det_context.get("before_metrics"))
            )
            topo_avail = bool(
                package is not None
                and det_context.get("topology_dep_hop_available")
            )

            flat_features = materialize_candidate_features(
                operation=op,
                deterministic_context=det_context,
                temporal_context=temporal_shape,
                case_context=case_context,
                hard_gate_status=hg_status,
                pareto_state=pareto,
                source_kind=source_kind,
            )

            feature_payload = {
                "schema_version": FEATURE_SCHEMA_VERSION,
                "candidate_id": cid,
                "operation": op,
                "features": flat_features,
                "exact_metrics": {
                    "raw_score": cand_dict.get("raw_score", 0.0),
                    "benefit": cand_dict.get("benefit", 0.0),
                    "hard_gate_passed": hard_gate_passed,
                    "pareto_state": pareto,
                    "delta": delta,
                    "metric_deltas": cand_dict.get("metric_deltas", {}),
                    "before_metrics": cand_dict.get("before_metrics", {}),
                    "after_metrics": cand_dict.get("after_metrics", {}),
                    "edit_cost": cand_dict.get("edit_cost", {}),
                },
                "temporal_features": temporal_shape,
                "availability_flags": {
                    "temporal_available": temporal_shape.get("status") == "AVAILABLE",
                    "metrics_available": metrics_avail,
                    "topology_available": topo_avail,
                },
                "version_provenance": {
                    "generator_version": generator_ver,
                    "config_version": config_version,
                    "delay_model_version": getattr(delay_model, "model_version", None),
                },
            }
            feature_fp = canonical_fingerprint(flat_features)
            cand_fp = canonical_fingerprint({"candidate_id": cid, "operation": op, "delta": delta, "feature_fp": feature_fp})
            candidate_fps.append(cand_fp)

            exp = CandidateExposure(
                review_id=review_id,
                candidate_id=cid,
                candidate_fingerprint=cand_fp,
                operation=op,
                original_rank=rank,
                displayed_rank=rank + 1,
                deterministic_eligibility=eligibility,
                hard_gate_status=hg_status,
                pareto_state=pareto,
                deterministic_context=det_context,
                case_context=case_context,
                temporal_context=temporal_shape,
                feature_fingerprint=feature_fp,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                feature_payload=feature_payload,
                created_at=now,
            )
            exposures.append(exp)

        # Determine server-grounded review_domain
        review_domain = "UNKNOWN_DOMAIN"
        if context is not None and getattr(context, "review_domain", None):
            review_domain = str(context.review_domain)
        elif hasattr(job_view, "review_domain") and getattr(job_view, "review_domain", None):
            review_domain = str(getattr(job_view, "review_domain"))
        elif package is not None:
            if getattr(package, "topology", None) and isinstance(package.topology, dict) and package.topology.get("domain"):
                review_domain = str(package.topology["domain"])
            elif getattr(package, "system_metadata", None) and isinstance(package.system_metadata, dict) and package.system_metadata.get("domain"):
                review_domain = str(package.system_metadata["domain"])
            elif chain_alarms:
                first_alarm = chain_alarms[0]
                if hasattr(first_alarm, "raw") and isinstance(first_alarm.raw, dict):
                    review_domain = str(first_alarm.raw.get("failure_domain") or first_alarm.raw.get("domain") or "UNKNOWN_DOMAIN")

        snapshot_observed_at = None
        if context is not None and getattr(context, "snapshot_observed_at", None):
            snapshot_observed_at = context.snapshot_observed_at
        elif package is not None and getattr(package, "snapshot", None) and getattr(package.snapshot, "observed_at", None):
            snapshot_observed_at = package.snapshot.observed_at

        job_completed_at = (context.job_completed_at if (context is not None and getattr(context, "job_completed_at", None)) else None) or getattr(job_view, "completed_at", None) or now

        ranker_version = None
        exposures = self.rerank_candidate_exposures(exposures)
        if self._ranker_model is not None:
            audit = exposures[0].deterministic_context.get("ranking_audit", {}) if exposures else {}
            status = audit.get("ranking_status", "UNAVAILABLE")
            model_ver = self._ranker_manifest.model_version if self._ranker_manifest else "ranker-v1"
            if status == "RERANKED":
                ranker_version = model_ver
            elif status == "ABSTAINED":
                ranker_version = f"{model_ver}:ABSTAINED"
            else:
                ranker_version = None

        cand_set_fp = compute_candidate_set_fingerprint(
            candidate_fingerprints=[exp.candidate_fingerprint for exp in exposures],
            generator_version=generator_ver,
            config_version=config_version,
            exposure_policy=exposure_policy,
        )

        session = ReviewSession(
            review_id=review_id,
            job_id=job_id,
            snapshot_id=str(snapshot_id),
            snapshot_version=str(snapshot_version),
            chain_id=str(chain_id),
            review_time=review_time,
            source_kind=source_kind,
            lineage_component_id=lineage_component_id,
            candidate_set_fingerprint=cand_set_fp,
            generator_version=generator_ver,
            config_version=config_version,
            delay_model_version=getattr(delay_model, "model_version", None),
            retrieval_version="cf-case-v1",
            ranker_version=ranker_version,
            exposure_policy=exposure_policy,
            created_at=now,
            review_domain=review_domain,
            snapshot_observed_at=snapshot_observed_at,
            job_completed_at=job_completed_at,
        )

        return session, exposures

    def register_persisted_bundle(
        self, session: ReviewSession, exposures: Sequence[CandidateExposure]
    ) -> None:
        """Register a committed review bundle into in-memory caches."""
        self._sessions[session.review_id] = session
        self._exposures[session.review_id] = list(exposures)
        self._job_to_review_id[session.job_id] = session.review_id

    async def freeze_review_bundle(
        self,
        *,
        job_id: str,
        job_view: Any,
        package: IngestedPackage | None,
        delay_model: Any | None = None,
        taxonomy: Any | None = None,
        config_version: str = "v1",
        exposure_policy: str = "ALL_EVALUATED",
        context: Any | None = None,
    ) -> ReviewSession:
        """Freeze and persist all evaluated candidates into an immutable bundle."""
        session, exposures = self.prepare_review_bundle(
            job_id=job_id,
            job_view=job_view,
            package=package,
            delay_model=delay_model,
            taxonomy=taxonomy,
            config_version=config_version,
            exposure_policy=exposure_policy,
            context=context,
        )
        review_id = session.review_id

        # Replay idempotency & conflict detection in memory
        if review_id in self._sessions:
            existing_session = self._sessions[review_id]
            if (
                existing_session.candidate_set_fingerprint == session.candidate_set_fingerprint
                and existing_session.chain_id == session.chain_id
                and existing_session.snapshot_id == session.snapshot_id
                and existing_session.snapshot_version == session.snapshot_version
            ):
                return existing_session
            raise ImmutableReviewConflict(
                f"Conflict: review session {review_id} already exists with differing candidate set fingerprint"
            )

        if self.repository is not None:
            await self.repository.persist_review_bundle(session, exposures)

        self.register_persisted_bundle(session, exposures)
        return session

    def _resolve_and_validate_manual_target(
        self,
        *,
        feedback_id: str,
        session: ReviewSession,
        target_exp: CandidateExposure | None,
        mc_sub: Mapping[str, Any],
        chain_alarms: list[Any] | None,
        allowed_reasons: Sequence[str] | None,
        reason_code_single: str | None,
        all_codes: list[str],
        decision: ReviewDecision,
        now: datetime,
        package: Any | None = None,
    ) -> ManualCorrection:
        mc_delta = mc_sub.get("partition_delta", {})
        op = mc_sub.get("operation", "MANUAL_SPLIT")

        frozen_source_chain_id = session.chain_id
        client_target_chain_id = mc_sub.get("target_chain_id")

        fu = (target_exp.deterministic_context.get("frozen_universe") or {}) if target_exp else {}
        frozen_source_alarms = fu.get("source_alarm_ids")
        fu_target_chain_id = fu.get("target_chain_id")
        frozen_target_alarms = fu.get("target_alarm_ids")

        if not frozen_source_alarms and chain_alarms:
            frozen_source_alarms = [a.alarm_id for a in chain_alarms]

        if not frozen_source_alarms:
            for exp in self._exposures.get(session.review_id, []):
                s_alarms = (exp.deterministic_context.get("frozen_universe") or {}).get("source_alarm_ids")
                if s_alarms:
                    frozen_source_alarms = s_alarms
                    break

        if not frozen_source_alarms:
            raise ValueError("Cannot validate manual correction: frozen alarm universe for review session is missing or empty")

        if op in {"MANUAL_SPLIT", "MANUAL_REMOVE"}:
            if client_target_chain_id:
                raise ValueError(f"{op} must not specify target_chain_id")
            resolved_target_chain_id = None
            resolved_target_alarms = None
        else:
            if not fu_target_chain_id and client_target_chain_id and package:
                fu_target_chain_id = client_target_chain_id
                if hasattr(package, "members_of"):
                    frozen_target_alarms = [str(aid) for aid in package.members_of(client_target_chain_id)]
            if not fu_target_chain_id or not frozen_target_alarms:
                raise ValueError(f"Target chain {client_target_chain_id or 'unknown'} does not have valid frozen alarms for {op}")
            if client_target_chain_id and client_target_chain_id != fu_target_chain_id:
                raise ImmutableReviewConflict(
                    f"Submitted target_chain_id {client_target_chain_id!r} conflicts with frozen target_chain_id {fu_target_chain_id!r}"
                )
            resolved_target_chain_id = fu_target_chain_id
            resolved_target_alarms = frozen_target_alarms

        validate_manual_correction(
            operation=op,
            partition_delta=mc_delta,
            server_chain_alarms=frozen_source_alarms,
            server_target_chain_alarms=resolved_target_alarms,
            allowed_reason_codes=allowed_reasons,
            submitted_reason_code=reason_code_single,
            submitted_reason_codes=all_codes,
            decision=decision,
            source_chain_id=frozen_source_chain_id,
            target_chain_id=resolved_target_chain_id,
        )
        mc_fp = canonical_fingerprint(mc_delta)
        return ManualCorrection(
            correction_id=f"mc_{uuid.uuid4().hex[:12]}",
            feedback_id=feedback_id,
            operation=op,
            partition_delta=mc_delta,
            correction_fingerprint=mc_fp,
            created_at=now,
        )

    async def record_feedback(
        self,
        *,
        job_id: str,
        submission: Mapping[str, Any],
        principal: ReviewerPrincipal,
        package: IngestedPackage | None = None,
    ) -> ReviewFeedback:
        """Submit append-only review feedback with server-derived reviewer identity."""
        session = await self._ensure_session_by_job_hydrated(job_id)
        review_id = self.get_review_id_for_job(job_id)
        if session is None and review_id in self._sessions:
            session = self._sessions[review_id]
        if session is None:
            raise ReviewSessionNotFound(f"Review session for job {job_id!r} not found")
        review_id = session.review_id

        # Verify reviewer domain authorization fail-closed
        principal.verify_domain_authorization(session.review_domain)

        decision = normalize_review_decision(submission["decision"])
        candidate_id = submission.get("candidate_id")

        if decision in (ReviewDecision.NONE_ACCEPTABLE, ReviewDecision.MANUAL_CORRECTION) and not candidate_id:
            candidate_id = None
        elif not candidate_id:
            raise ValueError(f"candidate_id is required for decision {decision.value}")

        exposures = self._exposures.get(review_id, [])
        target_exp: CandidateExposure | None = None

        if candidate_id is not None:
            for exp in exposures:
                if exp.candidate_id == candidate_id:
                    target_exp = exp
                    break
            if target_exp is None and exposures:
                raise ValueError(
                    f"candidate_id {candidate_id!r} is not an evaluated candidate or "
                    f"operator-facing recommendation for review job {job_id!r}"
                )

        # Enforce bidirectional manual_correction constraint
        mc_sub = submission.get("manual_correction")
        if decision == ReviewDecision.MANUAL_CORRECTION and not mc_sub:
            raise ValueError("manual_correction payload is required when decision is MANUAL_CORRECTION")
        if decision != ReviewDecision.MANUAL_CORRECTION and mc_sub:
            raise ValueError(f"manual_correction payload is only valid for decision MANUAL_CORRECTION, got {decision.value}")

        # Enforce server reason policy across all reason codes, reject conflicting inputs, pin policy version
        reason_policy = load_reason_policy()
        reason_policy_ver = reason_policy.get("policy_version", "review-reasons-v1")

        reason_code_single = submission.get("reason_code")
        reason_codes_list = submission.get("reason_codes")
        if reason_code_single and reason_codes_list and reason_code_single not in reason_codes_list:
            raise ValueError("Conflicting reason_code and reason_codes submitted")

        all_codes: list[str] = []
        if reason_codes_list:
            all_codes.extend([str(c) for c in reason_codes_list if c])
        elif reason_code_single:
            all_codes.append(str(reason_code_single))

        allowed_reasons = {
            r["code"] for r in reason_policy.get("reasons_by_decision", {}).get(decision.value, [])
        }
        for code in all_codes:
            if code not in allowed_reasons:
                raise ValueError(
                    f"Reason code {code!r} is not in the active server policy for decision {decision.value}: {sorted(allowed_reasons)}"
                )

        if decision == ReviewDecision.MANUAL_CORRECTION and len(all_codes) < 1:
            raise ValueError("Decision MANUAL_CORRECTION requires at least one reason code from active policy")

        reason_codes = tuple(all_codes)
        reason_text = submission.get("notes") or submission.get("reason")

        now = datetime.now(timezone.utc)
        feedback_id = f"fb_{uuid.uuid4().hex[:12]}"

        confidence = submission.get("confidence", 1.0)
        if confidence is not None:
            confidence = float(confidence)

        chain_id = session.chain_id
        chain_alarms = []
        if package:
            if hasattr(package, "alarms_of"):
                chain_alarms = package.alarms_of(chain_id)
            elif hasattr(package, "alarms") and hasattr(package, "members_of"):
                chain_alarms = [package.alarms[aid] for aid in package.members_of(chain_id) if aid in package.alarms]

        # Server-grounded manual correction validation against candidate frozen universe
        manual_correction: ManualCorrection | None = None
        if mc_sub:
            manual_correction = self._resolve_and_validate_manual_target(
                feedback_id=feedback_id,
                session=session,
                target_exp=target_exp,
                mc_sub=mc_sub,
                chain_alarms=chain_alarms,
                allowed_reasons=allowed_reasons,
                reason_code_single=reason_code_single,
                all_codes=all_codes,
                decision=decision,
                now=now,
                package=package,
            )

        resolved_truth_tier = self._feedback_truth_tier()

        feedback = ReviewFeedback(
            feedback_id=feedback_id,
            review_id=review_id,
            candidate_id=candidate_id,
            reviewer_subject=principal.subject,
            reviewer_role=principal.role,
            domain_scope=principal.domain_scope,
            reviewer_domain_scope=principal.domain_scope,
            decision=decision,
            confidence=confidence,
            reason_policy_version=reason_policy_ver,
            reason_codes=reason_codes,
            reason_text=reason_text,
            truth_tier=resolved_truth_tier,
            manual_correction=manual_correction,
            created_at=now,
        )

        # Formulate Review Case for retrieval
        cand_payload = {
            "operation": target_exp.operation if target_exp else (decision.value),
            "partition_delta": target_exp.deterministic_context.get("partition_delta", {}) if target_exp else {},
        }
        persisted_blocks = (
            (target_exp.case_context or {}).get("case_blocks")
            if target_exp is not None
            else None
        )
        if isinstance(persisted_blocks, dict):
            # A frozen exposure may carry the exact server-materialized case
            # blocks.  Reusing those blocks preserves fidelity after restart;
            # legacy exposures continue through the deterministic fallback.
            case_blocks = persisted_blocks
        else:
            case_blocks = extract_candidate_case_blocks(
                candidate=cand_payload,
                chain_id=chain_id,
                chain_alarms=chain_alarms,
                temporal_shape=target_exp.temporal_context if target_exp else None,
            )
        payload, master_hash = compute_case_fingerprint_payload(case_blocks)

        lineage_id = session.lineage_component_id

        review_case = ReviewCase(
            case_id=f"case_{uuid.uuid4().hex[:12]}",
            review_id=review_id,
            feedback_id=feedback_id,
            candidate_id=candidate_id,
            case_time=now,
            lineage_component_id=lineage_id,
            operation_pattern=target_exp.operation if target_exp else decision.value,
            fingerprint_schema_version="cf-case-v1",
            fingerprint_payload=payload,
            fingerprint_hash=master_hash,
            case_domain=session.review_domain,
            decision=decision,
            truth_tier=resolved_truth_tier,
            status="ACTIVE",
            created_at=now,
        )

        if self.repository is not None:
            await self.repository.append_review_feedback(
                feedback, manual_correction=manual_correction, review_case=review_case
            )

        # Mutate in-memory cache ONLY AFTER database commit succeeds
        self._active_feedbacks[feedback_id] = feedback
        self._review_cases[review_case.case_id] = review_case

        return feedback

    async def supersede_feedback(
        self,
        *,
        job_id: str,
        supersedes_feedback_id: str,
        submission: Mapping[str, Any],
        principal: ReviewerPrincipal,
        package: IngestedPackage | None = None,
    ) -> ReviewFeedback:
        """Supersede a previous feedback record with a new immutable feedback record."""
        session = await self._ensure_session_by_job_hydrated(job_id)
        review_id = self.get_review_id_for_job(job_id)
        if session is None and review_id in self._sessions:
            session = self._sessions[review_id]
        if session is None:
            raise ReviewSessionNotFound(f"Review session for job {job_id!r} not found")
        review_id = session.review_id

        # Verify reviewer domain authorization fail-closed
        principal.verify_domain_authorization(session.review_domain)

        decision = normalize_review_decision(submission["decision"])
        candidate_id = submission.get("candidate_id")

        if decision in (ReviewDecision.NONE_ACCEPTABLE, ReviewDecision.MANUAL_CORRECTION) and not candidate_id:
            candidate_id = None
        elif not candidate_id:
            raise ValueError(f"candidate_id is required for decision {decision.value}")

        exposures = self._exposures.get(review_id, [])
        target_exp: CandidateExposure | None = None
        if candidate_id is not None:
            for exp in exposures:
                if exp.candidate_id == candidate_id:
                    target_exp = exp
                    break
            if target_exp is None and exposures:
                raise ValueError(
                    f"candidate_id {candidate_id!r} is not an evaluated candidate or "
                    f"operator-facing recommendation for review job {job_id!r}"
                )

        # Precondition checks for supersedes_feedback_id when no repository
        if self.repository is None and supersedes_feedback_id not in self._active_feedbacks:
            raise InactiveFeedbackConflict(f"Previous feedback {supersedes_feedback_id} does not exist or is not active")

        # Enforce bidirectional manual_correction constraint
        mc_sub = submission.get("manual_correction")
        if decision == ReviewDecision.MANUAL_CORRECTION and not mc_sub:
            raise ValueError("manual_correction payload is required when decision is MANUAL_CORRECTION")
        if decision != ReviewDecision.MANUAL_CORRECTION and mc_sub:
            raise ValueError(f"manual_correction payload is only valid for decision MANUAL_CORRECTION, got {decision.value}")

        # Enforce server reason policy across all reason codes, reject conflicting inputs, pin policy version
        reason_policy = load_reason_policy()
        reason_policy_ver = reason_policy.get("policy_version", "review-reasons-v1")

        reason_code_single = submission.get("reason_code")
        reason_codes_list = submission.get("reason_codes")
        if reason_code_single and reason_codes_list and reason_code_single not in reason_codes_list:
            raise ValueError("Conflicting reason_code and reason_codes submitted")

        all_codes: list[str] = []
        if reason_codes_list:
            all_codes.extend([str(c) for c in reason_codes_list if c])
        elif reason_code_single:
            all_codes.append(str(reason_code_single))

        allowed_reasons = {
            r["code"] for r in reason_policy.get("reasons_by_decision", {}).get(decision.value, [])
        }
        for code in all_codes:
            if code not in allowed_reasons:
                raise ValueError(
                    f"Reason code {code!r} is not in the active server policy for decision {decision.value}: {sorted(allowed_reasons)}"
                )

        if decision == ReviewDecision.MANUAL_CORRECTION and len(all_codes) < 1:
            raise ValueError("Decision MANUAL_CORRECTION requires at least one reason code from active policy")

        reason_codes = tuple(all_codes)
        reason_text = submission.get("notes") or submission.get("reason")

        now = datetime.now(timezone.utc)
        feedback_id = f"fb_{uuid.uuid4().hex[:12]}"

        confidence = submission.get("confidence", 1.0)
        if confidence is not None:
            confidence = float(confidence)

        chain_id = session.chain_id
        chain_alarms = []
        if package:
            if hasattr(package, "alarms_of"):
                chain_alarms = package.alarms_of(chain_id)
            elif hasattr(package, "alarms") and hasattr(package, "members_of"):
                chain_alarms = [package.alarms[aid] for aid in package.members_of(chain_id) if aid in package.alarms]

        manual_correction: ManualCorrection | None = None
        if mc_sub:
            manual_correction = self._resolve_and_validate_manual_target(
                feedback_id=feedback_id,
                session=session,
                target_exp=target_exp,
                mc_sub=mc_sub,
                chain_alarms=chain_alarms,
                allowed_reasons=allowed_reasons,
                reason_code_single=reason_code_single,
                all_codes=all_codes,
                decision=decision,
                now=now,
                package=package,
            )

        resolved_truth_tier = self._feedback_truth_tier()

        new_feedback = ReviewFeedback(
            feedback_id=feedback_id,
            review_id=review_id,
            candidate_id=candidate_id,
            reviewer_subject=principal.subject,
            reviewer_role=principal.role,
            domain_scope=principal.domain_scope,
            reviewer_domain_scope=principal.domain_scope,
            decision=decision,
            confidence=confidence,
            reason_policy_version=reason_policy_ver,
            reason_codes=reason_codes,
            reason_text=reason_text,
            truth_tier=resolved_truth_tier,
            supersedes_feedback_id=supersedes_feedback_id,
            manual_correction=manual_correction,
            created_at=now,
        )

        cand_payload = {
            "operation": target_exp.operation if target_exp else (decision.value),
            "partition_delta": target_exp.deterministic_context.get("partition_delta", {}) if target_exp else {},
        }
        persisted_blocks = (
            (target_exp.case_context or {}).get("case_blocks")
            if target_exp is not None
            else None
        )
        case_blocks = persisted_blocks if isinstance(persisted_blocks, dict) else extract_candidate_case_blocks(
            candidate=cand_payload,
            chain_id=chain_id,
            chain_alarms=chain_alarms,
            temporal_shape=target_exp.temporal_context if target_exp else None,
        )
        payload, master_hash = compute_case_fingerprint_payload(case_blocks)

        lineage_id = session.lineage_component_id

        review_case = ReviewCase(
            case_id=f"case_{uuid.uuid4().hex[:12]}",
            review_id=review_id,
            feedback_id=feedback_id,
            candidate_id=candidate_id,
            case_time=now,
            lineage_component_id=lineage_id,
            operation_pattern=target_exp.operation if target_exp else decision.value,
            fingerprint_schema_version="cf-case-v1",
            fingerprint_payload=payload,
            fingerprint_hash=master_hash,
            case_domain=session.review_domain,
            decision=decision,
            truth_tier=resolved_truth_tier,
            status="ACTIVE",
            created_at=now,
        )

        if self.repository is not None:
            await self.repository.append_superseding_feedback(
                new_feedback,
                supersedes_feedback_id=supersedes_feedback_id,
                manual_correction=manual_correction,
                review_case=review_case,
            )

        # Mutate in-memory cache ONLY AFTER database commit succeeds
        self._active_feedbacks[feedback_id] = new_feedback
        self._superseded_feedbacks.add(supersedes_feedback_id)
        if supersedes_feedback_id in self._active_feedbacks:
            del self._active_feedbacks[supersedes_feedback_id]
        self._review_cases[review_case.case_id] = review_case

        return new_feedback

    async def retract_feedback(
        self,
        *,
        job_id: str,
        feedback_id: str,
        principal: ReviewerPrincipal,
        reason: str | None = None,
    ) -> None:
        """Retract feedback and mark related review cases inactive."""
        session = await self._ensure_session_by_job_hydrated(job_id)
        if session is None and self.repository is None and job_id not in self._job_to_review_id:
            raise ReviewSessionNotFound(f"Review session for job {job_id!r} not found")
        if session is None:
            raise ReviewSessionNotFound(f"Review session for job {job_id!r} not found")

        # Verify reviewer domain authorization fail-closed
        principal.verify_domain_authorization(session.review_domain)

        if self.repository is not None:
            await self.repository.append_retraction_event(
                feedback_id=feedback_id,
                actor_subject=principal.subject,
                reason=reason,
                expected_review_id=session.review_id,
            )
        else:
            fb = self._active_feedbacks.get(feedback_id)
            if fb is None or fb.review_id != session.review_id:
                raise ReviewFeedbackNotFound(f"Feedback {feedback_id} not found for review {session.review_id}")

        # Mutate in-memory cache ONLY AFTER database commit succeeds
        if feedback_id in self._active_feedbacks:
            del self._active_feedbacks[feedback_id]

        for cid, rc in list(self._review_cases.items()):
            if rc.feedback_id == feedback_id:
                del self._review_cases[cid]

    async def record_display_events(
        self,
        *,
        job_id: str,
        events_payload: Sequence[Mapping[str, Any]],
        principal: ReviewerPrincipal | None = None,
    ) -> int:
        """Record candidate display events to guard against position bias."""
        session = await self._ensure_session_by_job_hydrated(job_id)
        if session is None:
            raise ReviewSessionNotFound(f"Review session for job {job_id!r} not found")

        # Verify reviewer domain authorization fail-closed if principal provided
        if principal is not None:
            principal.verify_domain_authorization(session.review_domain)

        review_id = session.review_id
        exposures = self._exposures.get(review_id, [])
        if not exposures:
            raise ReviewSessionNotFound(f"No candidate exposures found for review session {review_id}")

        valid_cids = {exp.candidate_id for exp in exposures}
        if len(events_payload) > 50:
            raise ValueError("Batch size exceeds maximum of 50 display events")

        now = datetime.now(timezone.utc)
        events: list[CandidateDisplayEvent] = []
        seen_surface_ranks: set[tuple[str, int]] = set()

        for ev in events_payload:
            cid = str(ev.get("candidate_id"))
            if cid not in valid_cids:
                raise UnknownExposureCandidate(f"candidate_id {cid!r} is not an evaluated exposure for review {review_id}")

            displayed_rank = int(ev.get("displayed_rank", 0))
            if displayed_rank < 1 or displayed_rank > len(exposures):
                raise ValueError(
                    f"displayed_rank must be 1-based and <= candidate count ({len(exposures)}), got {displayed_rank}"
                )

            surface = str(ev.get("surface", "VALIDATION_TOP_CARD"))
            if (surface, displayed_rank) in seen_surface_ranks:
                raise ValueError(f"Duplicate displayed_rank {displayed_rank} for surface {surface}")
            seen_surface_ranks.add((surface, displayed_rank))

            rendered_at = ev.get("rendered_at")
            if isinstance(rendered_at, str):
                try:
                    dt = datetime.fromisoformat(rendered_at.replace("Z", "+00:00"))
                except ValueError:
                    dt = now
            elif isinstance(rendered_at, datetime):
                dt = rendered_at
            else:
                dt = now

            event = CandidateDisplayEvent(
                display_event_id=f"disp_{uuid.uuid4().hex[:12]}",
                review_id=review_id,
                candidate_id=cid,
                displayed_rank=displayed_rank,
                exposure_policy=str(ev.get("exposure_policy", "ALL_EVALUATED")),
                surface=surface,
                rendered_at=dt,
                viewer_session_id=ev.get("viewer_session_id"),
                client_event_id=ev.get("client_event_id"),
                created_at=now,
            )
            events.append(event)

        if self.repository is not None:
            await self.repository.append_candidate_display_events(events)

        self._display_events.extend(events)
        return len(events)

    async def find_similar_cases_for_candidate(
        self,
        *,
        job_id: str,
        candidate_id: str,
        principal: ReviewerPrincipal,
        top_k: int = 5,
        min_common_blocks: int = 3,
        min_similarity: float = 0.65,
        package: IngestedPackage | None = None,
    ) -> Any:
        """Find historical similar review cases for a candidate."""
        session = await self._ensure_session_by_job_hydrated(job_id)
        review_id = self.get_review_id_for_job(job_id)
        if session is None and review_id in self._sessions:
            session = self._sessions[review_id]
        if session is None:
            raise ReviewSessionNotFound(f"Review session for job {job_id!r} not found")

        # Authorize domain fail-closed
        principal.verify_domain_authorization(session.review_domain)
        review_domain = session.review_domain

        exposures = self._exposures.get(review_id, [])
        target_exp: CandidateExposure | None = None
        for exp in exposures:
            if exp.candidate_id == candidate_id:
                target_exp = exp
                break

        chain_alarms = []
        chain_id = session.chain_id if session else ""
        if package:
            if hasattr(package, "alarms_of"):
                chain_alarms = package.alarms_of(chain_id)
            elif hasattr(package, "alarms") and hasattr(package, "members_of"):
                chain_alarms = [package.alarms[aid] for aid in package.members_of(chain_id) if aid in package.alarms]

        cand_payload = {
            "operation": target_exp.operation if target_exp else "UNKNOWN",
            "partition_delta": target_exp.deterministic_context.get("partition_delta", {}) if target_exp else {},
        }
        persisted_blocks = (
            (target_exp.case_context or {}).get("case_blocks")
            if target_exp is not None
            else None
        )
        case_blocks = persisted_blocks if isinstance(persisted_blocks, dict) else extract_candidate_case_blocks(
            candidate=cand_payload,
            chain_id=chain_id,
            chain_alarms=chain_alarms,
            temporal_shape=target_exp.temporal_context if target_exp else None,
        )

        cutoff_time = getattr(session, "review_time", None) or datetime.now(timezone.utc)
        if isinstance(cutoff_time, str):
            try:
                cutoff_time = datetime.fromisoformat(cutoff_time.replace("Z", "+00:00"))
            except Exception:
                cutoff_time = datetime.now(timezone.utc)

        lineage_comp_id = getattr(session, "lineage_component_id", None)

        if self.repository is not None:
            historical_cases = await self.repository.active_review_cases_before(cutoff_time)
        else:
            historical_cases = [c for c in self._review_cases.values() if c.created_at < cutoff_time or not hasattr(c, "created_at")]

        return find_similar_review_cases(
            case_blocks,
            historical_cases,
            top_k=top_k,
            min_common_blocks=min_common_blocks,
            min_similarity=min_similarity,
            query_candidate_id=candidate_id,
            query_review_id=review_id,
            query_lineage_component_id=lineage_comp_id,
            query_operation=target_exp.operation if target_exp else "UNKNOWN",
            query_domain=review_domain,
            query_schema_version="cf-case-v1",
            query_review_time=cutoff_time,
        )
