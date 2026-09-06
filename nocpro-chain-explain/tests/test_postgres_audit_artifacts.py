from __future__ import annotations

import asyncio
import os

import pytest

from nocpro_api.persistence import Database, SnapshotRepository
from tier2.audit_artifact import build_review_audit_artifact
from tests.test_audit_artifact import _audit, _visualization


pytestmark = pytest.mark.postgres


def _artifact(artifact_id: str, created_at: str, *, config: str = "v1"):
    return build_review_audit_artifact(
        snapshot_id="same-snapshot",
        snapshot_version="v2",
        chain_id="C1",
        members=("a1", "a2", "a3", "a4"),
        structural_audit=_audit(),
        visualization=_visualization(),
        analysis_version="tier2-audit-v1",
        analysis_config_version=config,
        artifact_id=artifact_id,
        created_at=created_at,
    )


def test_audit_artifacts_are_insert_only_and_strictly_compatible() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    async def exercise() -> None:
        database = Database(database_url)
        repository = SnapshotRepository(database.sessions)
        try:
            first = _artifact("audit-db-1", "2026-09-02T10:00:00+00:00")
            latest = _artifact("audit-db-2", "2026-09-02T10:01:00+00:00")
            await repository.persist_audit_artifact(first)
            await repository.persist_audit_artifact(latest)

            loaded = await repository.latest_compatible_audit_artifact(
                snapshot_id="same-snapshot",
                snapshot_version="v2",
                chain_id="C1",
                chain_fingerprint=latest.chain_fingerprint,
                analysis_version="tier2-audit-v1",
                analysis_config_version="v1",
            )
            assert loaded == latest

            stale = await repository.latest_compatible_audit_artifact(
                snapshot_id="same-snapshot",
                snapshot_version="v1",
                chain_id="C1",
                chain_fingerprint=latest.chain_fingerprint,
                analysis_version="tier2-audit-v1",
                analysis_config_version="v1",
            )
            assert stale is None

            rewritten = _artifact(
                "audit-db-1", "2026-09-02T10:00:00+00:00", config="v2"
            )
            with pytest.raises(ValueError, match="immutable"):
                await repository.persist_audit_artifact(rewritten)
        finally:
            await database.close()

    asyncio.run(exercise())
