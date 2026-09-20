"""Version 1 REST routes; Tier-2 uses polling as the approved MVP transport."""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import partial
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

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
    ApplyThresholdInput,
    ProposalClarityComparisonView,
    ThresholdExplainOptimizationView,
)
from .catalog import list_catalog_presets, load_preset_payload
from .threshold_explain_optimizer import (
    apply_explain_threshold,
    find_clearest_explain_threshold,
)
from tier2.counterfactual.explain_clarity_comparator import (
    compare_proposal_explanations,
)
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
from .entity_resolver import AlarmEntityResolver
from .review_principal import (
    ReviewReasonPolicyUnavailable,
    ReviewerPrincipal,
    get_reviewer_principal,
    load_reason_policy,
)
from review_learning.contracts import SimilarCaseRetrievalResult
from sqlalchemy import select
from .persistence.models import CohesionNarrativeCache


router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)



def workspace(request: Request) -> Workspace:
    return request.app.state.workspace


def topology_repo(request: Request):
    return getattr(request.app.state, "topology_repository", None)


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
async def list_chains(request: Request, background_tasks: BackgroundTasks) -> ChainListView:
    try:
        service = workspace(request)
        result = service.list_chains()
        background_tasks.add_task(service.precompute_snapshot_deep_dive)
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


