"""Version 1 REST routes; live clients use SSE only for resource invalidation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.exc import SQLAlchemyError

from graybox import adapt_graybox_metadata
from libs.contracts import ContractIngestError
from libs.contracts.analysis_identity import (
    analysis_identity_from_review,
    analysis_identity_from_projection,
)
from libs.contracts.topology_identity import effective_topology_version, snapshot_topology_profile

from .schemas import (
    CandidateDisplayEventBatchSubmission,
    CandidateDisplayEventBatchView,
    ChainListView,
    ChainOverviewCardsView,
    ChainQualitySummaryView,
    ChainQualityAssessmentView,
    ChainSummaryView,
    CounterfactualJobView,
    OperatorFeedbackSubmission,
    OperatorFeedbackView,
    ReasonPolicyView,
    RetractionSubmission,
    CohesionNarrativeView,
    AssistantQueryInput,
    AssistantResponseView,
    AuditVisualizationArtifactView,
    ConfigUpdateInput,
    ConfigView,
    EvolutionView,
    EvolutionChangesView,
    EvidenceBundleView,
    EvidenceRecordView,
    JobSubmissionView,
    JobView,
    PairWhyView,
    SelectSnapshotRequest,
    SnapshotCatalogListView,
    SnapshotLoadedView,
    SnapshotQualitySummaryListView,
    SystemPairFactView,
    ApplyThresholdInput,
    ProposalClarityComparisonView,
    ThresholdExplainOptimizationView,
    RecurrentAlarmHistoryView,
)
from .blocking_work import (
    BlockingWorkBusy,
    BlockingWorkClosed,
    run_blocking as run_blocking_work,
)
from .catalog import list_catalog_presets, load_preset_payload
from .threshold_explain_optimizer import (
    apply_explain_threshold,
    find_clearest_explain_threshold,
)
from tier2.counterfactual.explain_clarity_comparator import (
    compare_proposal_explanations,
)
from tier2.counterfactual.jobs import ReviewIdentity, artifact_fingerprint
from .serializers import (
    chain_analysis_view,
    counterfactual_job_view,
    operator_feedback_view,
    audit_visualization_artifact_view,
    evolution_view,
    job_view,
    pair_evidence_view,
)
from .workspace import SnapshotNotLoaded, Workspace, _topology_version
from .review_feedback_history import (
    LifecycleStatus,
    ReviewFeedbackHistoryPage,
    load_review_feedback_history,
)
from .evolution_changes import compare_evolution_facts
from .cohesion_advisor import (
    CHAIN_OVERVIEW_PROJECTION_VERSION,
)
from .recurrent_alarm_history import chain_recurrence_history
from .quality_freshness import (
    projection_staleness_reason,
    record_quality_freshness_lag,
)
from .quality_readiness import quality_assessment_contract_is_valid
from .evidence_projection import (
    InvalidEvidenceCursor,
    StaleEvidenceCursor,
    build_evidence_records,
    paginate_evidence_records,
)
from .entity_resolver import AlarmEntityResolver
from .review_principal import (
    ReviewReasonPolicyUnavailable,
    ReviewerPrincipal,
    get_reviewer_principal_async,
    load_reason_policy,
)
from review_learning.contracts import SimilarCaseRetrievalResult
from sqlalchemy import select
from .persistence.models import (
    Chain,
    ChainQualityAssessmentRecord,
    CohesionNarrativeCache,
    CounterfactualJobRecord,
    DeepDiveJobRecord,
    Snapshot,
    SnapshotIngest,
)


router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)
MAX_REVIEW_AI_ENRICHMENTS = 3
MAX_REVIEW_AI_CONCURRENCY = 2
COHESION_NARRATIVE_VERSION = "grounded-investigation-v6"



def workspace(request: Request) -> Workspace:
    return request.app.state.workspace


def topology_repo(request: Request):
    return getattr(request.app.state, "topology_repository", None)


async def _active_unpinned_topology_is_stale(
    service: Workspace, request: Request, package: Any
) -> bool:
    """An already-open unpinned snapshot may lag a Kafka topology activation."""
    repository = getattr(service, "repository", None)
    topo_repository = topology_repo(request)
    if repository is None or topo_repository is None:
        return False
    snapshot_id = package.snapshot.snapshot_id
    snapshot_version = package.snapshot.snapshot_version
    async with repository.sessions() as session:
        source = await session.get(SnapshotIngest, (snapshot_id, snapshot_version))
    if source is None or source.topology_version_ref:
        return False
    profile = snapshot_topology_profile(snapshot_id, source.topology_profile_id)
    if profile is None:
        return False
    current_version = await effective_topology_version(
        snapshot_id,
        pinned_version=None,
        explicit_profile=profile,
        repository=topo_repository,
    )
    return current_version != _topology_version(package)


def _cohesion_input_fingerprint(
    service: Workspace,
    *,
    audit_artifact: Any | None,
    deep_dive_job: Any | None,
    review_job: Any | None,
) -> str:
    """Identify every mutable input represented by a cached cohesion narrative."""
    review_identity = getattr(review_job, "identity", None)
    if isinstance(review_identity, dict):
        pipeline_version = str(review_identity.get("engine_version") or "")
        source_fingerprint = str(
            review_identity.get("tier1b_artifact_fingerprint") or ""
        )
    else:
        pipeline_version = str(getattr(review_identity, "engine_version", "") or "")
        source_fingerprint = str(
            getattr(review_identity, "tier1b_artifact_fingerprint", "") or ""
        )
    shared_identity = analysis_identity_from_review(
        review_identity,
        pipeline_version=pipeline_version,
        input_fingerprint=source_fingerprint,
    )
    payload = {
        "narrative_version": COHESION_NARRATIVE_VERSION,
        "config_version": getattr(getattr(service, "config", None), "config_version", None),
        "review_config_version": (
            getattr(getattr(getattr(service, "config", None), "counterfactual", None), "config_version", None)
        ),
        "topology_version": _topology_version(getattr(service, "package", None)),
        "analysis_identity": (
            shared_identity.identity.to_payload()
            if shared_identity.available and shared_identity.identity is not None
            else {"status": shared_identity.reason or "IDENTITY_INCOMPLETE"}
        ),
        "audit": getattr(audit_artifact, "artifact_fingerprint", None)
        or getattr(audit_artifact, "artifact_id", None),
        "deep_dive": getattr(deep_dive_job, "job_id", None)
        or getattr(deep_dive_job, "cache_fingerprint", None),
        "review": getattr(review_job, "job_id", None)
        or getattr(review_job, "cache_fingerprint", None),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _should_preserve_cached_cohesion(
    cached_row: Any | None,
    generated_result: Any,
    input_fingerprint: str,
) -> bool:
    """Keep a matching provider-success row only for provider outages.

    A raw provider response with a ``GROUNDING_*`` diagnostic is deliberately
    not hidden behind an older cache row: the Cohesion inspection path exists so
    operators can see exactly what the current model returned.
    """
    if cached_row is None:
        return False
    generated_status = str(getattr(generated_result, "provider_status", None) or "")
    generated_model = str(getattr(generated_result, "model", None) or "")
    if generated_status == "GROUNDING_BYPASS" or (
        generated_status.startswith("GROUNDING_")
        and generated_model != "DETERMINISTIC_EVIDENCE"
    ):
        return False
    if getattr(cached_row, "input_fingerprint", None) != input_fingerprint:
        return False
    def is_complete_provider_result(value: Any) -> bool:
        narrative = str(getattr(value, "narrative", "")).strip()
        # Migrate away from rows written by older builds that persisted the
        # deterministic fallback as if it were provider prose.
        is_legacy_fallback = narrative.startswith(
            (
                "Chưa tạo được nhận định AI đáp ứng kiểm tra grounding.",
                "No AI investigation insight passed grounding validation.",
            )
        )
        return (
            getattr(value, "provider_status", None) == "OK"
            and getattr(value, "model", None) != "DETERMINISTIC_EVIDENCE"
            and not is_legacy_fallback
            and re.search(r"[.!?…。][\"'”’)]*$", narrative) is not None
        )

    cached_is_good = is_complete_provider_result(cached_row)
    generated_is_good = is_complete_provider_result(generated_result)
    return cached_is_good and not generated_is_good


async def _run_grounded_provider(function: Any, **kwargs: Any) -> Any:
    """Run a synchronous provider function on the bounded provider pool."""
    try:
        return await run_blocking_work(function, workload="provider", **kwargs)
    except (BlockingWorkBusy, BlockingWorkClosed) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI provider capacity is temporarily unavailable",
            headers={"Retry-After": "1"},
        ) from exc


async def _run_blocking(function: Any, *args: Any, **kwargs: Any) -> Any:
    """Run one synchronous read on the bounded API-read pool."""
    try:
        return await run_blocking_work(function, *args, workload="api-read", **kwargs)
    except (BlockingWorkBusy, BlockingWorkClosed) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API read capacity is temporarily unavailable",
            headers={"Retry-After": "1"},
        ) from exc


def translate_error(exc: Exception) -> HTTPException:
    from review_learning.contracts import (
        ReviewSessionNotFound,
        ReviewFeedbackNotFound,
        UnknownExposureCandidate,
        ImmutableReviewConflict,
        InactiveFeedbackConflict,
        ReviewIdentityUnavailable,
        ReviewDomainForbidden,
        ReviewerRoleForbidden,
    )
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, (ImmutableReviewConflict, InactiveFeedbackConflict, SnapshotNotLoaded)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (ReviewSessionNotFound, ReviewFeedbackNotFound)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (ReviewDomainForbidden, ReviewerRoleForbidden)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ReviewIdentityUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, ReviewReasonPolicyUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, (UnknownExposureCandidate, ContractIngestError, ValueError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )
    if isinstance(exc, KeyError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise exc


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/snapshots", response_model=SnapshotCatalogListView)
async def list_snapshots(request: Request) -> SnapshotCatalogListView:
    service = workspace(request)
    active_id = None
    active_version = None
    try:
        pkg = service.require_package()
        active_id = pkg.snapshot.snapshot_id
        active_version = pkg.snapshot.snapshot_version
    except Exception:
        pass

    presets = list_catalog_presets()

    # Merge live snapshots from DB (Kafka-ingested, tier1a=READY)
    # so the catalog auto-updates when new snapshots arrive via Kafka
    if service.repository is not None:
        try:
            preset_identities = {
                (p["snapshot_id"], p.get("snapshot_version")) for p in presets
            }
            live_rows = []
            page_size = 200
            offset = 0
            while True:
                page = await service.repository.list_live_snapshots(
                    limit=page_size,
                    offset=offset,
                )
                live_rows.extend(page)
                if len(page) < page_size:
                    break
                offset += page_size
            _PROFILE_MAP = {
                "IP_NETWORK": "IP_NETWORK",
                "IT_SERVICES": "IT_SERVICES",
                "ALARM_ONLY": "ALARM_ONLY",
            }
            for row in live_rows:
                sid = row["snapshot_id"]
                identity = (sid, row["snapshot_version"])
                if identity in preset_identities:
                    continue  # the artifact-backed preset takes priority
                raw_profile = str(
                    row.get("topology_profile_id") or row.get("source_kind") or ""
                )
                mapped_profile = _PROFILE_MAP.get(raw_profile.upper())
                profile = mapped_profile or "ALARM_ONLY"
                presets.append({
                    "snapshot_id": sid,
                    "snapshot_version": row["snapshot_version"],
                    "name": sid,
                    "profile": profile,
                    "alarm_count": row["alarm_count"],
                    "chain_count": row["chain_count"],
                    "description": (
                        f"Live snapshot ingested via Kafka (version {row['snapshot_version']})"
                        if mapped_profile
                        else (
                            f"Live snapshot ingested via Kafka (version {row['snapshot_version']}); "
                            f"unknown topology profile: {raw_profile or 'missing'}"
                        )
                    ),
                    "badge": "Live",
                    "available": True,
                    "unavailable_reason": None,
                })
        except Exception:
            pass  # DB unavailable — degrade gracefully, still return presets

    return SnapshotCatalogListView(
        active_snapshot_id=active_id,
        active_snapshot_version=active_version,
        snapshots=presets,
    )


async def _persisted_quality_summaries(service: Workspace) -> list[ChainQualitySummaryView]:
    """Summarize only persisted assessments and active analysis jobs.

    Singleton chains are deliberately outside the quality denominator because
    HEURISTIC_V1 marks them NOT_APPLICABLE.  A missing cache row means that no
    chain-quality result has been persisted; it is not treated as a bad chain.
    """
    if service.repository is None:
        return []

    async with service.repository.sessions() as session:
        chain_rows = list((await session.scalars(select(Chain))).all())
        snapshot_ids = {row.snapshot_id for row in chain_rows}
        if not snapshot_ids:
            return []
        snapshot_versions = {
            (row.snapshot_id, row.snapshot_version): row.topology_version
            for row in (await session.execute(select(
                Snapshot.snapshot_id, Snapshot.snapshot_version, Snapshot.topology_version,
            ).where(Snapshot.snapshot_id.in_(snapshot_ids)))).all()
        }
        ingest_topology = {
            (row.snapshot_id, row.snapshot_version): row
            for row in (await session.execute(select(
                SnapshotIngest.snapshot_id,
                SnapshotIngest.snapshot_version,
                SnapshotIngest.topology_profile_id,
                SnapshotIngest.topology_version_ref,
            ).where(SnapshotIngest.snapshot_id.in_(snapshot_ids)))).all()
        }
        quality_rows = list(
            (
                await session.scalars(
                    select(ChainQualityAssessmentRecord)
                    .where(ChainQualityAssessmentRecord.snapshot_id.in_(snapshot_ids))
                )
            ).all()
        )
        active_deep_dive_jobs = list(
            (
                await session.scalars(
                    select(DeepDiveJobRecord)
                    .where(DeepDiveJobRecord.status.in_(("QUEUED", "RUNNING")))
                    .where(DeepDiveJobRecord.snapshot_id.in_(snapshot_ids))
                    .order_by(DeepDiveJobRecord.updated_at.desc())
                )
            ).all()
        )
        active_review_jobs = list(
            (
                await session.scalars(
                    select(CounterfactualJobRecord)
                    .where(CounterfactualJobRecord.status.in_(("QUEUED", "RUNNING")))
                    .where(CounterfactualJobRecord.snapshot_id.in_(snapshot_ids))
                    .order_by(CounterfactualJobRecord.updated_at.desc())
                )
            ).all()
        )

    topology_repository = getattr(getattr(service, "coordinator", None), "topology_repository", None)
    active_by_profile: dict[str, str | None] = {}
    expected_topology_versions: dict[tuple[str, str], str | None] = {}
    for identity in {(row.snapshot_id, row.snapshot_version) for row in chain_rows}:
        ingested = ingest_topology.get(identity)
        if ingested is None:
            expected_topology_versions[identity] = snapshot_versions.get(identity)
            continue
        expected_topology_versions[identity] = await effective_topology_version(
            identity[0],
            pinned_version=ingested.topology_version_ref,
            explicit_profile=ingested.topology_profile_id,
            repository=topology_repository,
            active_by_profile=active_by_profile,
        )

    return _build_persisted_quality_summaries(
        chain_rows,
        quality_rows,
        [*active_deep_dive_jobs, *active_review_jobs],
        expected_config_version=getattr(service.config, "config_version", None),
        expected_review_config_version=(
            service.config.counterfactual.config_version
            if service.config.counterfactual is not None
            else "UNAVAILABLE"
        ),
        expected_topology_versions=expected_topology_versions,
    )


def _build_persisted_quality_summaries(
    chain_rows: list[Any],
    quality_rows: list[Any],
    active_jobs: list[Any],
    *,
    expected_config_version: str | None = None,
    expected_review_config_version: str | None = None,
    expected_topology_versions: dict[tuple[str, str], str | None] | None = None,
) -> list[ChainQualitySummaryView]:
    chains_by_snapshot: dict[tuple[str, str], dict[str, Any]] = {}
    for row in chain_rows:
        chains_by_snapshot.setdefault(
            (row.snapshot_id, row.snapshot_version), {}
        )[row.chain_id] = row

    latest_assessment: dict[tuple[str, str, str], tuple[dict[str, Any], Any]] = {}
    for row in quality_rows:
        key = (row.snapshot_id, row.snapshot_version, row.chain_id)
        assessment = row.payload if isinstance(row.payload, dict) else None
        if isinstance(assessment, dict):
            latest_assessment[key] = (assessment, row)

    evaluating: set[tuple[str, str, str]] = set()
    for row in active_jobs:
        if _active_quality_job_is_current(
            row,
            expected_config_version=expected_config_version,
            expected_review_config_version=expected_review_config_version,
            expected_topology_version=expected_topology_versions.get(
                (row.snapshot_id, row.snapshot_version)
            ) if expected_topology_versions is not None else None,
            topology_version_known=(
                expected_topology_versions is not None
                and (row.snapshot_id, row.snapshot_version) in expected_topology_versions
            ),
        ):
            evaluating.add((row.snapshot_id, row.snapshot_version, row.chain_id))

    summaries: list[ChainQualitySummaryView] = []
    for (snapshot_id, snapshot_version), rows_by_chain in sorted(chains_by_snapshot.items()):
        eligible_ids = {
            chain_id for chain_id, row in rows_by_chain.items()
            if row.member_count > 1
        }
        sturdy_ids: set[str] = set()
        review_ids: set[str] = set()
        unavailable_ids: set[str] = set()
        star_counts = {str(star): 0 for star in range(1, 6)}
        for chain_id in eligible_ids:
            record = latest_assessment.get((snapshot_id, snapshot_version, chain_id))
            if not record:
                continue
            assessment, quality_row = record
            status = str(assessment.get("status", "")).upper()
            if status not in {"EVALUATED", "UNAVAILABLE"}:
                continue
            if not quality_assessment_contract_is_valid(assessment):
                continue
            if not _quality_assessment_is_current(
                assessment,
                canonical_row=quality_row,
                expected_config_version=expected_config_version,
                expected_review_config_version=expected_review_config_version,
                expected_topology_version=(expected_topology_versions or {}).get((snapshot_id, snapshot_version)),
                topology_version_known=expected_topology_versions is not None and (snapshot_id, snapshot_version) in expected_topology_versions,
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
            ):
                record_quality_freshness_lag(
                    quality_row, stage="portfolio", state="stale"
                )
                # A quality row is immutable evidence for the config that
                # produced it.  Do not present an older projection as a
                # current portfolio result after calibration/restart.
                continue
            record_quality_freshness_lag(
                quality_row, stage="portfolio", state="current"
            )
            if status == "UNAVAILABLE":
                unavailable_ids.add(chain_id)
                continue
            stars = assessment.get("stars")
            if not isinstance(stars, (int, float)):
                continue
            rounded_stars = max(1, min(5, int(stars)))
            star_counts[str(rounded_stars)] += 1
            (sturdy_ids if stars >= 4 else review_ids).add(chain_id)

        evaluated_ids = sturdy_ids | review_ids
        evaluating_ids = {
            chain_id for chain_id in eligible_ids - evaluated_ids - unavailable_ids
            if (snapshot_id, snapshot_version, chain_id) in evaluating
        }
        unevaluated_count = max(
            0,
            len(eligible_ids)
            - len(evaluated_ids)
            - len(unavailable_ids)
            - len(evaluating_ids),
        )

        chain_assessments: list[ChainQualityAssessmentView] = []
        for chain_id in eligible_ids:
            row = rows_by_chain[chain_id]
            record = latest_assessment.get((snapshot_id, snapshot_version, chain_id))
            assessment = record[0] if record else None
            quality_row = record[1] if record else None
            analysis_identity_payload = None
            artifact_revision_payload = None
            if assessment and str(assessment.get("status", "")).upper() in {
                "EVALUATED",
                "UNAVAILABLE",
            }:
                if not quality_assessment_contract_is_valid(assessment) or not _quality_assessment_is_current(
                    assessment,
                    canonical_row=quality_row,
                    expected_config_version=expected_config_version,
                    expected_review_config_version=expected_review_config_version,
                    expected_topology_version=(expected_topology_versions or {}).get((snapshot_id, snapshot_version)),
                    topology_version_known=expected_topology_versions is not None and (snapshot_id, snapshot_version) in expected_topology_versions,
                    snapshot_id=snapshot_id,
                    snapshot_version=snapshot_version,
                ):
                    # Do not leak stale stars or reasons into the all-chains
                    # list while the current config is awaiting evaluation.
                    assessment = None
                else:
                    projection = assessment.get("overview_projection")
                    adapted_identity = analysis_identity_from_projection(projection)
                    if adapted_identity.available and adapted_identity.identity is not None:
                        analysis_identity_payload = adapted_identity.identity.to_payload()
                        artifact_revision_payload = {
                            "resource_kind": "chain_overview",
                            "fingerprint": adapted_identity.identity.input_fingerprint,
                        }
            stars = (
                assessment.get("stars")
                if assessment and assessment.get("readiness") == "READY"
                else None
            )
            reasons = assessment.get("reasons") if assessment else None
            reason_codes = assessment.get("reason_codes") if assessment else None
            evidence_coverage = assessment.get("evidence_coverage") if assessment else None
            evidence_ids = assessment.get("evidence_ids") if assessment else None
            reason_evidence_ids = assessment.get("reason_evidence_ids") if assessment else None
            readiness = assessment.get("readiness") if assessment else None
            if chain_id in review_ids:
                status = "REVIEW"
                label = str(assessment.get("label") or "Cần xem")
                reason = str(reasons[0]) if isinstance(reasons, list) and reasons else None
            elif chain_id in evaluating_ids:
                status = "EVALUATING"
                label = "Đang đánh giá"
                reason = "Deep Dive hoặc Counterfactual đang chạy ngầm."
            elif chain_id in unavailable_ids:
                status = "UNAVAILABLE"
                label = str(assessment.get("label") or "Thiếu evidence")
                reason = str(reasons[0]) if isinstance(reasons, list) and reasons else None
            elif chain_id not in evaluated_ids:
                status = "WAITING"
                label = "Chờ đánh giá"
                reason = "Chưa có kết quả deterministic được lưu."
            else:
                status = "EVALUATED"
                label = str(assessment.get("label") or "Đã đánh giá") if assessment else "Đã đánh giá"
                reason = None
            chain_assessments.append(ChainQualityAssessmentView(
                chain_id=chain_id,
                member_count=row.member_count,
                title=str(getattr(row, "chain_name", None) or f"Chain {chain_id}"),
                duration_seconds=(
                    float(getattr(row, "event_span_seconds", None))
                    if getattr(row, "event_span_seconds", None) is not None
                    else None
                ),
                status=status,
                stars=int(stars) if isinstance(stars, (int, float)) else None,
                label=label,
                reason=reason,
                readiness=str(readiness) if readiness is not None else None,
                readiness_policy_version=(
                    str(assessment.get("readiness_policy_version"))
                    if assessment and assessment.get("readiness_policy_version") is not None
                    else None
                ),
                reason_codes=(
                    [str(code) for code in reason_codes]
                    if isinstance(reason_codes, list)
                    else []
                ),
                evidence_coverage=(
                    evidence_coverage if isinstance(evidence_coverage, dict) else None
                ),
                evidence_ids=(
                    [str(value) for value in evidence_ids]
                    if isinstance(evidence_ids, list)
                    else []
                ),
                reason_evidence_ids=(
                    {
                        str(code): [str(value) for value in values]
                        for code, values in reason_evidence_ids.items()
                        if isinstance(values, list)
                    }
                    if isinstance(reason_evidence_ids, dict)
                    else {}
                ),
                analysis_identity=analysis_identity_payload,
                artifact_revision=artifact_revision_payload,
            ))
        for chain_id in sorted(set(rows_by_chain) - eligible_ids):
            row = rows_by_chain[chain_id]
            chain_assessments.append(ChainQualityAssessmentView(
                chain_id=chain_id,
                member_count=row.member_count,
                title=str(getattr(row, "chain_name", None) or f"Chain {chain_id}"),
                duration_seconds=(
                    float(getattr(row, "event_span_seconds", None))
                    if getattr(row, "event_span_seconds", None) is not None
                    else None
                ),
                status="NOT_APPLICABLE",
                stars=None,
                label="Singleton không chấm",
                reason="Singleton không áp dụng chấm độ vững.",
                analysis_identity=None,
                artifact_revision=None,
            ))
        chain_assessments.sort(key=lambda item: item.chain_id)
        attention = [item for item in chain_assessments if item.status not in {"EVALUATED", "NOT_APPLICABLE"}]
        attention.sort(key=lambda item: (
            {"REVIEW": 0, "UNAVAILABLE": 1, "EVALUATING": 2, "WAITING": 3}.get(item.status, 4),
            item.stars if item.stars is not None else 6,
            -item.member_count,
            item.chain_id,
        ))
        summaries.append(ChainQualitySummaryView(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            total_chain_count=len(rows_by_chain),
            eligible_chain_count=len(eligible_ids),
            sturdy_count=len(sturdy_ids),
            review_count=len(review_ids),
            evaluating_count=len(evaluating_ids),
            unevaluated_count=unevaluated_count,
            unavailable_count=len(unavailable_ids),
            not_applicable_count=len(rows_by_chain) - len(eligible_ids),
            star_counts=star_counts,
            attention_chains=attention[:5],
            chain_assessments=chain_assessments,
        ))
    return summaries


def _quality_assessment_is_current(
    assessment: dict[str, Any], *, canonical_row: Any | None = None,
    expected_config_version: str | None,
    expected_review_config_version: str | None = None,
    expected_topology_version: str | None = None,
    topology_version_known: bool = False,
    snapshot_id: str | None = None,
    snapshot_version: str | None = None,
) -> bool:
    """Only expose quality backed by a complete envelope and canonical row."""
    if canonical_row is None or not quality_assessment_contract_is_valid(assessment):
        return False
    return projection_staleness_reason(
        assessment.get("overview_projection"),
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        chain_id=getattr(canonical_row, "chain_id", None),
        config_version=expected_config_version,
        review_config_version=expected_review_config_version,
        topology_version=expected_topology_version,
        topology_version_known=topology_version_known,
        input_fingerprint=getattr(canonical_row, "input_fingerprint", None),
        canonical_row=canonical_row,
    ) is None


def _active_quality_job_is_current(
    job: Any,
    *,
    expected_config_version: str | None,
    expected_review_config_version: str | None = None,
    expected_topology_version: str | None = None,
    topology_version_known: bool = False,
) -> bool:
    """Only count active work for the current config and topology identity."""
    identity = getattr(job, "identity_payload", None)
    if isinstance(identity, dict):
        adapted = analysis_identity_from_review(
            identity,
            pipeline_version=str(identity.get("engine_version") or ""),
            input_fingerprint=str(identity.get("tier1b_artifact_fingerprint") or ""),
        )
        if not adapted.available or adapted.identity is None:
            return False
        try:
            if not set(ReviewIdentity.__dataclass_fields__).issubset(identity):
                return False
            review_identity = ReviewIdentity(**identity)
        except (TypeError, ValueError):
            return False
        if getattr(job, "cache_fingerprint", None) != artifact_fingerprint(
            review_identity.cache_tuple()
        ):
            return False
        job_config_version = adapted.identity.analysis_config_version
        job_review_config_version = adapted.identity.review_config_version
        job_topology_version = identity.get("topology_version")
        if (
            adapted.identity.snapshot_id != getattr(job, "snapshot_id", None)
            or adapted.identity.snapshot_version != getattr(job, "snapshot_version", None)
            or adapted.identity.chain_id != getattr(job, "chain_id", None)
        ):
            return False
        if (
            expected_review_config_version is not None
            and job_review_config_version != expected_review_config_version
        ):
            return False
    else:
        job_config_version = getattr(job, "analysis_config_version", None)
        job_review_config_version = None
        job_topology_version = getattr(job, "topology_version", None)

    if expected_config_version is not None:
        config_matches = (
            job_config_version == expected_config_version
            if isinstance(identity, dict)
            else isinstance(job_config_version, str)
            and (
                job_config_version == expected_config_version
                or job_config_version.startswith(f"{expected_config_version}|")
            )
        )
        if not config_matches:
            return False
    if topology_version_known and job_topology_version != expected_topology_version:
        return False
    return True


@router.get(
    "/snapshots/quality-summaries",
    response_model=SnapshotQualitySummaryListView,
)
async def list_snapshot_quality_summaries(
    request: Request,
) -> SnapshotQualitySummaryListView:
    try:
        service = workspace(request)
        # The overview is also the heartbeat for deterministic quality.  A
        # terminal worker failure must be retried without requiring a manual
        # reload or opening every chain detail page.  Scheduling keeps this
        # status endpoint responsive while the reconciliation runs.
        service.schedule_snapshot_quality_resume()
        summaries = await _persisted_quality_summaries(service)
    except Exception as exc:
        raise translate_error(exc) from exc
    return SnapshotQualitySummaryListView(summaries=summaries)


def _chain_summary_views(service: Workspace) -> list[ChainSummaryView]:
    result = service.list_chains()
    return [
        ChainSummaryView(
            chain_id=item.chain_id,
            member_count=item.member_count,
            is_singleton=item.is_singleton,
            title=item.auto_title,
            start_time=item.start_time,
            end_time=item.end_time,
            duration_seconds=item.duration_seconds,
        )
        for item in sorted(result.chains.values(), key=lambda value: value.chain_id)
    ]


def _active_topology_version(service: Workspace) -> str | None:
    package = service.current_package()
    if package is None:
        return None
    topology = getattr(package, "topology", None)
    version = topology.get("topology_version") if isinstance(topology, dict) else None
    if version is None:
        topology_ref = getattr(package.snapshot, "topology_ref", None)
        version = getattr(topology_ref, "topology_version", None)
    return str(version) if version is not None else None


def _persisted_review_cache_context(
    projection: dict[str, Any],
    *,
    snapshot_id: str,
    snapshot_version: str,
    chain_id: str,
    analysis_config_version: str | None,
    review_config_version: str,
    topology_version: str | None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Expose only the Review identity captured with this current projection.

    This deliberately does not rebuild Review context on the warm Overview
    read path; doing so would rerun Tier-1B and flush/read Audit persistence.
    """
    adapted = analysis_identity_from_projection(
        {"analysis_identity": projection.get("review_analysis_identity")}
    )
    identity = adapted.identity if adapted.available else None
    revision = projection.get("review_artifact_revision")
    if identity is None or not isinstance(revision, dict):
        return None, None
    if (
        identity.snapshot_id != snapshot_id
        or identity.snapshot_version != snapshot_version
        or identity.chain_id != chain_id
        or identity.analysis_config_version != analysis_config_version
        or identity.review_config_version != review_config_version
        or identity.topology_version != topology_version
        or revision.get("resource_kind") != "counterfactual_review"
        or not isinstance(revision.get("fingerprint"), str)
        or not revision["fingerprint"].strip()
    ):
        return None, None
    return identity.to_payload(), {
        "resource_kind": "counterfactual_review",
        "fingerprint": revision["fingerprint"],
    }


