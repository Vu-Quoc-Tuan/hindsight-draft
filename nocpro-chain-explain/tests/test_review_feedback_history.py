from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from libs.contracts import IngestedPackage, IngestedSnapshot
import nocpro_api.catalog as catalog
from nocpro_api.review_feedback_history import _active_snapshot_scope, load_review_feedback_history
from nocpro_api.review_principal import ReviewerPrincipal
from review_learning.contracts import ReviewDomainForbidden


def _scope_service(
    snapshot_id: str,
    *,
    source_ids: tuple[str, ...] = (),
    profile_id: str | None = None,
):
    snapshot_version = "v1"
    snapshot = IngestedSnapshot(
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        snapshot_time="2026-09-24T00:00:00Z",
        status="COMPLETE",
        source="nocpro-mock",
        source_kind="SYNTHETIC_TEST",
        produced_at="2026-09-24T00:00:00Z",
        topology_ref={"profile_id": profile_id} if profile_id else None,
    )
    package = IngestedPackage(snapshot=snapshot)
    package.provenance_manifest = {
        "sources": [{"source_id": source_id} for source_id in source_ids],
    }
    return SimpleNamespace(
        repository=None,
        current_package=lambda: package,
        active_identity=lambda: (snapshot_id, snapshot_version),
    )


def test_review_history_resolves_known_temporal_provenance() -> None:
    snapshot_id = "synthetic_temporal_topology_v1:opaque-token:snapshot_005"
    scope = asyncio.run(_active_snapshot_scope(
        _scope_service(
            snapshot_id,
            source_ids=("synthetic_temporal_topology_v1", "synthetic-topology"),
        ),
        snapshot_id,
        "v1",
    ))
    assert scope[3] == "IT_SERVICES"


@pytest.mark.parametrize(
    ("snapshot_id", "source_ids"),
    [
        ("generated_snapshot", ("unregistered-scenario",)),
        ("generated_ip_snapshot", ("synthetic_temporal_topology_v1",)),
    ],
)
def test_review_history_keeps_unknown_or_conflicting_provenance_unavailable(
    snapshot_id: str, source_ids: tuple[str, ...]
) -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(_active_snapshot_scope(
            _scope_service(snapshot_id, source_ids=source_ids), snapshot_id, "v1"
        ))
    assert error.value.status_code == 409
    assert error.value.detail == "REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE"


