"""Shared PostgreSQL corpus source for the standalone review-learning CLIs."""

from __future__ import annotations

import datetime
from typing import Any


async def fetch_postgres_groups(database_url: str, cutoff: str) -> list[dict[str, Any]]:
    """Load the immutable review groups preceding an ISO-8601 cutoff."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from nocpro_api.persistence.repository import SnapshotRepository

    engine = create_async_engine(database_url)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        cutoff_dt = datetime.datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        if cutoff_dt.tzinfo is None:
            cutoff_dt = cutoff_dt.replace(tzinfo=datetime.timezone.utc)
        return await SnapshotRepository(session_factory).training_review_groups_before(cutoff_dt)
    finally:
        await engine.dispose()