async def _ingest_selected_snapshot(service: Workspace, payload: dict[str, Any]):
    """Serialize UI snapshot selections so last request cannot be overwritten."""
    lock = getattr(service, "_snapshot_selection_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(service, "_snapshot_selection_lock", lock)
    async with lock:
        return await service.ingest_snapshot(payload)



@router.post(
    "/snapshots/select",
    response_model=SnapshotLoadedView,
    status_code=status.HTTP_200_OK,
)
async def select_snapshot(
    body: SelectSnapshotRequest, request: Request
) -> SnapshotLoadedView:
    service = workspace(request)
    try:
        active_identity = service.active_identity()
        try:
            payload, _ = load_preset_payload(body.snapshot_id)
            raw_snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
            preset_version = raw_snapshot.get("snapshot_version") if isinstance(raw_snapshot, dict) else None
            if body.snapshot_version is not None and str(preset_version) != body.snapshot_version:
                raise KeyError(
                    f"Unknown snapshot identity: {body.snapshot_id!r}@{body.snapshot_version!r}"
                )
        except (KeyError, ValueError):
            if service.repository is not None:
                if body.snapshot_version is None:
                    payload = await service.repository.get_ready_snapshot_payload(body.snapshot_id)
                else:
                    payload = await service.repository.get_ready_snapshot_payload(
                        body.snapshot_id, body.snapshot_version
                    )
                if payload is None:
                    raise KeyError(f"Unknown snapshot_id: {body.snapshot_id!r}")
            elif (
                active_identity is not None
                and active_identity[0] == body.snapshot_id
                and (body.snapshot_version is None or active_identity[1] == body.snapshot_version)
            ):
                # Test/demo workspaces can already hold an explicitly injected
                # snapshot that is not part of the preset catalog.  Preserve
                # the active no-op contract when there is no alternate source
                # from which a newer same-ID version could be resolved.
                current = service.list_chains()
                return SnapshotLoadedView(
                    snapshot_id=current.snapshot_id,
                    snapshot_version=active_identity[1],
                    topology_version=_active_topology_version(service),
                    alarm_count=current.alarm_count,
                    chain_count=current.chain_count,
                    incremental_snapshot={
                        "mode": service.config.incremental_snapshot.mode.value,
                        "reason": service.config.incremental_snapshot.reason,
                    },
                    chains=_chain_summary_views(service),
                )
            else:
                raise
        raw_snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
        requested_identity = (
            str(raw_snapshot.get("snapshot_id")),
            str(raw_snapshot.get("snapshot_version")),
        ) if isinstance(raw_snapshot, dict) else None
        # Compare the exact catalog identity, not just snapshot_id.  Kafka can
        # publish a new version under the same ID; treating that as a no-op
        # would leave the UI on stale evidence after a refresh.
        if active_identity is not None and requested_identity == active_identity:
            current = service.list_chains()
            return SnapshotLoadedView(
                snapshot_id=current.snapshot_id,
                snapshot_version=active_identity[1],
                topology_version=_active_topology_version(service),
                alarm_count=current.alarm_count,
                chain_count=current.chain_count,
                incremental_snapshot={
                    "mode": service.config.incremental_snapshot.mode.value,
                    "reason": service.config.incremental_snapshot.reason,
                },
                chains=_chain_summary_views(service),
            )
        result = await _ingest_selected_snapshot(service, payload)
    except Exception as exc:
        raise translate_error(exc) from exc
    return SnapshotLoadedView(
        snapshot_id=result.snapshot_id,
        snapshot_version=service.require_package().snapshot.snapshot_version,
        topology_version=_active_topology_version(service),
        alarm_count=result.alarm_count,
        chain_count=result.chain_count,
        incremental_snapshot={
            "mode": service.config.incremental_snapshot.mode.value,
            "reason": service.config.incremental_snapshot.reason,
        },
        chains=_chain_summary_views(service),
    )


@router.post(
    "/snapshots",
    response_model=SnapshotLoadedView,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def load_snapshot(
    payload: dict[str, Any], request: Request
) -> SnapshotLoadedView:
    service = workspace(request)
    try:
        result = await service.ingest_snapshot(payload)
    except Exception as exc:
        raise translate_error(exc) from exc
    return SnapshotLoadedView(
        snapshot_id=result.snapshot_id,
        snapshot_version=service.require_package().snapshot.snapshot_version,
        topology_version=_active_topology_version(service),
        alarm_count=result.alarm_count,
        chain_count=result.chain_count,
        incremental_snapshot={
            "mode": service.config.incremental_snapshot.mode.value,
            "reason": service.config.incremental_snapshot.reason,
        },
    )


@router.get("/chains", response_model=ChainListView)
async def list_chains(request: Request) -> ChainListView:
    try:
        service = workspace(request)
        result = service.list_chains()
        # In the normal persisted deployment the snapshot-wide runner owns
        # this queue.  Keep the in-process fallback for demo mode, but honour
        # the explicit quality switch so tests/disabled deployments do not
        # leave Tier-2 executor threads running after a simple list request.
        if getattr(service, "auto_chain_quality", False):
            service.precompute_snapshot_deep_dive()
    except Exception as exc:
        raise translate_error(exc) from exc
    return ChainListView(
        snapshot_id=result.snapshot_id,
        snapshot_version=workspace(request).require_package().snapshot.snapshot_version,
        topology_version=_active_topology_version(workspace(request)),
        chains=_chain_summary_views(workspace(request)),
    )


@router.post("/snapshots/precompute-deep-dive")
async def trigger_precompute_deep_dive(
    request: Request,
) -> dict[str, Any]:
    try:
        service = workspace(request)
        return service.precompute_snapshot_deep_dive()
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/chains/{chain_id}/overview-cards",
    response_model=ChainOverviewCardsView,
)
async def get_chain_overview_cards(
    chain_id: str, request: Request
) -> ChainOverviewCardsView:
    """Read the persisted deterministic Overview projection without AI work."""
    service = workspace(request)
    package = service.require_package()
    snapshot_id = package.snapshot.snapshot_id
    snapshot_version = package.snapshot.snapshot_version
    if chain_id not in package.chains:
        raise KeyError(f"unknown chain_id {chain_id!r}")

    if await _active_unpinned_topology_is_stale(service, request, package):
        return ChainOverviewCardsView(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            chain_id=chain_id,
            status="PENDING",
            reason="DETERMINISTIC_OVERVIEW_TOPOLOGY_MISMATCH",
        )

    if len(package.members_of(chain_id)) <= 1:
        return ChainOverviewCardsView(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            chain_id=chain_id,
            status="NOT_APPLICABLE",
            reason="SINGLETON_CHAIN",
        )

    quality_record = None
    if service.repository is not None:
        quality_record = await service.repository.chain_quality_assessment(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            chain_id=chain_id,
        )
    payload = getattr(quality_record, "payload", None)
    projection = payload.get("overview_projection") if isinstance(payload, dict) else None
    if not isinstance(projection, dict):
        return ChainOverviewCardsView(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            chain_id=chain_id,
            status="PENDING",
            reason="DETERMINISTIC_OVERVIEW_PROJECTION_PENDING",
        )

    stale_reason = projection_staleness_reason(
        projection,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        chain_id=chain_id,
        config_version=getattr(service.config, "config_version", None),
        review_config_version=(
            service.config.counterfactual.config_version
            if service.config.counterfactual is not None
            else "UNAVAILABLE"
        ),
        topology_version=_topology_version(package),
        topology_version_known=snapshot_topology_profile(
            snapshot_id,
            getattr(getattr(package.snapshot, "topology_ref", None), "profile_id", None),
        ) is not None,
        input_fingerprint=getattr(quality_record, "input_fingerprint", None),
        canonical_row=quality_record,
    )
    record_quality_freshness_lag(
        quality_record,
        stage="overview",
        state="current" if stale_reason is None else "stale",
    )
    if stale_reason is not None:
        return ChainOverviewCardsView(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            chain_id=chain_id,
            status="PENDING",
            reason=f"DETERMINISTIC_OVERVIEW_{stale_reason}",
            projection_version=(
                str(projection.get("projection_version") or "")
                if stale_reason == "PROJECTION_STALE" else None
            ),
        )

    adapted_identity = analysis_identity_from_projection(projection)
    projection_identity = adapted_identity.identity if adapted_identity.available else None
    artifact_revision = (
        {
            "resource_kind": "chain_overview",
            "fingerprint": projection_identity.input_fingerprint,
        }
        if projection_identity is not None
        else None
    )
    review_identity_payload, review_artifact_revision = _persisted_review_cache_context(
        projection,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        chain_id=chain_id,
        analysis_config_version=getattr(service.config, "config_version", None),
        review_config_version=(
            service.config.counterfactual.config_version
            if service.config.counterfactual is not None
            else "UNAVAILABLE"
        ),
        topology_version=_topology_version(package),
    )

    return ChainOverviewCardsView(
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        chain_id=chain_id,
        status="READY",
        projection_version=CHAIN_OVERVIEW_PROJECTION_VERSION,
        topology_version=projection.get("topology_version"),
        representative_member=projection.get("representative_member"),
        topology=projection.get("topology"),
        quality_assessment=projection.get("quality_assessment"),
        recommendations=projection.get("recommendations"),
        analysis_identity=(
            projection_identity.to_payload() if projection_identity is not None else None
        ),
        artifact_revision=artifact_revision,
        review_analysis_identity=review_identity_payload,
        review_artifact_revision=review_artifact_revision,
    )


def _require_evidence_snapshot_context(
    service: Workspace,
    *,
    chain_id: str,
    snapshot_id: str | None,
    snapshot_version: str | None,
) -> Any:
    package = service.require_package()
    if not snapshot_id or not snapshot_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="EVIDENCE_SNAPSHOT_CONTEXT_REQUIRED",
        )
    if (
        snapshot_id != package.snapshot.snapshot_id
        or snapshot_version != package.snapshot.snapshot_version
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="STALE_ANALYSIS_CONTEXT",
        )
    if chain_id not in package.chains:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown chain_id {chain_id!r}",
        )
    return package


