"""Version 1 REST routes; Tier-2 uses polling as the approved MVP transport."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from graybox import adapt_graybox_metadata
from libs.contracts import ContractIngestError

from .schemas import (
    ChainListView,
    ChainSummaryView,
    CounterfactualJobView,
    JobSubmissionView,
    JobView,
    PairWhyView,
    SnapshotLoadedView,
    SystemPairFactView,
)
from .serializers import (
    chain_analysis_view,
    counterfactual_job_view,
    job_view,
    pair_evidence_view,
)
from .workspace import SnapshotNotLoaded, Workspace


router = APIRouter(prefix="/api/v1")


def workspace(request: Request) -> Workspace:
    return request.app.state.workspace


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
        await workspace(request).flush_review_persistence()
        return counterfactual_job_view(
            workspace(request).review_jobs.get(job_id)
        )
    except Exception as exc:
        raise translate_error(exc) from exc


@router.get("/chains/{chain_id}/review", response_model=CounterfactualJobView)
async def get_latest_review(
    chain_id: str, request: Request
) -> CounterfactualJobView:
    try:
        await workspace(request).flush_review_persistence()
        result = await workspace(request).latest_review(chain_id)
        if result is None:
            raise KeyError(f"no compatible Counterfactual review for {chain_id!r}")
        return counterfactual_job_view(result)
    except Exception as exc:
        raise translate_error(exc) from exc
