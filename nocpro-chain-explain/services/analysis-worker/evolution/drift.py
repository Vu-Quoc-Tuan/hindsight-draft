"""Explanation drift, Tier-1A basic level (§7, ADR-0021).

Tier-1A drift compares only what Tier-1A actually has: membership counts,
descriptor changes, coverage/discrimination changes and lifecycle events. Roles
and evidence composition are Tier-1B, and over-merge/robustness are Tier-2; both
require a cache at *both* snapshots, because a role that was never computed
cannot be diffed.

``DATA_DRIFT`` vs ``CONFIG_DRIFT`` is the critical distinction: if a descriptor
changed because analysis config went v17 -> v18, the UI must say "explanation
changed because analysis configuration changed", not "incident behavior changed".
When both changed at once the result is ``MIXED``, never silently attributed to
data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from descriptor import DescriptorSet

from .events import ChainEvolution


class DriftTier(str, Enum):
    TIER_1A = "TIER_1A"
    TIER_1B = "TIER_1B"
    TIER_2 = "TIER_2"


class DriftCause(str, Enum):
    DATA_DRIFT = "DATA_DRIFT"
    CONFIG_DRIFT = "CONFIG_DRIFT"
    #: Both data and configuration changed; attribution is ambiguous.
    MIXED = "MIXED"
    NONE = "NONE"


class DriftAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    #: One or both snapshots lack the cache this tier needs.
    UNAVAILABLE_NO_CACHE = "UNAVAILABLE_NO_CACHE"


@dataclass(frozen=True)
class DescriptorDrift:
    """Descriptor-level change between two snapshots."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    retained: tuple[str, ...]
    top_descriptor_changed: bool
    coverage_delta: float | None
    precision_delta: float | None

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.top_descriptor_changed)


@dataclass(frozen=True)
class Tier1ADrift:
    """Basic per-snapshot drift for one evolving chain."""

    chain_id: str
    tier: DriftTier
    cause: DriftCause
    availability: DriftAvailability
    member_count_previous: int | None
    member_count_current: int | None
    descriptor_drift: DescriptorDrift | None
    lifecycle_event: str | None
    previous_config_version: str | None
    current_config_version: str | None
    narrative: str

    @property
    def member_count_delta(self) -> int | None:
        if self.member_count_previous is None or self.member_count_current is None:
            return None
        return self.member_count_current - self.member_count_previous


def diff_descriptors(
    previous: DescriptorSet, current: DescriptorSet
) -> DescriptorDrift:
    """Compare IDENTITY descriptor sets by label."""
    previous_labels = [d.label for d in previous.identity]
    current_labels = [d.label for d in current.identity]
    previous_set, current_set = set(previous_labels), set(current_labels)

    previous_top = previous.top_identity
    current_top = current.top_identity
    top_changed = (
        (previous_top.label if previous_top else None)
        != (current_top.label if current_top else None)
    )

    coverage_delta = None
    precision_delta = None
    if previous_top is not None and current_top is not None:
        coverage_delta = current_top.metrics.coverage - previous_top.metrics.coverage
        precision_delta = current_top.metrics.precision - previous_top.metrics.precision

    return DescriptorDrift(
        added=tuple(sorted(current_set - previous_set)),
        removed=tuple(sorted(previous_set - current_set)),
        retained=tuple(sorted(previous_set & current_set)),
        top_descriptor_changed=top_changed,
        coverage_delta=coverage_delta,
        precision_delta=precision_delta,
    )


def classify_cause(
    *,
    descriptor_changed: bool,
    membership_changed: bool,
    config_changed: bool,
) -> DriftCause:
    """Attribute drift to data, configuration, or both.

    Config change alone must never be reported as changed incident behavior.
    """
    if not descriptor_changed and not membership_changed:
        return DriftCause.NONE
    if config_changed and membership_changed:
        # Cannot separate the two influences from Tier-1A information alone.
        return DriftCause.MIXED
    if config_changed:
        return DriftCause.CONFIG_DRIFT
    return DriftCause.DATA_DRIFT


def _narrative(cause: DriftCause, chain_id: str) -> str:
    if cause is DriftCause.CONFIG_DRIFT:
        return (
            f"Chain {chain_id}: explanation changed because analysis configuration "
            "changed."
        )
    if cause is DriftCause.DATA_DRIFT:
        return f"Chain {chain_id}: explanation changed because the incident changed."
    if cause is DriftCause.MIXED:
        return (
            f"Chain {chain_id}: both the incident and the analysis configuration "
            "changed; attribution is ambiguous."
        )
    return f"Chain {chain_id}: no explanation drift detected."


def tier1a_drift(
    chain_id: str,
    *,
    previous_descriptors: DescriptorSet | None,
    current_descriptors: DescriptorSet | None,
    member_count_previous: int | None,
    member_count_current: int | None,
    evolution: ChainEvolution | None = None,
    previous_config_version: str | None = None,
    current_config_version: str | None = None,
) -> Tier1ADrift:
    """Compute Tier-1A basic drift for one chain."""
    if previous_descriptors is None or current_descriptors is None:
        # Nothing to diff against: report unavailability rather than "no drift".
        return Tier1ADrift(
            chain_id=chain_id,
            tier=DriftTier.TIER_1A,
            cause=DriftCause.NONE,
            availability=DriftAvailability.UNAVAILABLE_NO_CACHE,
            member_count_previous=member_count_previous,
            member_count_current=member_count_current,
            descriptor_drift=None,
            lifecycle_event=evolution.event.value if evolution else None,
            previous_config_version=previous_config_version,
            current_config_version=current_config_version,
            narrative=(
                f"Chain {chain_id}: drift unavailable, no descriptor snapshot on "
                "one side."
            ),
        )

    descriptor_drift = diff_descriptors(previous_descriptors, current_descriptors)
    membership_changed = (
        member_count_previous is not None
        and member_count_current is not None
        and member_count_previous != member_count_current
    )
    config_changed = (
        previous_config_version is not None
        and current_config_version is not None
        and previous_config_version != current_config_version
    )
    cause = classify_cause(
        descriptor_changed=descriptor_drift.changed,
        membership_changed=membership_changed,
        config_changed=config_changed,
    )

    return Tier1ADrift(
        chain_id=chain_id,
        tier=DriftTier.TIER_1A,
        cause=cause,
        availability=DriftAvailability.AVAILABLE,
        member_count_previous=member_count_previous,
        member_count_current=member_count_current,
        descriptor_drift=descriptor_drift,
        lifecycle_event=evolution.event.value if evolution else None,
        previous_config_version=previous_config_version,
        current_config_version=current_config_version,
        narrative=_narrative(cause, chain_id),
    )


def higher_tier_drift_available(
    previous_cached: bool, current_cached: bool
) -> DriftAvailability:
    """Tier-1B / Tier-2 drift needs a cache at both snapshots (ADR-0021)."""
    if previous_cached and current_cached:
        return DriftAvailability.AVAILABLE
    return DriftAvailability.UNAVAILABLE_NO_CACHE