async def _current_evidence_records(
    *,
    service: Workspace,
    package: Any,
    chain_id: str,
    overview: ChainOverviewCardsView,
) -> tuple[Any, list[dict[str, Any]]]:
    adapted_identity = analysis_identity_from_projection(
        {"analysis_identity": overview.analysis_identity.model_dump(mode="json")}
        if overview.analysis_identity is not None
        else None
    )
    identity = adapted_identity.identity if adapted_identity.available else None
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="EVIDENCE_ANALYSIS_IDENTITY_UNAVAILABLE",
        )

    projection = {
        "analysis_identity": identity.to_payload(),
        "review_analysis_identity": (
            overview.review_analysis_identity.model_dump(mode="json")
            if overview.review_analysis_identity is not None
            else None
        ),
        "review_artifact_revision": (
            overview.review_artifact_revision.model_dump(mode="json")
            if overview.review_artifact_revision is not None
            else None
        ),
        "topology": overview.topology,
        "quality_assessment": overview.quality_assessment,
        "recommendations": overview.recommendations,
    }

    audit_artifact = None
    if service.repository is not None:
        lookup = await service.latest_audit_visualization(chain_id)
        audit_artifact = lookup.audit_artifact

    review_result = None
    repository = service.repository
    if repository is not None and callable(getattr(repository, "chain_quality_assessment", None)):
        quality_row = await repository.chain_quality_assessment(
            snapshot_id=identity.snapshot_id,
            snapshot_version=identity.snapshot_version,
            chain_id=chain_id,
        )
        review_job_id = getattr(quality_row, "counterfactual_job_id", None)
        if review_job_id and callable(getattr(repository, "counterfactual_job", None)):
            stored_review = await repository.counterfactual_job(review_job_id)
            review_identity_payload = getattr(stored_review, "identity", None)
            if isinstance(review_identity_payload, dict):
                adapted_review = analysis_identity_from_review(
                    review_identity_payload,
                    pipeline_version=str(review_identity_payload.get("engine_version") or ""),
                    input_fingerprint=str(
                        review_identity_payload.get("tier1b_artifact_fingerprint") or ""
                    ),
                )
                expected_review = (
                    overview.review_analysis_identity.model_dump(mode="json")
                    if overview.review_analysis_identity is not None
                    else None
                )
                expected_revision = (
                    overview.review_artifact_revision.fingerprint
                    if overview.review_artifact_revision is not None
                    else None
                )
                if (
                    adapted_review.available
                    and adapted_review.identity is not None
                    and adapted_review.identity.to_payload() == expected_review
                    and getattr(stored_review, "snapshot_id", None) == identity.snapshot_id
                    and getattr(stored_review, "snapshot_version", None) == identity.snapshot_version
                    and getattr(stored_review, "chain_id", None) == chain_id
                    and getattr(stored_review, "cache_fingerprint", None) == expected_revision
                    and getattr(stored_review, "status", None) == "SUCCEEDED"
                    and isinstance(getattr(stored_review, "result", None), dict)
                ):
                    review_result = {
                        "job_id": stored_review.job_id,
                        "status": stored_review.status,
                        "analysis_identity": adapted_review.identity.to_payload(),
                        "result": stored_review.result,
                    }
                    expected_audit_fingerprint = review_identity_payload.get(
                        "structural_audit_artifact_fingerprint"
                    )
                    if (
                        audit_artifact is not None
                        and expected_audit_fingerprint
                        != getattr(audit_artifact, "artifact_fingerprint", None)
                    ):
                        audit_artifact = None

    if service.require_package() is not package:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="STALE_ANALYSIS_CONTEXT",
        )
    records = build_evidence_records(
        identity=identity,
        overview_projection=projection,
        pair_evidence=None,
        audit_artifact=audit_artifact,
        review_result=review_result,
    )
    return identity, records


