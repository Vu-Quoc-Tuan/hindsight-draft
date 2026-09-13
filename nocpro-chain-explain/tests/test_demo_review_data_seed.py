from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nocpro_api.persistence.models import (
    Base,
    CandidateExposureModel,
    ReviewCaseModel,
    ReviewFeedbackModel,
    ReviewSessionModel,
)
from nocpro_api.persistence.repository import SnapshotRepository
from nocpro_api.review_learning_service import ReviewLearningService
from nocpro_api.review_principal import ReviewerPrincipal
from scripts.review_learning.seed_demo_review_data import (
    DEMO_PREFIX,
    DEMO_VERSION,
    seed_demo_review_data,
)


pytestmark = pytest.mark.anyio


async def test_demo_seed_is_idempotent_and_explicitly_synthetic(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'demo_seed.db'}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = SnapshotRepository(async_sessionmaker(engine, expire_on_commit=False))

    try:
        first = await seed_demo_review_data(repository, group_count=8)
        second = await seed_demo_review_data(repository, group_count=8)

        assert first.created_groups == 8
        assert first.created_feedbacks > 0
        assert first.created_cases == first.created_feedbacks
        assert second.created_groups == 0
        assert second.existing_groups == 8

        async with repository.sessions() as db_session:
            sessions = list(
                (
                    await db_session.scalars(
                        select(ReviewSessionModel).where(ReviewSessionModel.review_id.startswith(DEMO_PREFIX))
                    )
                ).all()
            )
            assert len(sessions) == 8
            assert {row.source_kind for row in sessions} == {"SYNTHETIC_TEST"}
            assert {row.review_domain for row in sessions} == {"IP_NETWORK"}

            feedback_count = await db_session.scalar(
                select(func.count()).select_from(ReviewFeedbackModel).where(
                    ReviewFeedbackModel.reviewer_subject == "demo:synthetic-fixture"
                )
            )
            case_count = await db_session.scalar(
                select(func.count()).select_from(ReviewCaseModel).where(
                    ReviewCaseModel.case_id.startswith(DEMO_PREFIX)
                )
            )
            exposure_count = await db_session.scalar(
                select(func.count()).select_from(CandidateExposureModel).where(
                    CandidateExposureModel.review_id.startswith(DEMO_PREFIX)
                )
            )
            assert feedback_count == first.created_feedbacks
            assert case_count == first.created_cases
            assert exposure_count == first.created_exposures

            # PostgreSQL enforces 64-character IDs for exposure primary keys;
            # keep the versioned append-only fixture safely within that bound.
            assert all(
                len(row.exposure_id) <= 64
                for row in (
                    await db_session.scalars(
                        select(CandidateExposureModel).where(
                            CandidateExposureModel.review_id.startswith(DEMO_PREFIX)
                        )
                    )
                ).all()
            )

        service = ReviewLearningService(repository)
        matches = await service.find_similar_cases_for_candidate(
            job_id=f"{DEMO_PREFIX}j008{DEMO_VERSION}",
            candidate_id=f"{DEMO_PREFIX}r008{DEMO_VERSION}-cand-1",
            principal=ReviewerPrincipal(
                subject="demo-viewer",
                role="PRODUCT_OWNER",
                domain_scope=("IP_NETWORK",),
                auth_type="TEST",
            ),
        )
        assert matches.retrieval_status == "AVAILABLE"
        assert matches.common_block_count == 5
        assert matches.cross_incident_cases
    finally:
        await engine.dispose()
