"""Serialized identity contract for normalized evidence families."""

from __future__ import annotations

from enum import Enum


class ChannelFamily(str, Enum):
    """Stable public family names; provider IDs remain internal."""

    DEP_EMBEDDING = "DEP_EMBEDDING"


class DependencySemantic(str, Enum):
    """Epistemic dependency tier, separate from numeric evidence strength."""

    SHARED_ANCESTOR = "SHARED_ANCESTOR"
    SHARED_ACTIVE_PATH = "SHARED_ACTIVE_PATH"
    UNAVOIDABLE_DEPENDENCY = "UNAVOIDABLE_DEPENDENCY"