@router.get(
    "/chains/{chain_id}/evidence",
    response_model=EvidenceBundleView,
)
async def get_chain_evidence(
    chain_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=4096),
    snapshot_id: str | None = Header(None, alias="X-NocPro-Snapshot-Id"),
    snapshot_version: str | None = Header(None, alias="X-NocPro-Snapshot-Version"),
    topology_version: str | None = Header(None, alias="X-NocPro-Topology-Version"),
) -> EvidenceBundleView:
    service = workspace(request)
    package = _require_evidence_snapshot_context(
        service,
        chain_id=chain_id,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
    )
    overview = await get_chain_overview_cards(chain_id, request)
    if overview.status != "READY":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=overview.reason or "EVIDENCE_PROJECTION_NOT_READY",
        )
    if topology_version is not None and (topology_version or None) != overview.topology_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="STALE_TOPOLOGY_CONTEXT",
        )
    identity, records = await _current_evidence_records(
        service=service,
        package=package,
        chain_id=chain_id,
        overview=overview,
    )
    try:
        page = paginate_evidence_records(
            identity=identity,
            records=records,
            limit=limit,
            cursor=cursor,
        )
    except InvalidEvidenceCursor as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except StaleEvidenceCursor as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return EvidenceBundleView(**page)


@router.get(
    "/chains/{chain_id}/evidence/{evidence_id}",
    response_model=EvidenceRecordView,
)
async def get_chain_evidence_record(
    chain_id: str,
    evidence_id: str,
    request: Request,
    snapshot_id: str | None = Header(None, alias="X-NocPro-Snapshot-Id"),
    snapshot_version: str | None = Header(None, alias="X-NocPro-Snapshot-Version"),
    topology_version: str | None = Header(None, alias="X-NocPro-Topology-Version"),
) -> EvidenceRecordView:
    service = workspace(request)
    package = _require_evidence_snapshot_context(
        service,
        chain_id=chain_id,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
    )
    overview = await get_chain_overview_cards(chain_id, request)
    if overview.status != "READY":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=overview.reason or "EVIDENCE_PROJECTION_NOT_READY",
        )
    if topology_version is not None and (topology_version or None) != overview.topology_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="STALE_TOPOLOGY_CONTEXT",
        )
    identity, records = await _current_evidence_records(
        service=service,
        package=package,
        chain_id=chain_id,
        overview=overview,
    )
    if not evidence_id.startswith("ev1_") or len(evidence_id) != 68:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="evidence record not found",
        )
    record = next(
        (item for item in records if item.get("evidence_id") == evidence_id),
        None,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="evidence record not found",
    )
    return EvidenceRecordView(**record)


@router.get(
    "/chains/{chain_id}/recurrent-alarms",
    response_model=RecurrentAlarmHistoryView,
)
async def get_chain_recurrent_alarm_history(
    chain_id: str,
    request: Request,
    snapshot_id: str | None = Header(None, alias="X-NocPro-Snapshot-Id"),
    snapshot_version: str | None = Header(None, alias="X-NocPro-Snapshot-Version"),
) -> RecurrentAlarmHistoryView:
    service = workspace(request)
    package = _require_evidence_snapshot_context(
        service,
        chain_id=chain_id,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
    )
    result = await chain_recurrence_history(
        package,
        chain_id=chain_id,
        repository=service.repository,
    )
    return RecurrentAlarmHistoryView(**result)


