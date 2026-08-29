from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from .persistence import SnapshotRepository


class Tier1ACoordinator:
    """Durably claim Tier-1A once, while keeping Tier-1B lazy in Workspace."""

    def __init__(
        self,
        repository: SnapshotRepository,
        workspace,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 120,
        max_attempts: int = 5,
        backoff_base_seconds: int = 2,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.worker_id = worker_id or f"{os.getpid()}-{uuid4().hex}"
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds

    async def run(self, snapshot_id: str, snapshot_version: str):
        """Process logical-oldest jobs until the requested snapshot is READY."""
        target = (snapshot_id, snapshot_version)
        while True:
            completed = await self.run_pending_once()
            if completed is None:
                return None
            identity, precompute = completed
            if identity == target:
                return precompute

    async def run_pending_once(self):
        claim = await self.repository.claim_next_tier1a(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            max_attempts=self.max_attempts,
        )
        if claim is None:
            return None
        try:
            package, precompute = self.workspace.compute_snapshot(claim.payload)
            renewed = await self.repository.heartbeat_tier1a(
                claim.snapshot_id,
                claim.snapshot_version,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if not renewed:
                raise RuntimeError("Tier-1A lease ownership was lost")
            summary: dict[str, Any] = {
                "snapshot_id": precompute.snapshot_id,
                "snapshot_version": claim.snapshot_version,
                "alarm_count": precompute.alarm_count,
                "chain_count": precompute.chain_count,
                "singleton_count": precompute.singleton_count,
                "config_version": precompute.config_version,
            }
            await self.repository.finish_tier1a(
                claim.snapshot_id,
                claim.snapshot_version,
                result=summary,
                worker_id=self.worker_id,
            )
            active_payload = await self.repository.latest_ready_payload()
            if active_payload is not None:
                active_id = (
                    active_payload["snapshot"]["snapshot_id"],
                    active_payload["snapshot"]["snapshot_version"],
                )
                if active_id == (claim.snapshot_id, claim.snapshot_version):
                    self.workspace.activate_snapshot(package, precompute)
                else:
                    active_package, active_precompute = self.workspace.compute_snapshot(
                        active_payload
                    )
                    self.workspace.activate_snapshot(active_package, active_precompute)
            return (claim.snapshot_id, claim.snapshot_version), precompute
        except Exception as exc:
            await self.repository.record_tier1a_failure(
                claim.snapshot_id,
                claim.snapshot_version,
                error=str(exc),
                worker_id=self.worker_id,
                max_attempts=self.max_attempts,
                backoff_base_seconds=self.backoff_base_seconds,
            )
            raise

    async def hydrate_active(self):
        """Serve the latest logical READY immediately after process startup."""
        payload = await self.repository.latest_ready_payload()
        if payload is None:
            return None
        identity = (
            payload["snapshot"]["snapshot_id"],
            payload["snapshot"]["snapshot_version"],
        )
        if self.workspace.active_identity() == identity:
            return self.workspace.precompute
        package, precompute = self.workspace.compute_snapshot(payload)
        self.workspace.activate_snapshot(package, precompute)
        return precompute