def test_review_history_keeps_ambiguous_provenance_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(
        catalog._PROVENANCE_SOURCE_PROFILES,
        "synthetic_ip_scenario",
        "IP_NETWORK",
    )
    snapshot_id = "generated_snapshot"
    service = _scope_service(
        snapshot_id,
        source_ids=("synthetic_temporal_topology_v1", "synthetic_ip_scenario"),
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(_active_snapshot_scope(service, snapshot_id, "v1"))
    assert error.value.detail == "REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE"


def test_review_history_keeps_malformed_provenance_unavailable() -> None:
    snapshot_id = "generated_snapshot"
    service = _scope_service(snapshot_id)
    service.current_package().provenance_manifest["sources"] = 1

    with pytest.raises(HTTPException) as error:
        asyncio.run(_active_snapshot_scope(service, snapshot_id, "v1"))

    assert error.value.status_code == 409
    assert error.value.detail == "REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE"


def _service():
    snapshot = IngestedSnapshot(
        snapshot_id="history_ip_active",
        snapshot_version="v1",
        snapshot_time="2026-09-24T00:00:00Z",
        status="COMPLETE",
        source="history-source",
        source_kind="CSV",
        produced_at="2026-09-24T00:00:00Z",
        topology_ref={"profile_id": "IP_NETWORK"},
    )
    package = IngestedPackage(snapshot=snapshot)
    learning = SimpleNamespace(
        _active_feedbacks={"fb-active": object()},
        _superseded_feedbacks={"fb-old": object()},
        _sessions={
            "rev-active": SimpleNamespace(review_domain="IP_NETWORK"),
            "rev-old": SimpleNamespace(review_domain="IP_NETWORK"),
            "rev-retracted": SimpleNamespace(review_domain="IP_NETWORK"),
        },
    )
    operator_feedbacks = [
        {
            "feedback_id": "fb-active",
            "review_id": "rev-active",
            "job_id": "job-active",
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_version": snapshot.snapshot_version,
            "chain_id": "C-ACTIVE",
            "candidate_id": "candidate-active",
            "operation": "REMOVE",
            "decision": "APPROVE",
            "reviewer_subject": "operator@example.test",
            "reviewer_role": "REVIEWER",
            "confidence": 0.9,
            "reason": "Confirmed",
            "reason_codes": ["EVIDENCE_CONFIRMED"],
            "created_at": datetime(2026, 9, 25, 12, tzinfo=timezone.utc),
            "supersedes_feedback_id": "fb-old",
        },
        {
            "feedback_id": "fb-old",
            "review_id": "rev-old",
            "job_id": "job-old",
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_version": snapshot.snapshot_version,
            "chain_id": "C-OLD",
            "candidate_id": "candidate-old",
            "operation": "SPLIT_CHAIN",
            "decision": "APPROVE",
            "reviewer_subject": "operator@example.test",
            "reviewer_role": "REVIEWER",
            "confidence": 0.7,
            "reason": "Superseded",
            "reason_codes": [],
            "created_at": datetime(2026, 9, 25, 11, tzinfo=timezone.utc),
        },
        {
            "feedback_id": "fb-retracted",
            "review_id": "rev-retracted",
            "job_id": "job-retracted",
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_version": snapshot.snapshot_version,
            "chain_id": "C-RETRACTED",
            "candidate_id": None,
            "operation": "",
            "decision": "REJECT",
            "reviewer_subject": "operator@example.test",
            "reviewer_role": "REVIEWER",
            "confidence": None,
            "reason": "Retracted",
            "reason_codes": [],
            "created_at": datetime(2026, 9, 25, 10, tzinfo=timezone.utc),
        },
        {
            "feedback_id": "fb-other-snapshot",
            "review_id": "rev-active",
            "job_id": "job-other",
            "snapshot_id": "history_ip_other",
            "snapshot_version": "v2",
            "chain_id": "C-OTHER",
            "decision": "APPROVE",
            "created_at": datetime(2026, 9, 25, 13, tzinfo=timezone.utc),
        },
    ]
    return SimpleNamespace(
        repository=None,
        current_package=lambda: package,
        active_identity=lambda: (snapshot.snapshot_id, snapshot.snapshot_version),
        review_learning=learning,
        operator_feedbacks=operator_feedbacks,
    )


def _principal(*domains: str) -> ReviewerPrincipal:
    return ReviewerPrincipal(
        subject="reviewer-1",
        role="REVIEWER",
        domain_scope=domains,
        auth_type="test",
    )


def test_review_feedback_history_filters_lifecycle_and_paginates() -> None:
    service = _service()
    first_page = asyncio.run(load_review_feedback_history(
        service,
        _principal("IP_NETWORK"),
        snapshot_id="history_ip_active",
        snapshot_version="v1",
        limit=1,
    ))

    assert first_page.history_scope == "IN_MEMORY_ACTIVE_SNAPSHOT"
    assert [item.feedback_id for item in first_page.items] == ["fb-active"]
    assert first_page.items[0].superseded_by_id is None
    assert first_page.next_cursor

    second_page = asyncio.run(load_review_feedback_history(
        service,
        _principal("IP_NETWORK"),
        snapshot_id="history_ip_active",
        snapshot_version="v1",
        limit=1,
        cursor=first_page.next_cursor,
    ))
    assert [item.feedback_id for item in second_page.items] == ["fb-old"]
    assert second_page.items[0].lifecycle_status == "SUPERSEDED"
    assert second_page.items[0].superseded_by_id == "fb-active"

    filtered = asyncio.run(load_review_feedback_history(
        service,
        _principal("IP_NETWORK"),
        snapshot_id="history_ip_active",
        snapshot_version="v1",
        search="C-RETRACTED",
        decision="REJECT",
        lifecycle_status="RETRACTED",
        reviewer="operator@",
    ))
    assert [item.feedback_id for item in filtered.items] == ["fb-retracted"]


def test_review_feedback_history_fails_closed_for_stale_snapshot_and_domain() -> None:
    stale_service = _service()
    stale_service.active_identity = lambda: ("different-snapshot", "v2")
    with pytest.raises(HTTPException) as stale_error:
        asyncio.run(load_review_feedback_history(
            stale_service,
            _principal("IP_NETWORK"),
            snapshot_id="history_ip_active",
            snapshot_version="v1",
        ))
    assert stale_error.value.detail == "STALE_REVIEW_HISTORY_SNAPSHOT"

    with pytest.raises(ReviewDomainForbidden):
        asyncio.run(load_review_feedback_history(
            _service(),
            _principal("IT_SERVICES"),
            snapshot_id="history_ip_active",
            snapshot_version="v1",
        ))


def test_review_feedback_history_rejects_invalid_cursor_and_time_ranges() -> None:
    service = _service()
    with pytest.raises(HTTPException) as cursor_error:
        asyncio.run(load_review_feedback_history(
            service,
            _principal("IP_NETWORK"),
            snapshot_id="history_ip_active",
            snapshot_version="v1",
            cursor="not-a-valid-cursor",
        ))
    assert cursor_error.value.detail == "INVALID_FEEDBACK_HISTORY_CURSOR"
    with pytest.raises(HTTPException) as time_error:
        asyncio.run(load_review_feedback_history(
            service,
            _principal("IP_NETWORK"),
            snapshot_id="history_ip_active",
            snapshot_version="v1",
            since=datetime(2026, 9, 25),
        ))
    assert time_error.value.detail == "REVIEW_HISTORY_SINCE_REQUIRES_TIMEZONE"