@router.get("/chains/{chain_id}")
async def explain_chain(chain_id: str, request: Request):
    service = workspace(request)
    try:
        result = await _run_blocking(service.analyze, chain_id)
        pkg = service.require_package()

        entity_resolutions_by_alarm = {}
        repo = topology_repo(request)
        chain_alarm_ids = list(result.members.keys())
        resolver: AlarmEntityResolver | None = None
        new_resolutions = []

        topo_ref = getattr(getattr(pkg, "snapshot", None), "topology_ref", None) or getattr(pkg, "topology_ref", None)
        profile_id = getattr(topo_ref, "profile_id", None)
        target_topo_ver = getattr(topo_ref, "topology_version", None)
        topo_ver = target_topo_ver
        persisted_by_alarm: dict[str, list[AlarmEntityResolution]] = {}

        if repo is not None and profile_id:
            if not topo_ver:
                active = await repo.get_active_version(profile_id)
                topo_ver = active.topology_version if active is not None else None
            if topo_ver:
                try:
                    persisted = await repo.get_alarm_entity_resolutions(
                        chain_alarm_ids, profile_id, topo_ver
                    )
                    for r in persisted:
                        persisted_by_alarm.setdefault(r.alarm_id, []).append(r)
                except Exception as e:
                    logger.warning("Failed to fetch persisted entity resolutions: %s", e)

        # 1. Use persisted resolutions for alarms already resolved
        for alarm_id in chain_alarm_ids:
            if alarm_id in persisted_by_alarm:
                res_list = persisted_by_alarm[alarm_id]
                observed_host = next(
                    (r.resource_id for r in res_list if r.entity_role == "OBSERVED_HOST" and r.resource_id),
                    None,
                )
                entity_resolutions_by_alarm[alarm_id] = (observed_host, res_list)

        # 2. Only resolve alarms not already in persistence
        missing_alarm_ids = [aid for aid in chain_alarm_ids if aid not in persisted_by_alarm]
        if missing_alarm_ids:
            if repo is not None and profile_id and topo_ver:
                host_mod_map, host_can_map = await repo.get_host_modules_map(
                    profile_id, topology_version=topo_ver
                )
                resolver = AlarmEntityResolver(
                    profile_id=profile_id,
                    topology_version=topo_ver,
                    host_modules_map=host_mod_map,
                    host_canonical_id_map=host_can_map,
                )
            else:
                resolver = AlarmEntityResolver.from_package(
                    pkg,
                    profile_id=profile_id,
                    topology_version=topo_ver,
                )
            for alarm_id in missing_alarm_ids:
                if alarm_id in pkg.alarms:
                    alarm = pkg.alarms[alarm_id]
                    raw_dict = (
                        alarm.raw
                        if hasattr(alarm, "raw") and isinstance(alarm.raw, dict)
                        else {}
                    )
                    raw_content = (
                        raw_dict.get("content")
                        or getattr(alarm, "raw_content", None)
                        or raw_dict.get("addition_info")
                    )
                    observed_host, resolutions = resolver.resolve_alarm(
                        alarm_id,
                        raw_content=raw_content,
                        alarm_name=alarm.alarm_name,
                        device_code=alarm.device_code,
                        node_reference=alarm.node_reference,
                        raw_fields=raw_dict,
                    )
                    entity_resolutions_by_alarm[alarm_id] = (observed_host, resolutions)
                    new_resolutions.extend(resolutions)

        if repo is not None and profile_id and topo_ver and new_resolutions:
            try:
                await repo.save_alarm_entity_resolutions(new_resolutions)
            except Exception as e:
                logger.warning("Failed to persist entity resolutions: %s", e)

        return chain_analysis_view(
            result,
            pkg,
            evidence_availability=service.chain_evidence_availability(result),
            entity_resolutions_by_alarm=entity_resolutions_by_alarm,
        )
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/chains/{chain_id}/evolution", response_model=EvolutionView)
async def explain_evolution(chain_id: str, request: Request) -> EvolutionView:
    try:
        return evolution_view(await workspace(request).evolution(chain_id))
    except Exception as exc:
        raise translate_error(exc) from exc


def _evolution_empty_quality() -> dict[str, Any]:
    return {
        "comparable": False, "reason_codes": ["QUALITY_RECEIPT_UNAVAILABLE"],
        "before_score": None, "after_score": None, "before_stars": None,
        "after_stars": None, "delta": None, "before_receipt_id": None,
        "after_receipt_id": None,
    }


def _evolution_receipt_choices(receipts: list[Any]) -> list[dict[str, str]]:
    return [
        {
            "receipt_id": item.receipt_id,
            "artifact_revision": item.artifact_revision,
            "created_at": item.created_at.isoformat(),
        }
        for item in receipts
    ]


def _evolution_receipt_compatibility_signature(receipt: Any) -> tuple[str, ...] | None:
    """Return only the complete fields that govern direct quality comparison."""
    assessment = getattr(receipt, "assessment", None)
    identity = getattr(receipt, "analysis_identity", None)
    def field(value: Any, name: str) -> Any:
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)

    assessment_status = field(assessment, "status")
    readiness = field(assessment, "readiness")
    score = field(assessment, "score")
    if assessment_status != "EVALUATED" or readiness != "READY":
        return None
    if type(score) not in (int, float) or not 0 <= score <= 1:
        return None
    fields = (
        assessment_status,
        readiness,
        field(assessment, "method"),
        field(assessment, "readiness_policy_version"),
        field(identity, "analysis_config_version"),
        field(identity, "review_config_version"),
        field(identity, "pipeline_version"),
        field(identity, "topology_version"),
    )
    if any(not isinstance(value, str) or not value.strip() for value in fields):
        return None
    return fields


@router.get("/chains/{chain_id}/evolution/changes", response_model=EvolutionChangesView)
async def explain_evolution_changes(
    chain_id: str,
    request: Request,
    parent_snapshot_id: str | None = None,
    parent_snapshot_version: str | None = None,
    parent_chain_id: str | None = None,
    parent_receipt_id: str | None = None,
    child_receipt_id: str | None = None,
) -> EvolutionChangesView:
    service = workspace(request)
    try:
        package = _require_evidence_snapshot_context(
            service,
            chain_id=chain_id,
            snapshot_id=request.headers.get("x-nocpro-snapshot-id"),
            snapshot_version=request.headers.get("x-nocpro-snapshot-version"),
        )
    except SnapshotNotLoaded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if os.getenv("NOCPRO_EVOLUTION_CHANGES_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=503, detail="EVOLUTION_CHANGES_DISABLED")
    repo = service.repository
    if repo is None:
        raise HTTPException(status_code=503, detail="EVOLUTION_REPOSITORY_UNAVAILABLE")

    parent_values = (parent_snapshot_id, parent_snapshot_version, parent_chain_id)
    if any(value is not None for value in parent_values) and not all(
        isinstance(value, str) and value.strip() for value in parent_values
    ):
        raise HTTPException(status_code=422, detail="PARENT_SELECTION_INCOMPLETE")
    if not any(parent_values) and (parent_receipt_id is not None or child_receipt_id is not None):
        raise HTTPException(status_code=422, detail="PARENT_EDGE_REQUIRED_FOR_RECEIPT")
    if parent_receipt_id == "" or child_receipt_id == "":
        raise HTTPException(status_code=422, detail="RECEIPT_SELECTION_INCOMPLETE")

    child = (package.snapshot.snapshot_id, package.snapshot.snapshot_version, chain_id)
    child_view = dict(zip(("snapshot_id", "snapshot_version", "chain_id"), child))

    def ensure_current_package() -> None:
        try:
            current = service.require_package()
        except SnapshotNotLoaded as exc:
            raise HTTPException(status_code=409, detail="STALE_ANALYSIS_CONTEXT") from exc
        if current is not package:
            raise HTTPException(status_code=409, detail="STALE_ANALYSIS_CONTEXT")

    try:
        if not any(parent_values):
            edges, truncated = await repo.list_evolution_predecessors(child=child)
            ensure_current_package()
            choices = [
                {
                    "parent": {
                        "snapshot_id": edge["parent_snapshot_id"],
                        "snapshot_version": edge["parent_snapshot_version"],
                        "chain_id": edge["parent_chain_id"],
                    },
                    "event_type": edge["event_type"],
                    "parent_source_kind": edge["parent_source_kind"],
                    "child_source_kind": edge["child_source_kind"],
                }
                for edge in edges
            ]
            return EvolutionChangesView.model_validate({
                "status": "PARTIAL" if choices else "UNAVAILABLE",
                "reason_codes": ["PARENT_SELECTION_REQUIRED"] if choices else ["SEQUENTIAL_SNAPSHOTS_NOT_AVAILABLE"],
                "parent": None, "child": child_view, "event_type": None,
                "predecessor_choices": choices, "predecessor_choices_truncated": truncated,
                "membership": None, "context_changes": [],
                "quality": _evolution_empty_quality(), "explanations": [],
            })

        parent = (parent_snapshot_id, parent_snapshot_version, parent_chain_id)
        edge = await repo.get_evolution_edge(child=child, parent=parent)
        ensure_current_package()
        if edge is None:
            raise HTTPException(status_code=404, detail="LINEAGE_EDGE_NOT_FOUND")

        async def select_receipt(endpoint: tuple[str, str, str], receipt_id: str | None):
            if receipt_id is not None:
                receipt = await repo.quality_evaluation_receipt(receipt_id)
                ensure_current_package()
                if receipt is None or not isinstance(receipt.analysis_identity, dict) or any(
                    receipt.analysis_identity.get(name) != value
                    for name, value in zip(("snapshot_id", "snapshot_version", "chain_id"), endpoint)
                ):
                    raise HTTPException(status_code=422, detail="RECEIPT_ENDPOINT_MISMATCH")
                return receipt, [], False, False
            candidates, candidate_truncated = await repo.list_evolution_endpoint_receipts(endpoint=endpoint)
            ensure_current_package()
            if len(candidates) == 1 and not candidate_truncated:
                if _evolution_receipt_compatibility_signature(candidates[0]) is not None:
                    return candidates[0], [], False, False
                return None, _evolution_receipt_choices(candidates), False, True
            ambiguous = len(candidates) > 1 or candidate_truncated
            if len(candidates) > 1 and not candidate_truncated:
                signatures = [_evolution_receipt_compatibility_signature(item) for item in candidates]
                if signatures[0] is not None and all(value == signatures[0] for value in signatures[1:]):
                    # The repository orders newest first by (created_at, receipt_id).
                    return candidates[0], [], False, False
            return None, _evolution_receipt_choices(candidates) if ambiguous else [], candidate_truncated, ambiguous

        parent_receipt, parent_choices, parent_truncated, parent_ambiguous = await select_receipt(parent, parent_receipt_id)
        child_receipt, child_choices, child_truncated, child_ambiguous = await select_receipt(child, child_receipt_id)
        summary = await repo.evolution_membership_summary(parent=parent, child=child)
        ensure_current_package()
        facts = compare_evolution_facts(
            parent_members=None, child_members=None,
            parent_receipt=parent_receipt, child_receipt=child_receipt,
            lineage_edge=edge, membership_summary=summary,
        )
        if parent_ambiguous or child_ambiguous:
            facts["reason_codes"].append("RECEIPT_SELECTION_REQUIRED")
            if facts["status"] == "AVAILABLE":
                facts["status"] = "PARTIAL"
        facts.update({
            "parent_source_kind": edge["parent_source_kind"],
            "child_source_kind": edge["child_source_kind"],
            "parent_receipt_choices": parent_choices,
            "child_receipt_choices": child_choices,
            "parent_receipt_choices_truncated": parent_truncated,
            "child_receipt_choices_truncated": child_truncated,
        })
        return EvolutionChangesView.model_validate(facts)
    except SQLAlchemyError as exc:
        logger.exception("Evolution changes database read failed")
        raise HTTPException(status_code=503, detail="EVOLUTION_DATABASE_UNAVAILABLE") from exc


@router.get("/chains/{chain_id}/pairs/{alarm_a}/{alarm_b}", response_model=PairWhyView)
async def explain_pair(
    chain_id: str, alarm_a: str, alarm_b: str, request: Request
) -> PairWhyView:
    service = workspace(request)
    try:
        package = service.require_package()
        requested_snapshot_id = request.headers.get("x-nocpro-snapshot-id")
        requested_snapshot_version = request.headers.get("x-nocpro-snapshot-version")
        if requested_snapshot_id or requested_snapshot_version:
            _require_evidence_snapshot_context(
                service,
                chain_id=chain_id,
                snapshot_id=requested_snapshot_id,
                snapshot_version=requested_snapshot_version,
            )
        values = await _run_blocking(service.pair_why, chain_id, alarm_a, alarm_b)
        if service.require_package() is not package:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="STALE_ANALYSIS_CONTEXT",
            )
        graybox = adapt_graybox_metadata(package, chain_id)
    except Exception as exc:
        raise translate_error(exc) from exc
    fact = graybox.pair_fact(alarm_a, alarm_b)
    evidence_views = [pair_evidence_view(value) for value in values]
    evidence_records: list[EvidenceRecordView] = []
    if requested_snapshot_id and requested_snapshot_version:
        try:
            overview = await get_chain_overview_cards(chain_id, request)
            if overview.status == "READY" and overview.analysis_identity is not None:
                adapted = analysis_identity_from_projection({
                    "analysis_identity": overview.analysis_identity.model_dump(mode="json")
                })
                if adapted.available and adapted.identity is not None:
                    pair_records = build_evidence_records(
                        identity=adapted.identity,
                        overview_projection=None,
                        pair_evidence=[{
                            "alarm_id_a": alarm_a,
                            "alarm_id_b": alarm_b,
                            "evidence": [value.model_dump(mode="json") for value in evidence_views],
                        }],
                        audit_artifact=None,
                        review_result=None,
                    )
                    evidence_records = [
                        EvidenceRecordView(**record)
                        for record in pair_records
                        if record.get("kind") == "TOPOLOGY_PATH"
                        and str(record.get("summary") or "").startswith("Pair WHY ")
                    ]
            if service.require_package() is not package:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="STALE_ANALYSIS_CONTEXT",
                )
        except Exception as exc:
            raise translate_error(exc) from exc
    return PairWhyView(
        chain_id=chain_id,
        alarm_id_a=alarm_a,
        alarm_id_b=alarm_b,
        evidence=evidence_views,
        evidence_records=evidence_records,
        system_fact=SystemPairFactView(
            status=graybox.pair_status(alarm_a, alarm_b),
            attribute_ref=fact.attribute_ref if fact else None,
            raw_score=fact.raw_score if fact else None,
            semantic=fact.system_semantic if fact else None,
        ),
    )


