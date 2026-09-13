"""Version 1 REST routes; Tier-2 uses polling as the approved MVP transport."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from graybox import adapt_graybox_metadata
from libs.contracts import ContractIngestError

from .schemas import (
    CandidateDisplayEventBatchSubmission,
    CandidateDisplayEventBatchView,
    ChainListView,
    ChainSummaryView,
    CounterfactualJobView,
    OperatorFeedbackSubmission,
    OperatorFeedbackView,
    ReasonPolicyView,
    RetractionSubmission,
    AISuggestionView,
    CohesionNarrativeView,
    AssistantQueryInput,
    AssistantResponseView,
    AuditVisualizationArtifactView,
    CalibrationReportView,
    ConfigUpdateInput,
    ConfigView,
    EvolutionView,
    JobSubmissionView,
    JobView,
    PairWhyView,
    SelectSnapshotRequest,
    SnapshotCatalogListView,
    SnapshotLoadedView,
    SystemPairFactView,
)
from .catalog import list_catalog_presets, load_preset_payload
from .serializers import (
    chain_analysis_view,
    counterfactual_job_view,
    operator_feedback_view,
    ai_suggestion_view,
    audit_visualization_artifact_view,
    evolution_view,
    job_view,
    pair_evidence_view,
)
from .workspace import SnapshotNotLoaded, Workspace
from .review_principal import (
    ReviewReasonPolicyUnavailable,
    ReviewerPrincipal,
    get_reviewer_principal,
    load_reason_policy,
)
from review_learning.contracts import SimilarCaseRetrievalResult


router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)



def workspace(request: Request) -> Workspace:
    return request.app.state.workspace


async def _run_grounded_provider(function: Any, **kwargs: Any) -> Any:
    """Run one blocking provider call without retaining a default-executor thread."""
    call = partial(function, **kwargs)
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="nocpro-grounded-llm",
    ) as executor:
        return await loop.run_in_executor(executor, call)


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
            preset_ids = {p["snapshot_id"] for p in presets}
            live_rows = await service.repository.list_live_snapshots()
            _PROFILE_MAP = {
                "IP_NETWORK": "IP_NETWORK",
                "ip_network": "IP_NETWORK",
                "IT_SERVICES": "IT_SERVICES",
                "it_services": "IT_SERVICES",
                "ALARM_ONLY": "ALARM_ONLY",
                "alarm_only": "ALARM_ONLY",
            }
            for row in live_rows:
                sid = row["snapshot_id"]
                if sid in preset_ids:
                    continue  # preset takes priority for named snapshots
                raw_profile = row.get("topology_profile_id") or row.get("source_kind") or ""
                profile = _PROFILE_MAP.get(raw_profile, "IP_NETWORK")
                presets.append({
                    "snapshot_id": sid,
                    "name": sid,
                    "profile": profile,
                    "alarm_count": row["alarm_count"],
                    "chain_count": row["chain_count"],
                    "description": f"Live snapshot ingested via Kafka (version {row['snapshot_version']})",
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
        try:
            payload, _ = load_preset_payload(body.snapshot_id)
        except (KeyError, ValueError):
            if service.repository is not None:
                payload = await service.repository.get_ready_snapshot_payload(body.snapshot_id)
                if payload is None:
                    raise KeyError(f"Unknown snapshot_id: {body.snapshot_id!r}")
            else:
                raise
        result = await service.ingest_snapshot(payload)
    except Exception as exc:
        raise translate_error(exc) from exc
    return SnapshotLoadedView(
        snapshot_id=result.snapshot_id,
        snapshot_version=service.require_package().snapshot.snapshot_version,
        alarm_count=result.alarm_count,
        chain_count=result.chain_count,
        incremental_snapshot={
            "mode": service.config.incremental_snapshot.mode.value,
            "reason": service.config.incremental_snapshot.reason,
        },
    )


@router.post(
    "/snapshots",
    response_model=SnapshotLoadedView,
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
        result = workspace(request).list_chains()
    except Exception as exc:
        raise translate_error(exc) from exc
    return ChainListView(
        snapshot_id=result.snapshot_id,
        snapshot_version=workspace(request).require_package().snapshot.snapshot_version,
        chains=[
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
        ],
    )


@router.get("/chains/{chain_id}")
async def explain_chain(chain_id: str, request: Request):
    service = workspace(request)
    try:
        result = service.analyze(chain_id)
        return chain_analysis_view(result, service.require_package())
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/chains/{chain_id}/evolution", response_model=EvolutionView)
async def explain_evolution(chain_id: str, request: Request) -> EvolutionView:
    try:
        return evolution_view(await workspace(request).evolution(chain_id))
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/chains/{chain_id}/pairs/{alarm_a}/{alarm_b}", response_model=PairWhyView)
async def explain_pair(
    chain_id: str, alarm_a: str, alarm_b: str, request: Request
) -> PairWhyView:
    service = workspace(request)
    try:
        values = service.pair_why(chain_id, alarm_a, alarm_b)
        graybox = adapt_graybox_metadata(service.require_package(), chain_id)
    except Exception as exc:
        raise translate_error(exc) from exc
    fact = graybox.pair_fact(alarm_a, alarm_b)
    return PairWhyView(
        chain_id=chain_id,
        alarm_id_a=alarm_a,
        alarm_id_b=alarm_b,
        evidence=[pair_evidence_view(value) for value in values],
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
        return job_view(result) if result is not None else None
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
        try:
            job = service.review_jobs.get(job_id)
        except KeyError:
            # Preserve the read-boundary flush even for an unknown in-memory
            # job: another request may have pending durable state to release.
            await service.flush_review_persistence()
            raise
        await service.flush_review_persistence()
        pkg = None
        try:
            pkg = service.current_package()
        except Exception:
            pass
        return counterfactual_job_view(job, package=pkg, language=lang)
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
        return counterfactual_job_view(result, package=pkg, language=lang)
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
    principal: ReviewerPrincipal = Depends(get_reviewer_principal),
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
    principal: ReviewerPrincipal = Depends(get_reviewer_principal),
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
    principal: ReviewerPrincipal = Depends(get_reviewer_principal),
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
    principal: ReviewerPrincipal = Depends(get_reviewer_principal),
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
    principal: ReviewerPrincipal = Depends(get_reviewer_principal),
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
    principal: ReviewerPrincipal = Depends(get_reviewer_principal),
) -> list[OperatorFeedbackView]:
    try:
        service = workspace(request)
        feedbacks = await service.list_operator_feedback(chain_id=chain_id, principal=principal)
        return [operator_feedback_view(f) for f in feedbacks]
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
    principal: ReviewerPrincipal = Depends(get_reviewer_principal),
) -> dict[str, Any]:
    try:
        service = workspace(request)
        res = await service.find_similar_cases_for_candidate(
            job_id, candidate_id, principal=principal, top_k=top_k
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


@router.post(
    "/chains/{chain_id}/ai-suggestion",
    response_model=AISuggestionView,
)
@router.get(
    "/chains/{chain_id}/ai-suggestion",
    response_model=AISuggestionView,
)
async def get_chain_ai_suggestion(
    chain_id: str, request: Request, lang: str = Query("en")
) -> AISuggestionView:
    try:
        service = workspace(request)
        analysis = service.analyze(chain_id)
        review_result = None
        review_status = "NOT_AVAILABLE"
        review_reason = None
        try:
            latest_review = await service.latest_review(chain_id)
            if latest_review and latest_review.result:
                from tier2.counterfactual.public_contract import public_review_result
                package = service.current_package() if hasattr(service, "current_package") else None
                review_result = (
                    public_review_result(latest_review.result, package=package, language=lang)
                    if hasattr(latest_review.result, "recommendations")
                    else latest_review.result
                )
                review_status = "AVAILABLE"
        except Exception:
            logger.exception("Could not load Review artifact for AI suggestion chain=%s", chain_id)
            review_status = "UNAVAILABLE"
            review_reason = "REVIEW_ARTIFACT_UNAVAILABLE"

        from .ai_advisor import generate_ai_suggestion
        suggestion = await _run_grounded_provider(
            generate_ai_suggestion,
            chain_id=chain_id,
            analysis=analysis,
            review_result=review_result,
            review_status=review_status,
            review_reason=review_reason,
            language=lang,
        )
        return ai_suggestion_view(suggestion)
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
    chain_id: str, request: Request, lang: str = Query("en")
) -> CohesionNarrativeView:
    try:
        service = workspace(request)
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

        review_result = None
        try:
            latest_rev = await service.latest_review(chain_id)
            if latest_rev and latest_rev.result:
                from tier2.counterfactual.public_contract import public_review_result
                package = service.current_package() if hasattr(service, "current_package") else None
                review_result = (
                    public_review_result(latest_rev.result, package=package, language=lang)
                    if hasattr(latest_rev.result, "recommendations")
                    else latest_rev.result
                )
        except KeyError:
            raise
        except Exception:
            logger.exception("Failed to retrieve latest review for chain %s", chain_id)

        from .cohesion_advisor import generate_cohesion_narrative
        result = await _run_grounded_provider(
            generate_cohesion_narrative,
            service=service,
            chain_id=chain_id,
            audit_artifact=audit_artifact,
            review_result=review_result,
            audit_error_reason=audit_error_reason,
            language=lang,
        )
        return CohesionNarrativeView(
            chain_id=result.chain_id,
            narrative=result.narrative,
            model=result.model,
            provider_status=result.provider_status,
            context=result.context,
        )
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


@router.post("/config/calibrate", response_model=CalibrationReportView)
async def calibrate_config(request: Request) -> CalibrationReportView:
    try:
        report = await workspace(request).calibrate_from_database(include_fixtures=True)
        return CalibrationReportView(**report)
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
        "p2_mapping_eligible": False,
        "dependency_semantics": "UNAVAILABLE",
    }