@router.post("/snapshots/precompute-deep-dive")
async def trigger_precompute_deep_dive(
    request: Request, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    try:
        service = workspace(request)
        background_tasks.add_task(service.precompute_snapshot_deep_dive)
        return {"status": "QUEUED"}
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/chains/{chain_id}")
async def explain_chain(chain_id: str, request: Request):
    service = workspace(request)
    try:
        result = await asyncio.to_thread(service.analyze, chain_id)
        pkg = service.require_package()

        entity_resolutions_by_alarm = {}
        repo = topology_repo(request)
        chain_alarm_ids = list(result.members.keys())
        resolver: AlarmEntityResolver | None = None
        new_resolutions = []

        topo_ref = getattr(getattr(pkg, "snapshot", None), "topology_ref", None) or getattr(pkg, "topology_ref", None)
        profile_id = getattr(topo_ref, "profile_id", None)
        target_topo_ver = getattr(topo_ref, "topology_version", None)
        if not profile_id:
            snap_id = getattr(getattr(pkg, "snapshot", None), "snapshot_id", "") or ""
            if "ip" in snap_id.lower():
                profile_id = "IP_NETWORK"
            else:
                profile_id = "IT_SERVICES"

        topo_ver = target_topo_ver
        persisted_by_alarm: dict[str, list[AlarmEntityResolution]] = {}

        if repo is not None:
            active = await repo.get_active_version(profile_id)
            if active is not None:
                topo_ver = target_topo_ver or active.topology_version
                host_mod_map, host_can_map = await repo.get_host_modules_map(
                    profile_id, topology_version=topo_ver
                )
                resolver = AlarmEntityResolver(
                    profile_id=profile_id,
                    topology_version=topo_ver,
                    host_modules_map=host_mod_map,
                    host_canonical_id_map=host_can_map,
                )

            if topo_ver:
                try:
                    persisted = await repo.get_alarm_entity_resolutions(
                        chain_alarm_ids, profile_id, topo_ver
                    )
                    for r in persisted:
                        persisted_by_alarm.setdefault(r.alarm_id, []).append(r)
                except Exception as e:
                    logger.warning("Failed to fetch persisted entity resolutions: %s", e)

        if resolver is None:
            resolver = AlarmEntityResolver.from_package(pkg)
            if not topo_ver:
                topo_ver = resolver.topology_version

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

        if repo is not None and new_resolutions:
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


@router.get("/chains/{chain_id}/pairs/{alarm_a}/{alarm_b}", response_model=PairWhyView)
async def explain_pair(
    chain_id: str, alarm_a: str, alarm_b: str, request: Request
) -> PairWhyView:
    service = workspace(request)
    try:
        values = await asyncio.to_thread(service.pair_why, chain_id, alarm_a, alarm_b)
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
                for cand in view.result.get("evaluated_candidates", []):
                    if (
                        isinstance(cand, dict)
                        and cand.get("hard_gate_result", {}).get("status") == "PASSED"
                        and cand.get("comparative_explanation")
                        and not cand["comparative_explanation"].get("ai_narrative")
                    ):
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
        ai_provider_status = "NOT_CONFIGURED"
        overall_rationale = comparison_res.overall_recommendation_rationale
        try:
            from .grounded_llm import is_provider_configured, render_grounded
            if is_provider_configured() and overall_rationale:
                rendered = render_grounded(
                    draft=overall_rationale,
                    facts={
                        "top_proposal": comparison_res.top_proposal_operation,
                        "top_proposal_id": comparison_res.top_proposal_id,
                        "candidates_count": len(candidates_raw),
                    },
                    fact_refs=[job.chain_id, comparison_res.top_proposal_operation or ""],
                    purpose="ADVISOR",
                )
                ai_model = rendered.model
                ai_provider_status = rendered.provider_status
                if rendered.used_provider and rendered.provider_status == "OK":
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
    min_common_blocks: int = Query(2, ge=1, le=5),
    principal: ReviewerPrincipal = Depends(get_reviewer_principal),
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
        package = service.current_package() if hasattr(service, "current_package") else None
        try:
            latest_review = await service.latest_review(chain_id)
            if latest_review and latest_review.result:
                from tier2.counterfactual.public_contract import public_review_result
                if hasattr(latest_review.result, "recommendations"):
                    review_result = public_review_result(latest_review.result, package=package, language=lang)
                elif isinstance(latest_review.result, dict):
                    review_result = dict(latest_review.result)
                    if "evaluated_candidates" in review_result:
                        from tier2.counterfactual.comparative_explainer import (
                            build_deterministic_comparative_explanation,
                        )
                        cands = []
                        for cand in review_result.get("evaluated_candidates", []):
                            if isinstance(cand, dict):
                                cand_copy = dict(cand)
                                cand_m_ids = cand.get("member_ids")
                                if not cand_m_ids:
                                    ev = cand.get("operation_specific_evidence") or {}
                                    if ev.get("alarm_id"):
                                        cand_m_ids = [str(ev["alarm_id"])]
                                    elif cand.get("partition_delta"):
                                        p_delta = cand.get("partition_delta") or {}
                                        b_list = p_delta.get("before") or []
                                        a_list = p_delta.get("after") or []
                                        if b_list and a_list:
                                            b_m = set(b_list[0][1]) if len(b_list) > 0 and len(b_list[0]) > 1 else set()
                                            a_m = set(a_list[0][1]) if len(a_list) > 0 and len(a_list[0]) > 1 else set()
                                            diff = b_m - a_m
                                            if diff:
                                                cand_m_ids = list(sorted(diff))
                                cand_copy["member_ids"] = cand_m_ids or []
                                cand_copy["comparative_explanation"] = build_deterministic_comparative_explanation(
                                    operation=cand.get("operation", "UNKNOWN"),
                                    candidate_id=cand.get("candidate_id", ""),
                                    partition_delta=cand.get("partition_delta"),
                                    before_metrics=cand.get("before_metrics") or cand.get("before"),
                                    after_metrics=cand.get("after_metrics") or cand.get("after"),
                                    metric_deltas=cand.get("metric_deltas"),
                                    package=package,
                                    member_ids=cand_m_ids or (),
                                    source_chain_id=cand.get("source_chain_id") or chain_id,
                                    target_chain_id=cand.get("target_chain_id"),
                                    merged_chain_ids=cand.get("merged_chain_ids"),
                                    operation_evidence=cand.get("operation_specific_evidence"),
                                    semantic_effects=cand.get("semantic_effects"),
                                    structural_facts=cand.get("structural_facts"),
                                    language=lang,
                                ).as_dict()
                                cands.append(cand_copy)
                            else:
                                cands.append(cand)
                        review_result["evaluated_candidates"] = cands
                else:
                    review_result = latest_review.result
                review_status = "AVAILABLE"
                if isinstance(review_result, dict):
                    review_reason = review_result.get("reason")
                    if not review_reason and review_result.get("recommendation_status") == "UNAVAILABLE":
                        review_reason = "RECOMMENDATION_UNAVAILABLE"
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
            package=package,
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
    chain_id: str,
    request: Request,
    lang: str = Query("en"),
    force_refresh: bool = Query(False),
) -> CohesionNarrativeView:
    try:
        service = workspace(request)
        active_id = service.active_identity() if hasattr(service, "active_identity") else None
        snapshot_id = active_id[0] if active_id else "default_snapshot"
        snapshot_version = active_id[1] if active_id else "v1"

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
        try:
            deep_dive_job = await service.latest_deep_dive(chain_id)
            if (
                deep_dive_job
                and getattr(deep_dive_job, "status", None)
                and getattr(deep_dive_job.status, "value", str(deep_dive_job.status)) == "SUCCEEDED"
            ):
                deep_dive_analysis = deep_dive_job.result
                if audit_artifact is None and getattr(deep_dive_job, "audit_artifact", None):
                    audit_artifact = deep_dive_job.audit_artifact
        except Exception:
            logger.debug("Failed to retrieve latest deep dive job for chain %s", chain_id, exc_info=True)

        # Check DB cache if available and not force_refresh
        if service.repository is not None and not force_refresh:
            try:
                async with service.repository.sessions() as session:
                    cache_stmt = select(CohesionNarrativeCache).where(
                        CohesionNarrativeCache.snapshot_id == snapshot_id,
                        CohesionNarrativeCache.snapshot_version == snapshot_version,
                        CohesionNarrativeCache.chain_id == chain_id,
                        CohesionNarrativeCache.language == lang,
                    )
                    cached_row = (await session.scalars(cache_stmt)).first()
                    if cached_row is not None:
                        # If cached has P2, OR if P2 is still not completed (audit_artifact and deep_dive_analysis are None):
                        if cached_row.has_p2 or (audit_artifact is None and deep_dive_analysis is None):
                            return CohesionNarrativeView(
                                chain_id=cached_row.chain_id,
                                narrative=cached_row.narrative,
                                model=cached_row.model,
                                provider_status=cached_row.provider_status,
                                context=cached_row.context,
                            )
            except Exception:
                logger.debug("Cohesion narrative DB cache lookup failed", exc_info=True)

        review_result = None
        try:
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

        from .cohesion_advisor import generate_cohesion_narrative
        result = await _run_grounded_provider(
            generate_cohesion_narrative,
            service=service,
            chain_id=chain_id,
            audit_artifact=audit_artifact,
            review_result=review_result,
            audit_error_reason=audit_error_reason,
            deep_dive_analysis=deep_dive_analysis,
            language=lang,
        )

        has_p2 = (audit_artifact is not None) or (deep_dive_analysis is not None)
        if isinstance(result.context, dict):
            result.context["has_p2"] = has_p2

        # Save to DB cache
        if service.repository is not None:
            try:
                async with service.repository.sessions() as session:
                    cache_record = CohesionNarrativeCache(
                        snapshot_id=snapshot_id,
                        snapshot_version=snapshot_version,
                        chain_id=chain_id,
                        language=lang,
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


@router.get("/topology/subgraph")
async def get_topology_subgraph(
    request: Request,
    profile_id: str | None = None,
    profile: str | None = None,
    seeds: str = "",
    hops: int = Query(default=2, ge=1, le=5),
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
