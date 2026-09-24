"""Shared snapshot-to-topology profile identification for unpinned sources."""

from __future__ import annotations

from typing import Any


def snapshot_topology_profile(snapshot_id: str, explicit_profile: str | None = None) -> str | None:
    if explicit_profile:
        return explicit_profile
    snapshot_id = snapshot_id.lower()
    if "_it_" in snapshot_id:
        return "IT_SERVICES"
    if "_ip_" in snapshot_id:
        return "IP_NETWORK"
    return None


async def effective_topology_version(
    snapshot_id: str,
    *,
    pinned_version: str | None,
    explicit_profile: str | None,
    repository: Any,
    active_by_profile: dict[str, str | None] | None = None,
) -> str | None:
    """Use a pinned version, otherwise the current version of the profile."""
    if pinned_version:
        return pinned_version
    profile = snapshot_topology_profile(snapshot_id, explicit_profile)
    if not profile or repository is None:
        return None
    cache = active_by_profile if active_by_profile is not None else {}
    if profile not in cache:
        active = await repository.get_active_version(profile)
        cache[profile] = active.topology_version if active else None
    return cache[profile]