@router.post(
    "/chains/{chain_id}/deep-dive",
    response_model=JobSubmissionView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_deep_dive(
    chain_id: str, request: Request
) -> JobSubmissionView:
    try:
        result = workspace(request).submit_deep_dive(chain_id)
    except Exception as exc:
        raise translate_error(exc) from exc
    return JobSubmissionView(
        job_id=result.job_id,
        cache_hit=result.cache_hit,
        deduplicated=result.deduplicated,
    )


@router.get(
    "/chains/{chain_id}/audit-visualization",
    response_model=AuditVisualizationArtifactView,
)
async def get_audit_visualization(
    chain_id: str, request: Request
) -> AuditVisualizationArtifactView:
    try:
        lookup = await workspace(request).latest_audit_visualization(chain_id)
        return audit_visualization_artifact_view(lookup)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/jobs/{job_id}", response_model=JobView)
async def get_job(job_id: str, request: Request) -> JobView:
    try:
        service = workspace(request)
        job = await service.deep_dive_job(job_id)
        await service.flush_deep_dive_persistence()
        await service.flush_audit_persistence()
        return job_view(job)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/chains/{chain_id}/deep-dive", response_model=JobView | None)
async def get_latest_deep_dive(
    chain_id: str, request: Request
) -> JobView | None:
    try:
        service = workspace(request)
        result = await service.latest_deep_dive(chain_id)
        await service.flush_deep_dive_persistence()
        await service.flush_audit_persistence()
        return (
            job_view(result, topology_version=_active_topology_version(service))
            if result is not None
            else None
        )
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post(
    "/chains/{chain_id}/review",
    response_model=JobSubmissionView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_review(
    chain_id: str, request: Request
) -> JobSubmissionView:
    try:
        result = await workspace(request).submit_review(chain_id)
    except Exception as exc:
        raise translate_error(exc) from exc
    return JobSubmissionView(
        job_id=result.job_id,
        cache_hit=result.cache_hit,
        deduplicated=result.deduplicated,
    )


@router.get("/review-jobs/{job_id}", response_model=CounterfactualJobView)
async def get_review_job(
    job_id: str, request: Request, lang: str = Query("vi")
) -> CounterfactualJobView:
    try:
        service = workspace(request)
        # The manager sets a terminal state and enqueues its persistence future
        # under one lock.  Read the state first so a terminal response cannot
        # flush an older future list and race a subsequent API restart.
        job = None
        try:
            job = service.review_jobs.get(job_id)
        except KeyError:
            if service.repository is not None:
                job = await service.repository.counterfactual_job(job_id)
            if job is None:
                await service.flush_review_persistence()
                raise
        await service.flush_review_persistence()
        pkg = None
        try:
            pkg = service.current_package()
        except Exception:
            pass
        return counterfactual_job_view(
            job, package=pkg, language=lang, review_learning=service.review_learning
        )
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/chains/{chain_id}/review", response_model=CounterfactualJobView)
async def get_latest_review(
    chain_id: str, request: Request, lang: str = Query("vi")
) -> CounterfactualJobView:
    try:
        service = workspace(request)
        result = await service.latest_review(chain_id)
        await service.flush_review_persistence()
        if result is None:
            raise KeyError(f"no compatible Counterfactual review for {chain_id!r}")
        pkg = None
        try:
            pkg = service.current_package()
        except Exception:
            pass
        view = counterfactual_job_view(
            result, package=pkg, language=lang, review_learning=service.review_learning
        )
        if os.environ.get("AI_API_KEY") or os.environ.get("AI_BASE_URL"):
            if isinstance(view.result, dict) and "evaluated_candidates" in view.result:
                from tier2.counterfactual.comparative_explainer import (
                    ComparativeExplanation,
                    enrich_comparative_explanation_with_ai,
                )
                eligible_candidates = []
                for cand in view.result.get("evaluated_candidates", []):
                    if (
                        isinstance(cand, dict)
                        and cand.get("hard_gate_result", {}).get("status") == "PASSED"
                        and cand.get("comparative_explanation")
                        and not cand["comparative_explanation"].get("ai_narrative")
                    ):
                        eligible_candidates.append(cand)
                    if len(eligible_candidates) >= MAX_REVIEW_AI_ENRICHMENTS:
                        break

                enrichment_semaphore = asyncio.Semaphore(MAX_REVIEW_AI_CONCURRENCY)

                async def enrich_candidate(cand: dict[str, Any]) -> None:
                    c_exp = cand["comparative_explanation"]
                    obj_exp = ComparativeExplanation(
                            operation=c_exp.get("operation", "UNKNOWN"),
                            summary_action=c_exp.get("summary_action", ""),
                            why_better=c_exp.get("why_better", ""),
                            comparison_points=c_exp.get("comparison_points", []),
                            delta_highlights=c_exp.get("delta_highlights", []),
                            language=c_exp.get("language", lang),
                            context_facts=c_exp.get("context_facts"),
                        )
                    async with enrichment_semaphore:
                        enriched_exp = await enrich_comparative_explanation_with_ai(
                            obj_exp,
                            candidate_id=cand.get("candidate_id", ""),
                            operation=cand.get("operation", "UNKNOWN"),
                            before_metrics=cand.get("before_metrics"),
                            after_metrics=cand.get("after_metrics"),
                            package=pkg,
                            language=lang,
                            target_chain_id=cand.get("target_chain_id"),
                            source_chain_id=cand.get("source_chain_id"),
                            member_ids=cand.get("member_ids"),
                            structural_facts=cand.get("structural_facts"),
                        )
                    cand["comparative_explanation"] = enriched_exp.as_dict()

                await asyncio.gather(*(enrich_candidate(cand) for cand in eligible_candidates))
        return view
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/review-jobs/{job_id}/compare-proposals-clarity",
    response_model=ProposalClarityComparisonView,
)
async def get_review_job_proposals_clarity(
    job_id: str, request: Request, lang: str = Query("vi")
) -> ProposalClarityComparisonView:
    try:
        service = workspace(request)
        job = None
        try:
            job = service.review_jobs.get(job_id)
        except KeyError:
            if service.repository is not None:
                job = await service.repository.counterfactual_job(job_id)
            if job is None:
                await service.flush_review_persistence()
                raise
        await service.flush_review_persistence()
        pkg = None
        try:
            pkg = service.current_package()
        except Exception:
            pass
        view = counterfactual_job_view(
            job, package=pkg, language=lang, review_learning=service.review_learning
        )
        res_dict = view.result if isinstance(view.result, dict) else {}
        candidates_raw = res_dict.get("evaluated_candidates") or res_dict.get("candidates") or []
        if not candidates_raw and isinstance(job.result, dict):
            from tier2.counterfactual.public_contract import public_review_result
            pub = public_review_result(job.result, package=pkg, language=lang)
            candidates_raw = pub.get("evaluated_candidates") or pub.get("candidates") or []
        comparison_res = compare_proposal_explanations(candidates_raw, package=pkg)

        ai_model = "DETERMINISTIC_EVIDENCE"
        has_eligible_proposal = bool(
            comparison_res.proposals and comparison_res.top_proposal_id
        )
        ai_provider_status = "NOT_CONFIGURED" if has_eligible_proposal else "NOT_APPLIED"
        overall_rationale = comparison_res.overall_recommendation_rationale
        try:
            from .grounded_llm import is_provider_configured, render_grounded
            if has_eligible_proposal and is_provider_configured() and overall_rationale:
                rendered = await _run_grounded_provider(
                    render_grounded,
                    draft=overall_rationale,
                    facts={
                        "top_proposal": comparison_res.top_proposal_operation,
                        "top_proposal_id": comparison_res.top_proposal_id,
                        "candidates_count": len(comparison_res.proposals),
                    },
                    fact_refs=[job.chain_id, comparison_res.top_proposal_operation or ""],
                    purpose="ADVISOR",
                    requested_language=lang,
                    preserve_provider_output=True,
                )
                ai_model = rendered.model
                ai_provider_status = rendered.provider_status
                if rendered.used_provider and rendered.message:
                    overall_rationale = rendered.message
        except Exception as exc:
            logger.warning("Optional AI render for proposal clarity skipped: %s", exc)

        return ProposalClarityComparisonView(
            job_id=job_id,
            proposals=[asdict(p) for p in comparison_res.proposals],
            top_proposal_id=comparison_res.top_proposal_id,
            top_proposal_operation=comparison_res.top_proposal_operation,
            head_to_head_comparisons=comparison_res.head_to_head_comparisons,
            overall_recommendation_rationale=overall_rationale,
            ai_model=ai_model,
            ai_provider_status=ai_provider_status,
        )
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/review-reasons",
    response_model=ReasonPolicyView,
)
async def get_review_reasons() -> ReasonPolicyView:
    try:
        policy = load_reason_policy()
        return ReasonPolicyView.model_validate(policy)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post(
    "/review-jobs/{job_id}/display-events",
    response_model=CandidateDisplayEventBatchView,
    status_code=status.HTTP_201_CREATED,
)
async def record_display_events(
    job_id: str,
    submission: CandidateDisplayEventBatchSubmission,
    request: Request,
    principal: ReviewerPrincipal = Depends(get_reviewer_principal_async),
) -> CandidateDisplayEventBatchView:
    try:
        service = workspace(request)
        count = await service.record_candidate_display_events(
            job_id, [e.model_dump() for e in submission.events], principal=principal
        )
        return CandidateDisplayEventBatchView(recorded_events=count)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post(
    "/review-jobs/{job_id}/feedback",
    response_model=OperatorFeedbackView,
    status_code=status.HTTP_201_CREATED,
)
async def submit_operator_feedback(
    job_id: str,
    submission: OperatorFeedbackSubmission,
    request: Request,
    principal: ReviewerPrincipal = Depends(get_reviewer_principal_async),
) -> OperatorFeedbackView:
    try:
        service = workspace(request)
        result = await service.record_operator_feedback(
            job_id, submission.model_dump(), principal=principal
        )
        return operator_feedback_view(result)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post(
    "/review-jobs/{job_id}/feedback/{feedback_id}/supersede",
    response_model=OperatorFeedbackView,
    status_code=status.HTTP_201_CREATED,
)
async def supersede_operator_feedback(
    job_id: str,
    feedback_id: str,
    submission: OperatorFeedbackSubmission,
    request: Request,
    principal: ReviewerPrincipal = Depends(get_reviewer_principal_async),
) -> OperatorFeedbackView:
    try:
        service = workspace(request)
        result = await service.supersede_operator_feedback(
            job_id, feedback_id, submission.model_dump(), principal=principal
        )
        return operator_feedback_view(result)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post(
    "/review-jobs/{job_id}/feedback/{feedback_id}/retract",
    status_code=status.HTTP_200_OK,
)
async def retract_operator_feedback(
    job_id: str,
    feedback_id: str,
    submission: RetractionSubmission,
    request: Request,
    principal: ReviewerPrincipal = Depends(get_reviewer_principal_async),
) -> dict[str, Any]:
    try:
        service = workspace(request)
        await service.retract_operator_feedback(
            job_id, feedback_id, principal=principal, reason=submission.reason
        )
        return {"status": "RETRACTED", "feedback_id": feedback_id}
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/review-jobs/{job_id}/feedback",
    response_model=list[OperatorFeedbackView],
)
async def get_job_operator_feedback(
    job_id: str,
    request: Request,
    principal: ReviewerPrincipal = Depends(get_reviewer_principal_async),
) -> list[OperatorFeedbackView]:
    try:
        service = workspace(request)
        feedbacks = await service.list_operator_feedback(job_id=job_id, principal=principal)
        return [operator_feedback_view(f) for f in feedbacks]
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/chains/{chain_id}/feedback",
    response_model=list[OperatorFeedbackView],
)
async def get_chain_operator_feedback(
    chain_id: str,
    request: Request,
    snapshot_id: str = Query(..., min_length=1),
    snapshot_version: str = Query(..., min_length=1),
    principal: ReviewerPrincipal = Depends(get_reviewer_principal_async),
) -> list[OperatorFeedbackView]:
    try:
        service = workspace(request)
        feedbacks = await service.list_operator_feedback(
            chain_id=chain_id,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            principal=principal,
        )
        return [operator_feedback_view(f) for f in feedbacks]
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/review-feedback/history",
    response_model=ReviewFeedbackHistoryPage,
)
async def get_review_feedback_history(
    request: Request,
    snapshot_id: str = Query(..., min_length=1),
    snapshot_version: str = Query(..., min_length=1),
    search: str | None = Query(None, max_length=160),
    decision: str | None = Query(None, max_length=32),
    lifecycle_status: LifecycleStatus | None = Query(None),
    reviewer: str | None = Query(None, max_length=255),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    principal: ReviewerPrincipal = Depends(get_reviewer_principal_async),
) -> ReviewFeedbackHistoryPage:
    try:
        return await load_review_feedback_history(
            workspace(request),
            principal,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            search=search,
            decision=decision,
            lifecycle_status=lifecycle_status,
            reviewer=reviewer,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/review-jobs/{job_id}/candidates/{candidate_id}/similar-cases",
)
async def get_candidate_similar_cases(
    job_id: str,
    candidate_id: str,
    request: Request,
    top_k: int = Query(5, ge=1, le=20),
    min_common_blocks: int = Query(2, ge=1, le=5),
    principal: ReviewerPrincipal = Depends(get_reviewer_principal_async),
) -> dict[str, Any]:
    try:
        service = workspace(request)
        res = await service.find_similar_cases_for_candidate(
            job_id,
            candidate_id,
            principal=principal,
            top_k=top_k,
            min_common_blocks=min_common_blocks,
        )
        if isinstance(res, SimilarCaseRetrievalResult):
            return {
                "retrieval_status": res.retrieval_status,
                "min_similarity": res.min_similarity,
                "reason": res.reason,
                "common_block_count": res.common_block_count,
                "required_common_block_count": res.required_common_block_count,
                "disclaimer": res.disclaimer,
                "cross_incident_cases": [
                    {
                        "case_id": m.case_id,
                        "review_id": m.review_id,
                        "candidate_id": m.candidate_id,
                        "decision": m.decision,
                        "truth_tier": m.truth_tier,
                        "similarity_score": m.similarity_score,
                        "common_block_count": m.common_block_count,
                        "block_scores": m.block_scores,
                        "lineage_component_id": m.lineage_component_id,
                        "disclaimer": m.disclaimer,
                    }
                    for m in res.cross_incident_cases
                ],
                "same_lineage_history": [
                    {
                        "case_id": m.case_id,
                        "review_id": m.review_id,
                        "candidate_id": m.candidate_id,
                        "decision": m.decision,
                        "truth_tier": m.truth_tier,
                        "similarity_score": m.similarity_score,
                        "common_block_count": m.common_block_count,
                        "block_scores": m.block_scores,
                        "lineage_component_id": m.lineage_component_id,
                        "disclaimer": m.disclaimer,
                    }
                    for m in res.same_lineage_history
                ],
            }
        elif isinstance(res, list):
            return {
                "retrieval_status": "AVAILABLE",
                "min_similarity": 0.5,
                "reason": None,
                "common_block_count": 5,
                "required_common_block_count": 3,
                "disclaimer": "Historical reference only — not probability or automated recommendation. Intended solely as peer context for human decision-making.",
                "cross_incident_cases": [
                    {
                        "case_id": getattr(m, "case_id", None) or m.get("case_id"),
                        "review_id": getattr(m, "review_id", None) or m.get("review_id"),
                        "candidate_id": getattr(m, "candidate_id", None) or m.get("candidate_id"),
                        "decision": getattr(m, "decision", None) or m.get("decision"),
                        "truth_tier": getattr(m, "truth_tier", None) or m.get("truth_tier"),
                        "similarity_score": getattr(m, "similarity_score", None) or m.get("similarity_score"),
                        "common_block_count": getattr(m, "common_block_count", None) or m.get("common_block_count"),
                        "block_scores": getattr(m, "block_scores", None) or m.get("block_scores"),
                        "lineage_component_id": getattr(m, "lineage_component_id", None) or m.get("lineage_component_id"),
                        "disclaimer": getattr(m, "disclaimer", "Historical reference only — not probability or automated recommendation."),
                    }
                    for m in res
                ],
                "same_lineage_history": [],
            }
        return dict(res)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/chains/{chain_id}/cohesion-narrative",
    response_model=CohesionNarrativeView,
)
@router.post(
    "/chains/{chain_id}/cohesion-narrative",
    response_model=CohesionNarrativeView,
)
async def get_chain_cohesion_narrative(
    chain_id: str,
    request: Request,
    lang: str = Query("vi"),
    force_refresh: bool = Query(False),
) -> CohesionNarrativeView:
    try:
        service = workspace(request)
        active_id = service.active_identity() if hasattr(service, "active_identity") else None
        snapshot_id = active_id[0] if active_id else "default_snapshot"
        snapshot_version = active_id[1] if active_id else "v1"
        package = service.current_package()
        if package is not None and await _active_unpinned_topology_is_stale(service, request, package):
            return CohesionNarrativeView(
                chain_id=chain_id,
                narrative="",
                model="DETERMINISTIC_EVIDENCE",
                provider_status="STALE_TOPOLOGY",
                context={"reason": "Snapshot đang mở dùng topology cũ; mở lại snapshot để cập nhật."},
            )

        audit_artifact = None
        audit_error_reason: str | None = None
        try:
            audit_lookup = await service.latest_audit_visualization(chain_id)
            if audit_lookup and audit_lookup.audit_artifact:
                audit_artifact = audit_lookup.audit_artifact
        except KeyError:
            # Chain unknown or not found
            raise
        except Exception:
            logger.exception("Failed to retrieve latest audit visualization for chain %s", chain_id)
            audit_error_reason = "AUDIT_LOOKUP_FAILED"

        deep_dive_analysis = None
        deep_dive_job = None
        try:
            deep_dive_job = await service.latest_deep_dive(chain_id)
            if (
                deep_dive_job
                and getattr(deep_dive_job, "status", None)
                and getattr(deep_dive_job.status, "value", str(deep_dive_job.status)) == "SUCCEEDED"
            ):
                from .cohesion_advisor import hydrate_persisted_deep_dive

                deep_dive_analysis = hydrate_persisted_deep_dive(deep_dive_job.result)
                if audit_artifact is None and getattr(deep_dive_job, "audit_artifact", None):
                    audit_artifact = deep_dive_job.audit_artifact
        except Exception:
            logger.debug("Failed to retrieve latest deep dive job for chain %s", chain_id, exc_info=True)

        review_result = None
        latest_rev = None
        try:
            package = service.current_package()
            latest_rev = await service.latest_review(chain_id)
            if latest_rev and latest_rev.result:
                from tier2.counterfactual.public_contract import public_review_result
                review_result = (
                    public_review_result(latest_rev.result, package=package, language=lang)
                    if hasattr(latest_rev.result, "recommendations")
                    else latest_rev.result
                )
        except KeyError:
            raise
        except Exception:
            logger.exception("Failed to retrieve latest review for chain %s", chain_id)

        persisted_quality_assessment = None
        if service.repository is not None:
            try:
                quality_record = await service.repository.chain_quality_assessment(
                    snapshot_id=snapshot_id,
                    snapshot_version=snapshot_version,
                    chain_id=chain_id,
                )
                current_package = service.require_package()
                if quality_record is not None and isinstance(quality_record.payload, dict) and _quality_assessment_is_current(
                    quality_record.payload,
                    canonical_row=quality_record,
                    expected_config_version=getattr(service.config, "config_version", None),
                    expected_review_config_version=(
                        service.config.counterfactual.config_version
                        if service.config.counterfactual is not None
                        else "UNAVAILABLE"
                    ),
                    expected_topology_version=_topology_version(current_package),
                    topology_version_known=snapshot_topology_profile(
                        snapshot_id,
                        getattr(getattr(current_package.snapshot, "topology_ref", None), "profile_id", None),
                    ) is not None,
                    snapshot_id=snapshot_id,
                    snapshot_version=snapshot_version,
                ):
                    persisted_quality_assessment = quality_record.payload
            except Exception:
                logger.debug(
                    "Failed to retrieve persisted quality for chain %s",
                    chain_id,
                    exc_info=True,
                )

        evidence_review_result = None
        if persisted_quality_assessment is not None and latest_rev is not None:
            overview_projection = persisted_quality_assessment.get("overview_projection")
            expected_review_identity = (
                overview_projection.get("review_analysis_identity")
                if isinstance(overview_projection, dict)
                else None
            )
            expected_review_revision = (
                overview_projection.get("review_artifact_revision")
                if isinstance(overview_projection, dict)
                else None
            )
            raw_review_identity = getattr(latest_rev, "identity", None)
            raw_review_identity = (
                asdict(raw_review_identity)
                if raw_review_identity is not None and hasattr(raw_review_identity, "__dataclass_fields__")
                else raw_review_identity
            )
            if isinstance(raw_review_identity, dict):
                adapted_review = analysis_identity_from_review(
                    raw_review_identity,
                    pipeline_version=str(raw_review_identity.get("engine_version") or ""),
                    input_fingerprint=str(
                        raw_review_identity.get("tier1b_artifact_fingerprint") or ""
                    ),
                )
                review_status = str(
                    getattr(getattr(latest_rev, "status", None), "value", getattr(latest_rev, "status", ""))
                    or ""
                ).upper()
                expected_job_id = persisted_quality_assessment.get("counterfactual_job_id")
                expected_review_fingerprint = (
                    expected_review_revision.get("fingerprint")
                    if isinstance(expected_review_revision, dict)
                    else None
                )
                if (
                    adapted_review.available
                    and adapted_review.identity is not None
                    and adapted_review.identity.to_payload() == expected_review_identity
                    and getattr(latest_rev, "job_id", None) == expected_job_id
                    and getattr(latest_rev, "cache_fingerprint", None) == expected_review_fingerprint
                    and review_status == "SUCCEEDED"
                    and isinstance(review_result, dict)
                ):
                    evidence_review_result = {
                        "job_id": latest_rev.job_id,
                        "status": review_status,
                        "analysis_identity": adapted_review.identity.to_payload(),
                        "result": review_result,
                    }
                    expected_audit_fingerprint = raw_review_identity.get(
                        "structural_audit_artifact_fingerprint"
                    )
                    if (
                        audit_artifact is not None
                        and expected_audit_fingerprint
                        != getattr(audit_artifact, "artifact_fingerprint", None)
                    ):
                        audit_artifact = None

        input_fingerprint = _cohesion_input_fingerprint(
            service,
            audit_artifact=audit_artifact,
            deep_dive_job=deep_dive_job,
            review_job=latest_rev,
        )

        # Cache rows created under a different config, audit, deep-dive, or
        # review identity are deliberately misses.  Legacy rows have the
        # migration marker and cannot satisfy this predicate.
        cached_row = None
        if service.repository is not None:
            try:
                async with service.repository.sessions() as session:
                    cache_stmt = select(CohesionNarrativeCache).where(
                        CohesionNarrativeCache.snapshot_id == snapshot_id,
                        CohesionNarrativeCache.snapshot_version == snapshot_version,
                        CohesionNarrativeCache.chain_id == chain_id,
                        CohesionNarrativeCache.language == lang,
                        CohesionNarrativeCache.input_fingerprint == input_fingerprint,
                    )
                    cached_row = (await session.scalars(cache_stmt)).first()
                    # Do not resurrect legacy deterministic fallback prose from
                    # the narrative cache. Only a non-empty provider result may
                    # short-circuit the current render; grounding warnings are
                    # intentionally cacheable because they expose the raw model
                    # output with its diagnostic status.
                    cached_narrative = str(getattr(cached_row, "narrative", "") or "").strip()
                    cached_is_legacy_fallback = cached_narrative.startswith(
                        (
                            "Chưa tạo được nhận định AI đáp ứng kiểm tra grounding.",
                            "No AI investigation insight passed grounding validation.",
                        )
                    )
                    cached_is_provider_output = bool(
                        cached_row is not None
                        and cached_narrative
                        and str(getattr(cached_row, "model", "") or "")
                        and getattr(cached_row, "model", None) != "DETERMINISTIC_EVIDENCE"
                        and not cached_is_legacy_fallback
                    )
                    if cached_row is not None and cached_is_provider_output and not force_refresh:
                        return CohesionNarrativeView(
                            chain_id=cached_row.chain_id,
                            narrative=cached_row.narrative,
                            model=cached_row.model,
                            provider_status=cached_row.provider_status,
                            context=cached_row.context,
                        )
            except Exception:
                logger.debug("Cohesion narrative DB cache lookup failed", exc_info=True)

        from .cohesion_advisor import generate_cohesion_narrative
        result = await _run_grounded_provider(
            generate_cohesion_narrative,
            service=service,
            chain_id=chain_id,
            audit_artifact=audit_artifact,
            review_result=review_result,
            audit_error_reason=audit_error_reason,
            deep_dive_analysis=deep_dive_analysis,
            persisted_quality_assessment=persisted_quality_assessment,
            evidence_review_result=evidence_review_result,
            language=lang,
        )

        has_p2 = (audit_artifact is not None) or (deep_dive_analysis is not None)
        if isinstance(result.context, dict):
            result.context["has_p2"] = has_p2

        if _should_preserve_cached_cohesion(cached_row, result, input_fingerprint):
            return CohesionNarrativeView(
                chain_id=cached_row.chain_id,
                narrative=cached_row.narrative,
                model=cached_row.model,
                provider_status=cached_row.provider_status,
                context=cached_row.context,
            )

        # Never persist an explicitly unvalidated dev probe.  Otherwise a later
        # normal request could serve raw provider prose as if it were grounded.
        if service.repository is not None and result.provider_status != "GROUNDING_BYPASS":
            try:
                async with service.repository.sessions() as session:
                    cache_record = CohesionNarrativeCache(
                        snapshot_id=snapshot_id,
                        snapshot_version=snapshot_version,
                        chain_id=chain_id,
                        language=lang,
                        input_fingerprint=input_fingerprint,
                        has_p2=has_p2,
                        narrative=result.narrative,
                        analytical_findings=result.context.get("analytical_findings", []) if isinstance(result.context, dict) else [],
                        context=result.context if isinstance(result.context, dict) else {},
                        model=result.model,
                        provider_status=result.provider_status,
                    )
                    await session.merge(cache_record)
                    await session.commit()
            except Exception:
                logger.debug("Failed to persist cohesion narrative to DB cache", exc_info=True)

        return CohesionNarrativeView(
            chain_id=result.chain_id,
            narrative=result.narrative,
            model=result.model,
            provider_status=result.provider_status,
            context=result.context,
        )
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post(
    "/chains/{chain_id}/optimize-explain-threshold",
    response_model=ThresholdExplainOptimizationView,
)
async def post_optimize_explain_threshold(
    chain_id: str, request: Request
) -> ThresholdExplainOptimizationView:
    try:
        service = workspace(request)
        opt_data = find_clearest_explain_threshold(chain_id, service)
        return ThresholdExplainOptimizationView(**opt_data)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post("/chains/{chain_id}/apply-explain-threshold")
