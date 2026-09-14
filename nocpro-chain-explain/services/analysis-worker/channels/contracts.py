"""Serialized identity contract for normalized evidence families."""

from __future__ import annotations

from enum import Enum


class ChannelFamily(str, Enum):
    """Stable public family names; provider IDs remain internal."""

    DEP_UPSTREAM = "DEP_UPSTREAM"
    DEP_EMBEDDING = "DEP_EMBEDDING"


class DependencySemantic(str, Enum):
    """Epistemic dependency tier, separate from numeric evidence strength."""

    SHARED_ANCESTOR = "SHARED_ANCESTOR"
    SHARED_ACTIVE_PATH = "SHARED_ACTIVE_PATH"
    UNAVOIDABLE_DEPENDENCY = "UNAVOIDABLE_DEPENDENCY"


def dependency_derivation_tag(source_ref: str) -> str:
    """One vote per underlying dependency source/model, regardless of tier."""
    normalized = source_ref.strip()
    if not normalized:
        raise ValueError("dependency source_ref must be non-empty")
    return f"dependency:{normalized}"
