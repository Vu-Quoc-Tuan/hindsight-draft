"""Version 1 REST routes; Tier-2 uses polling as the approved MVP transport."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from graybox import adapt_graybox_metadata
from libs.contracts import ContractIngestError

from .schemas import (
    ChainListView,
    ChainSummaryView,
    CounterfactualJobView,
    OperatorFeedbackSubmission,
    OperatorFeedbackView,
    AISuggestionView,
    AssistantQueryInput,
    AssistantResponseView,
    EvolutionView,
    JobSubmissionView,
    JobView,
    PairWhyView,
    SnapshotLoadedView,
    SystemPairFactView,
)
from .serializers import (
    chain_analysis_view,
    counterfactual_job_view,
    operator_feedback_view,
    ai_suggestion_view,
    evolution_view,
    job_view,
    pair_evidence_view,
)
from .workspace import SnapshotNotLoaded, Workspace


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
    if isinstance(exc, SnapshotNotLoaded):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (ContractIngestError, ValueError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )
    raise exc


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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


@router.get("/jobs/{job_id}", response_model=JobView)
async def get_job(job_id: str, request: Request) -> JobView:
    try:
        await workspace(request).flush_audit_persistence()
        return job_view(workspace(request).jobs.get(job_id))
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
    job_id: str, request: Request
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
        return counterfactual_job_view(job)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/chains/{chain_id}/review", response_model=CounterfactualJobView)
async def get_latest_review(
    chain_id: str, request: Request
) -> CounterfactualJobView:
    try:
        service = workspace(request)
        result = await service.latest_review(chain_id)
        await service.flush_review_persistence()
        if result is None:
            raise KeyError(f"no compatible Counterfactual review for {chain_id!r}")
        return counterfactual_job_view(result)
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
) -> OperatorFeedbackView:
    try:
        service = workspace(request)
        result = await service.record_operator_feedback(
            job_id, submission.model_dump()
        )
        return operator_feedback_view(result)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/review-jobs/{job_id}/feedback",
    response_model=list[OperatorFeedbackView],
)
async def get_job_operator_feedback(
    job_id: str, request: Request
) -> list[OperatorFeedbackView]:
    try:
        service = workspace(request)
        feedbacks = await service.list_operator_feedback(job_id=job_id)
        return [operator_feedback_view(f) for f in feedbacks]
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get(
    "/chains/{chain_id}/feedback",
    response_model=list[OperatorFeedbackView],
)
async def get_chain_operator_feedback(
    chain_id: str, request: Request
) -> list[OperatorFeedbackView]:
    try:
        service = workspace(request)
        feedbacks = await service.list_operator_feedback(chain_id=chain_id)
        return [operator_feedback_view(f) for f in feedbacks]
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
    chain_id: str, request: Request
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
                review_result = (
                    public_review_result(latest_review.result)
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
        )
        return ai_suggestion_view(suggestion)
    except Exception as exc:
        raise translate_error(exc) from exc


@router.post("/assistant/query", response_model=AssistantResponseView)
async def query_assistant(
    request_body: AssistantQueryInput, request: Request
) -> AssistantResponseView:
    """Read-only deterministic assistant endpoint for active UI context."""
    try:
        from .assistant import answer_query

        result = answer_query(
            workspace(request),
            request_body.query,
            request_body.context.model_dump(),
        )
        return AssistantResponseView(
            contract_version="nocpro-assistant-v1",
            **result,
        )
    except Exception as exc:
        raise translate_error(exc) from exc