async def post_apply_explain_threshold(
    chain_id: str,
    payload: ApplyThresholdInput,
    request: Request,
) -> dict[str, Any]:
    try:
        service = workspace(request)
        return apply_explain_threshold(chain_id, service, payload.parameters)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post("/assistant/query", response_model=AssistantResponseView)
async def query_assistant(
    request_body: AssistantQueryInput, request: Request
) -> AssistantResponseView:
    """Read-only Assistant; the optional LLM can render text but not actions."""
    try:
        from .assistant import answer_query, render_answer

        context = request_body.context.model_dump()
        ws = workspace(request)
        query_text = request_body.query
        deterministic = await answer_query(
            ws,
            query_text,
            context,
            history=[item.model_dump() for item in request_body.history],
            provider_runner=_run_grounded_provider,
        )
        result = await _run_grounded_provider(
            render_answer,
            context=context,
            deterministic=deterministic,
        )
        return AssistantResponseView(
            contract_version="nocpro-assistant-v1",
            **result,
        )
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/config", response_model=ConfigView)
async def get_config(request: Request) -> ConfigView:
    try:
        data = workspace(request).get_active_parameters()
        return ConfigView(**data)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post("/config", response_model=ConfigView)
async def update_config(payload: ConfigUpdateInput, request: Request) -> ConfigView:
    try:
        data = workspace(request).update_parameters(payload.parameters)
        return ConfigView(**data)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post("/config/reset", response_model=ConfigView)
