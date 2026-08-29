from __future__ import annotations

from typing import Any

from .persistence import SnapshotRepository


class Tier1ACoordinator:
    """Durably claim Tier-1A once, while keeping Tier-1B lazy in Workspace."""

    def __init__(self, repository: SnapshotRepository, workspace) -> None:
        self.repository = repository
        self.workspace = workspace

    async def run(self, snapshot_id: str, snapshot_version: str):
        payload = await self.repository.claim_tier1a(snapshot_id, snapshot_version)
        if payload is None:
            return None
        try:
            precompute = self.workspace.replace_snapshot(payload)
            summary: dict[str, Any] = {
                "snapshot_id": precompute.snapshot_id,
                "snapshot_version": snapshot_version,
                "alarm_count": precompute.alarm_count,
                "chain_count": precompute.chain_count,
                "singleton_count": precompute.singleton_count,
                "config_version": precompute.config_version,
            }
            await self.repository.finish_tier1a(
                snapshot_id, snapshot_version, result=summary
            )
            return precompute
        except Exception as exc:
            await self.repository.release_tier1a(
                snapshot_id, snapshot_version, error=str(exc)
            )
            raise
