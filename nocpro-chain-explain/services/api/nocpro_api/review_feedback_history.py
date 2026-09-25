"""Read-only, source-scoped history for Counterfactual operator feedback."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from libs.contracts.topology_identity import snapshot_topology_profile
from .catalog import (
    catalog_profile_for_snapshot,
    catalog_profiles_for_provenance_sources,
    catalog_snapshot_identities_for_profile,
)
from .persistence.models import (
    CandidateExposureModel,
    FeedbackLifecycleEventModel,
    ReviewFeedbackModel,
    ReviewSessionModel,
    Snapshot,
    SnapshotIngest,
)
from .review_principal import ReviewerPrincipal


LifecycleStatus = Literal["ACTIVE", "SUPERSEDED", "RETRACTED"]
HistoryScope = Literal[
    "PERSISTED_SOURCE_PROFILE",
    "PERSISTED_SOURCE_PROFILE_PLUS_ACTIVE",
    "IN_MEMORY_ACTIVE_SNAPSHOT",
]
_TERMINAL_EVENTS = ("SUPERSEDED", "RETRACTED")
_PROFILE_IDS = {"IP_NETWORK", "IT_SERVICES", "ALARM_ONLY"}


class ReviewFeedbackHistoryItem(BaseModel):
    feedback_id: str
    review_id: str
    job_id: str
    snapshot_id: str
    snapshot_version: str
    profile_id: str
    chain_id: str
    candidate_id: str | None = None
    operation: str = ""
    decision: str
    lifecycle_status: LifecycleStatus
    lifecycle_at: datetime | None = None
    lifecycle_reason: str | None = None
    superseded_by_id: str | None = None
    reviewer_subject: str
    reviewer_role: str
    confidence: float | None = None
    reason: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    created_at: datetime


class ReviewFeedbackHistoryPage(BaseModel):
    snapshot_id: str
    snapshot_version: str
    profile_id: str
    source_id: str
    history_scope: HistoryScope
    items: list[ReviewFeedbackHistoryItem] = Field(default_factory=list)
    next_cursor: str | None = None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value") and isinstance(value.value, str):
        value = value.value
    normalized = str(value).strip()
    return normalized or None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _encode_cursor(created_at: datetime, feedback_id: str) -> str:
    value = json.dumps(
        {"created_at": created_at.astimezone(timezone.utc).isoformat(), "feedback_id": feedback_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    if len(cursor) > 1024:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="INVALID_FEEDBACK_HISTORY_CURSOR")
    try:
        raw = base64.urlsafe_b64decode(cursor + ("=" * (-len(cursor) % 4)))
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid cursor payload")
        created_at = _datetime(value.get("created_at"))
        feedback_id = value.get("feedback_id")
        if created_at is None or not isinstance(feedback_id, str) or not feedback_id:
            raise ValueError("invalid cursor fields")
        return created_at, feedback_id
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError, binascii.Error):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="INVALID_FEEDBACK_HISTORY_CURSOR") from None


async def _active_snapshot_scope(
    service: Any, snapshot_id: str, snapshot_version: str
) -> tuple[Any, str, str, str, str]:
    package = service.current_package()
    if package is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="REVIEW_HISTORY_SNAPSHOT_REQUIRED")
    active_identity = service.active_identity()
    if active_identity != (snapshot_id, snapshot_version):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="STALE_REVIEW_HISTORY_SNAPSHOT")

    snapshot = package.snapshot
    source_id = _text(getattr(snapshot, "source", None))
    source_kind = _text(getattr(snapshot, "source_kind", None))
    topology_ref = getattr(snapshot, "topology_ref", None)
    explicit_profile = (
        topology_ref.get("profile_id")
        if isinstance(topology_ref, dict)
        else getattr(topology_ref, "profile_id", None)
    )
    profile_id = _text(explicit_profile)
    repository = getattr(service, "repository", None)
    if not profile_id and repository is not None:
        async with repository.sessions() as db_session:
            snapshot_ingest = await db_session.get(SnapshotIngest, (snapshot_id, snapshot_version))
        profile_id = _text(snapshot_ingest.topology_profile_id) if snapshot_ingest is not None else None
    if not profile_id:
        manifest = getattr(package, "provenance_manifest", None)
        sources = manifest.get("sources") if isinstance(manifest, dict) else None
        if not isinstance(sources, (list, tuple)):
            sources = ()
        source_ids = tuple(
            source["source_id"]
            for source in sources or ()
            if isinstance(source, dict) and isinstance(source.get("source_id"), str)
        )
        profile_evidence = (
            _text(catalog_profile_for_snapshot(snapshot_id, snapshot_version)),
            _text(snapshot_topology_profile(snapshot_id, None)),
            *catalog_profiles_for_provenance_sources(source_ids),
        )
        resolved_profiles = {
            value.upper() for value in profile_evidence if value
        }
        if len(resolved_profiles) == 1:
            profile_id = next(iter(resolved_profiles))
        elif len(resolved_profiles) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE",
            )
    profile_id = profile_id.upper() if profile_id else None
    if not source_id or not source_kind or profile_id not in _PROFILE_IDS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE")
    return package, source_id, source_kind, profile_id, snapshot_id


def _profile_filter(profile_id: str):
    profile_clauses = [SnapshotIngest.topology_profile_id == profile_id]
    missing_profile = SnapshotIngest.topology_profile_id.is_(None)
    legacy_marker = {"IP_NETWORK": "_ip_", "IT_SERVICES": "_it_"}.get(profile_id)
    if legacy_marker is not None:
        profile_clauses.append(and_(
            missing_profile,
            func.lower(Snapshot.snapshot_id).contains(legacy_marker, autoescape=True),
        ))
    for catalog_snapshot_id, catalog_snapshot_version in catalog_snapshot_identities_for_profile(profile_id):
        identity_clause = Snapshot.snapshot_id == catalog_snapshot_id
        if catalog_snapshot_version is not None:
            identity_clause = and_(
                identity_clause,
                Snapshot.snapshot_version == catalog_snapshot_version,
            )
        profile_clauses.append(and_(missing_profile, identity_clause))
    return or_(*profile_clauses)


def _lifecycle_filter(status_filter: LifecycleStatus):
    if status_filter == "ACTIVE":
        inactive = select(FeedbackLifecycleEventModel.feedback_id).where(
            FeedbackLifecycleEventModel.event_type.in_(_TERMINAL_EVENTS)
        )
        return ReviewFeedbackModel.feedback_id.not_in(inactive)
    event_ids = select(FeedbackLifecycleEventModel.feedback_id).where(
        FeedbackLifecycleEventModel.event_type == status_filter
    )
    return ReviewFeedbackModel.feedback_id.in_(event_ids)


def _memory_items(
    service: Any,
    principal: ReviewerPrincipal,
    *,
    snapshot_id: str,
    snapshot_version: str,
    profile_id: str,
    search: str | None,
    decision: str | None,
    lifecycle_status: LifecycleStatus | None,
    reviewer: str | None,
    since: datetime | None,
    until: datetime | None,
) -> list[ReviewFeedbackHistoryItem]:
    learning = service.review_learning
    active_ids = set(learning._active_feedbacks)
    superseded_ids = set(learning._superseded_feedbacks)
    superseding_ids = {
        str(item.get("supersedes_feedback_id")): str(item.get("feedback_id"))
        for item in service.operator_feedbacks
        if item.get("supersedes_feedback_id")
    }
    result: list[ReviewFeedbackHistoryItem] = []
    for row in service.operator_feedbacks:
        if str(row.get("snapshot_id") or "") != snapshot_id:
            continue
        if str(row.get("snapshot_version") or "1") != snapshot_version:
            continue
        created_at = _datetime(row.get("created_at"))
        if created_at is None:
            continue
        feedback_id = str(row.get("feedback_id") or "")
        if not feedback_id:
            continue
        if feedback_id in active_ids:
            row_status: LifecycleStatus = "ACTIVE"
        elif feedback_id in superseded_ids:
            row_status = "SUPERSEDED"
        else:
            row_status = "RETRACTED"
        session = learning._sessions.get(str(row.get("review_id") or ""))
        if session is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="REVIEW_HISTORY_PROVENANCE_UNAVAILABLE")
        principal.verify_domain_authorization(session.review_domain)
        if decision and str(row.get("decision") or "").upper() != decision.upper():
            continue
        if lifecycle_status and row_status != lifecycle_status:
            continue
        reviewer_subject = str(row.get("reviewer_subject") or row.get("operator_id") or "")
        if reviewer and reviewer.casefold() not in reviewer_subject.casefold():
            continue
        if since and created_at < since:
            continue
        if until and created_at > until:
            continue
        candidate_id = _text(row.get("candidate_id"))
        operation = _text(row.get("operation")) or ""
        if search:
            searchable = " ".join((
                str(row.get("chain_id") or ""), candidate_id or "", operation,
                feedback_id,
            )).casefold()
            if search.casefold() not in searchable:
                continue
        result.append(ReviewFeedbackHistoryItem(
            feedback_id=feedback_id,
            review_id=str(row.get("review_id") or ""),
            job_id=str(row.get("job_id") or ""),
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            profile_id=profile_id,
            chain_id=str(row.get("chain_id") or ""),
            candidate_id=candidate_id,
            operation=operation,
            decision=str(row.get("decision") or "UNKNOWN"),
            lifecycle_status=row_status,
            superseded_by_id=superseding_ids.get(feedback_id),
            reviewer_subject=reviewer_subject,
            reviewer_role=str(row.get("reviewer_role") or "UNKNOWN"),
            confidence=row.get("confidence"),
            reason=_text(row.get("reason")),
            reason_codes=[str(code) for code in (row.get("reason_codes") or [])],
            created_at=created_at,
        ))
    return result


def _apply_cursor_and_limit(
    items: list[ReviewFeedbackHistoryItem], limit: int, cursor: str | None
) -> tuple[list[ReviewFeedbackHistoryItem], str | None]:
    cursor_value = _decode_cursor(cursor)
    if cursor_value:
        cursor_time, cursor_id = cursor_value
        items = [
            item for item in items
            if item.created_at < cursor_time
            or (item.created_at == cursor_time and item.feedback_id < cursor_id)
        ]
    items.sort(key=lambda item: (item.created_at, item.feedback_id), reverse=True)
    page_items = items[: limit + 1]
    has_more = len(page_items) > limit
    page_items = page_items[:limit]
    next_cursor = _encode_cursor(page_items[-1].created_at, page_items[-1].feedback_id) if has_more and page_items else None
    return page_items, next_cursor


async def load_review_feedback_history(
    service: Any,
    principal: ReviewerPrincipal,
    *,
    snapshot_id: str,
    snapshot_version: str,
    search: str | None = None,
    decision: str | None = None,
    lifecycle_status: LifecycleStatus | None = None,
    reviewer: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> ReviewFeedbackHistoryPage:
    package, source_id, source_kind, profile_id, active_snapshot_id = await _active_snapshot_scope(
        service, snapshot_id, snapshot_version
    )
    del package
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="INVALID_REVIEW_HISTORY_LIMIT")
    if since and (since.tzinfo is None or since.utcoffset() is None):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="REVIEW_HISTORY_SINCE_REQUIRES_TIMEZONE")
    if until and (until.tzinfo is None or until.utcoffset() is None):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="REVIEW_HISTORY_UNTIL_REQUIRES_TIMEZONE")
    if since and until and since > until:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="REVIEW_HISTORY_TIME_RANGE_INVALID")
    since_utc = since.astimezone(timezone.utc) if since else None
    until_utc = until.astimezone(timezone.utc) if until else None
    decision_value = decision.upper() if decision else None

    if service.repository is None:
        items = _memory_items(
            service,
            principal,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            profile_id=profile_id,
            search=search.strip() if search else None,
            decision=decision_value,
            lifecycle_status=lifecycle_status,
            reviewer=reviewer.strip() if reviewer else None,
            since=since_utc,
            until=until_utc,
        )
        page_items, next_cursor = _apply_cursor_and_limit(items, limit, cursor)
        return ReviewFeedbackHistoryPage(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            profile_id=profile_id,
            source_id=source_id,
            history_scope="IN_MEMORY_ACTIVE_SNAPSHOT",
            items=page_items,
            next_cursor=next_cursor,
        )

    cursor_value = _decode_cursor(cursor)
    query = (
        select(ReviewFeedbackModel, ReviewSessionModel, CandidateExposureModel)
        .join(ReviewSessionModel, ReviewFeedbackModel.review_id == ReviewSessionModel.review_id)
        .outerjoin(
            CandidateExposureModel,
            and_(
                CandidateExposureModel.review_id == ReviewFeedbackModel.review_id,
                CandidateExposureModel.candidate_id == ReviewFeedbackModel.candidate_id,
            ),
        )
        .outerjoin(
            Snapshot,
            and_(
                Snapshot.snapshot_id == ReviewSessionModel.snapshot_id,
                Snapshot.snapshot_version == ReviewSessionModel.snapshot_version,
            ),
        )
        .outerjoin(
            SnapshotIngest,
            and_(
                SnapshotIngest.snapshot_id == ReviewSessionModel.snapshot_id,
                SnapshotIngest.snapshot_version == ReviewSessionModel.snapshot_version,
            ),
        )
        .where(or_(
            and_(
                ReviewSessionModel.snapshot_id == snapshot_id,
                ReviewSessionModel.snapshot_version == snapshot_version,
            ),
            and_(
                Snapshot.source == source_id,
                Snapshot.source_kind == source_kind,
                _profile_filter(profile_id),
            ),
        ))
    )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.where(or_(
            ReviewSessionModel.chain_id.ilike(pattern),
            ReviewFeedbackModel.feedback_id.ilike(pattern),
            ReviewFeedbackModel.candidate_id.ilike(pattern),
            CandidateExposureModel.operation.ilike(pattern),
        ))
    if decision_value:
        query = query.where(ReviewFeedbackModel.decision == decision_value)
    if reviewer and reviewer.strip():
        query = query.where(ReviewFeedbackModel.reviewer_subject.ilike(f"%{reviewer.strip()}%"))
    if since_utc:
        query = query.where(ReviewFeedbackModel.created_at >= since_utc)
    if until_utc:
        query = query.where(ReviewFeedbackModel.created_at <= until_utc)
    if lifecycle_status:
        query = query.where(_lifecycle_filter(lifecycle_status))
    if cursor_value:
        cursor_time, cursor_id = cursor_value
        query = query.where(or_(
            ReviewFeedbackModel.created_at < cursor_time,
            and_(
                ReviewFeedbackModel.created_at == cursor_time,
                ReviewFeedbackModel.feedback_id < cursor_id,
            ),
        ))
    query = query.order_by(
        ReviewFeedbackModel.created_at.desc(), ReviewFeedbackModel.feedback_id.desc()
    ).limit(limit + 1)

    async with service.repository.sessions() as db_session:
        rows = (await db_session.execute(query)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        feedback_ids = [fb.feedback_id for fb, _session, _exposure in rows]
        events_by_feedback: dict[str, Any] = {}
        if feedback_ids:
            event_rows = (await db_session.scalars(
                select(FeedbackLifecycleEventModel)
                .where(
                    FeedbackLifecycleEventModel.feedback_id.in_(feedback_ids),
                    FeedbackLifecycleEventModel.event_type.in_(_TERMINAL_EVENTS),
                )
                .order_by(FeedbackLifecycleEventModel.created_at.desc())
            )).all()
            for event in event_rows:
                events_by_feedback.setdefault(event.feedback_id, event)
        current_snapshot_row = await db_session.get(SnapshotIngest, (snapshot_id, snapshot_version))

    items: list[ReviewFeedbackHistoryItem] = []
    for feedback, session, exposure in rows:
        principal.verify_domain_authorization(session.review_domain)
        lifecycle = events_by_feedback.get(feedback.feedback_id)
        status_value: LifecycleStatus = lifecycle.event_type if lifecycle else "ACTIVE"
        items.append(ReviewFeedbackHistoryItem(
            feedback_id=feedback.feedback_id,
            review_id=feedback.review_id,
            job_id=session.job_id,
            snapshot_id=session.snapshot_id,
            snapshot_version=session.snapshot_version,
            profile_id=profile_id,
            chain_id=session.chain_id,
            candidate_id=feedback.candidate_id,
            operation=exposure.operation if exposure is not None else "",
            decision=feedback.decision,
            lifecycle_status=status_value,
            lifecycle_at=lifecycle.created_at if lifecycle else None,
            lifecycle_reason=lifecycle.reason if lifecycle else None,
            superseded_by_id=lifecycle.superseded_by_id if lifecycle else None,
            reviewer_subject=feedback.reviewer_subject,
            reviewer_role=feedback.reviewer_role,
            confidence=feedback.confidence,
            reason=feedback.reason_text,
            reason_codes=list(feedback.reason_codes or []),
            created_at=feedback.created_at,
        ))
    next_cursor = (
        _encode_cursor(items[-1].created_at, items[-1].feedback_id)
        if has_more and items
        else None
    )
    scope: HistoryScope = (
        "PERSISTED_SOURCE_PROFILE"
        if current_snapshot_row is not None and current_snapshot_row.topology_profile_id == profile_id
        else "PERSISTED_SOURCE_PROFILE_PLUS_ACTIVE"
    )
    return ReviewFeedbackHistoryPage(
        snapshot_id=active_snapshot_id,
        snapshot_version=snapshot_version,
        profile_id=profile_id,
        source_id=source_id,
        history_scope=scope,
        items=items,
        next_cursor=next_cursor,
    )