async def reset_config(request: Request) -> ConfigView:
    try:
        data = workspace(request).reset_parameters()
        return ConfigView(**data)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post("/config/calibrate", status_code=204)
async def calibrate_config(request: Request) -> None:
    try:
        await workspace(request).calibrate_from_database()
    except Exception as exc:
        raise translate_error(exc) from exc


def topology_repo(request: Request):
    return getattr(request.app.state, "topology_repository", None)


@router.get("/topology/profiles")
async def get_topology_profiles(request: Request) -> dict[str, Any]:
    repo = topology_repo(request)
    if repo is not None:
        profiles = await repo.list_profiles()
        return {"status": "AVAILABLE", "profiles": profiles}
    return {"status": "AVAILABLE", "profiles": ["ALARM_ONLY"]}


@router.get("/topology/projection")
async def get_topology_projection(
    request: Request,
    profile_id: str | None = None,
    profile: str | None = None,
    root_id: str | None = None,
    max_depth: int = Query(default=3, ge=1, le=10),
    max_children: int = Query(default=50, ge=1, le=200),
    version: str | None = None,
) -> dict[str, Any]:
    selected_profile = profile_id or profile or "ALARM_ONLY"
    repo = topology_repo(request)
    if repo is not None:
        return await repo.get_projection(
            selected_profile,
            root_id=root_id,
            max_depth=max_depth,
            max_children=max_children,
            topology_version=version,
        )
    return {
        "status": "UNAVAILABLE",
        "reason": "TOPOLOGY_PERSISTENCE_NOT_INITIALIZED",
        "profile": selected_profile,
        "dataset_profile": selected_profile,
        "topology_kind": "UNAVAILABLE",
        "topology": {"availability": "UNAVAILABLE"},
    }


@router.get("/topology/search")
async def get_topology_search(
    request: Request,
    profile_id: str | None = None,
    profile: str | None = None,
    q: str = "",
    query: str | None = None,
    version: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    selected_profile = profile_id or profile or "ALARM_ONLY"
    search_query = query if query is not None else q
    repo = topology_repo(request)
    if repo is not None:
        return await repo.search_nodes(
            selected_profile,
            search_query,
            topology_version=version,
            limit=limit,
        )
    return {
        "status": "UNAVAILABLE",
        "reason": "TOPOLOGY_PERSISTENCE_NOT_INITIALIZED",
        "dataset_profile": selected_profile,
        "results": [],
    }


@router.get("/topology/resolve")
async def get_topology_resolve(
    request: Request,
    profile_id: str | None = None,
    profile: str | None = None,
    identifier: str = "",
    version: str | None = None,
) -> dict[str, Any]:
    selected_profile = profile_id or profile or "ALARM_ONLY"
    repo = topology_repo(request)
    if repo is not None:
        return await repo.resolve_identifier(
            selected_profile,
            identifier,
            topology_version=version,
        )
    return {
        "status": "UNAVAILABLE",
        "reason": "TOPOLOGY_PERSISTENCE_NOT_INITIALIZED",
        "dataset_profile": selected_profile,
        "identifier": identifier,
        "resource_id": None,
        "mapping_status": "UNMAPPED",
        "source_field": None,
        "navigation_eligible": False,
        "dependency_semantics": "UNAVAILABLE",
    }


@router.get("/topology/subgraph")
async def get_topology_subgraph(
    request: Request,
    profile_id: str | None = None,
    profile: str | None = None,
    seeds: str = "",
    hops: int = Query(default=2, ge=1, le=4),
    limit: int = Query(default=150, ge=1, le=500),
    version: str | None = None,
) -> dict[str, Any]:
    selected_profile = profile_id or profile or "ALARM_ONLY"
    repo = topology_repo(request)
    seed_list = [s.strip() for s in seeds.split(",") if s.strip()]
    if repo is not None:
        return await repo.get_subgraph(
            selected_profile,
            seeds=seed_list,
            max_hops=hops,
            max_nodes=limit,
            topology_version=version,
        )
    return {
        "status": "UNAVAILABLE",
        "reason": "TOPOLOGY_PERSISTENCE_NOT_INITIALIZED",
        "profile_id": selected_profile,
        "nodes": [],
        "edges": [],
        "requested_seed_count": len(set(seed_list)),
        "resolved_seed_count": 0,
        "retained_seed_count": 0,
        "dropped_seed_count": 0,
        "truncated": False,
        "truncation_reasons": [],
    }


@router.get("/review-learning/status")
async def get_review_learning_status(request: Request) -> dict[str, Any]:
    try:
        service = workspace(request)
        return service.get_review_learning_status()
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post("/review-learning/train")
async def trigger_review_learning_training(
    request: Request,
) -> dict[str, Any]:
    try:
        service = workspace(request)
        return await service.trigger_ranker_training()
    except Exception as exc:
        if "ONLINE_TRAINING_DISABLED" in str(exc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        raise translate_error(exc) from exc
