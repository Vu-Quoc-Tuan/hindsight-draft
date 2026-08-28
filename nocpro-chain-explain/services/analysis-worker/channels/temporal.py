"""Temporal channels ``T_burst`` and ``T_delay`` (§4A, POST_HOC).

``T_burst`` — SameBurst, **contextual**. Silent-gap segmentation runs inside a
blocking context (site/device/region), never over the global stream: a
nationwide stream may never fall silent, so a global gap search would put
everything in one burst.

``T_delay`` — DelayCompatibility by **local mass**, not CDF:

    s+(dt) = P_r(|T - dt| <= h) / max_t P_r(|T - t| <= h)

A CDF-based ``2*min(F, 1-F)`` is wrong for multimodal delays: with modes at ~2s
and ~100s, dt=50s gives F~0.5 and therefore score 1.0 even though that region
almost never occurs.

``T_delay`` needs a fitted per-relation distribution. Without one it returns ⊥
rather than a fabricated score, per ADR-0029's fail-closed requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from libs.contracts import IngestedAlarm
from libs.provenance import ProvenanceClass

from .base import ChannelValue, unavailable

BURST_CHANNEL = "T_burst"
BURST_DERIVATION = "temporal_burst"
DELAY_CHANNEL = "T_delay"
DELAY_DERIVATION = "temporal_delay"

#: Same contextual burst is boolean.
BURST_THRESHOLD = 1.0

#: Default silent-gap: a new burst starts after this much quiet in the context.
DEFAULT_SILENT_GAP_SECONDS = 120

#: Fields tried in order to define the blocking context.
DEFAULT_CONTEXT_FIELDS = ("location_code", "device_code")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def context_key(alarm: IngestedAlarm, fields: tuple[str, ...]) -> str | None:
    """Resolve the blocking context for an alarm.

    Returns ``None`` when no context field is present: without a context the
    burst question is not answerable, and a global fallback is forbidden.
    """
    for name in fields:
        value = getattr(alarm, name, None) or alarm.raw.get(name)
        if value and str(value).strip():
            return f"{name}={str(value).strip()}"
    return None


@dataclass
class BurstSegmentation:
    """Contextual burst assignment for one chain.

    ``burst_of`` maps alarm_id -> "context#index". Alarms with no resolvable
    context are absent, which makes ``T_burst`` ⊥ for their pairs.
    """

    burst_of: dict[str, str] = field(default_factory=dict)
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS
    context_fields: tuple[str, ...] = DEFAULT_CONTEXT_FIELDS

    def same_burst(self, alarm_a: str, alarm_b: str) -> bool | None:
        left, right = self.burst_of.get(alarm_a), self.burst_of.get(alarm_b)
        if left is None or right is None:
            return None
        return left == right


def segment_bursts(
    alarms: list[IngestedAlarm],
    *,
    silent_gap_seconds: int = DEFAULT_SILENT_GAP_SECONDS,
    context_fields: tuple[str, ...] = DEFAULT_CONTEXT_FIELDS,
) -> BurstSegmentation:
    """Segment alarms into bursts per blocking context."""
    by_context: dict[str, list[tuple[datetime, str]]] = {}
    for alarm in alarms:
        key = context_key(alarm, context_fields)
        start = _parse(alarm.canonical_start_time)
        if key is None or start is None:
            # No context or no parseable time => not assignable.
            continue
        by_context.setdefault(key, []).append((start, alarm.alarm_id))

    burst_of: dict[str, str] = {}
    for key, entries in by_context.items():
        entries.sort()
        index = 0
        previous: datetime | None = None
        for start, alarm_id in entries:
            if previous is not None and (start - previous).total_seconds() > silent_gap_seconds:
                index += 1
            burst_of[alarm_id] = f"{key}#{index}"
            previous = start

    return BurstSegmentation(
        burst_of=burst_of,
        silent_gap_seconds=silent_gap_seconds,
        context_fields=context_fields,
    )


def evaluate_burst_channel(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    segmentation: BurstSegmentation,
) -> ChannelValue:
    """Evaluate ``T_burst`` for a pair."""
    same = segmentation.same_burst(alarm_a.alarm_id, alarm_b.alarm_id)
    if same is None:
        return unavailable(
            BURST_CHANNEL,
            BURST_DERIVATION,
            ProvenanceClass.POST_HOC,
            reason="no resolvable blocking context or unparseable timestamp",
            threshold=BURST_THRESHOLD,
        )
    return ChannelValue(
        channel_id=BURST_CHANNEL,
        derivation_tag=BURST_DERIVATION,
        provenance_class=ProvenanceClass.POST_HOC,
        availability=True,
        positive_score=1.0 if same else 0.0,
        threshold=BURST_THRESHOLD,
        detail=(
            f"same contextual burst (gap<={segmentation.silent_gap_seconds}s)"
            if same
            else "different contextual burst"
        ),
    )


@dataclass(frozen=True)
class DelayDistribution:
    """Observed delays for one directed relation, used for local-mass typicality.

    ``samples`` are ``t_B - t_A`` in seconds for A->B. Direction matters: A->B and
    B->A are different relations and must not be mirrored.
    """

    relation: str
    samples: tuple[float, ...]
    bandwidth_seconds: float

    def local_mass(self, delta: float) -> float:
        return float(
            sum(1 for s in self.samples if abs(s - delta) <= self.bandwidth_seconds)
        )

    def max_local_mass(self) -> float:
        """Peak local mass, evaluated at the sample points."""
        if not self.samples:
            return 0.0
        return max(self.local_mass(s) for s in self.samples)

    def typicality(self, delta: float) -> float | None:
        """``P(|T-dt|<=h) / max_t P(|T-t|<=h)``, or ``None`` if not computable."""
        peak = self.max_local_mass()
        if peak <= 0:
            return None
        return self.local_mass(delta) / peak


def evaluate_delay_channel(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    *,
    distribution: DelayDistribution | None,
    threshold: float,
) -> ChannelValue:
    """Evaluate ``T_delay`` for the directed pair ``a -> b``.

    Returns ⊥ when no fitted distribution is supplied: delay typicality cannot be
    invented from a single observation.
    """
    if distribution is None:
        return unavailable(
            DELAY_CHANNEL,
            DELAY_DERIVATION,
            ProvenanceClass.POST_HOC,
            reason="no fitted delay distribution for this relation",
            threshold=threshold,
        )

    start_a = _parse(alarm_a.canonical_start_time)
    start_b = _parse(alarm_b.canonical_start_time)
    if start_a is None or start_b is None:
        return unavailable(
            DELAY_CHANNEL,
            DELAY_DERIVATION,
            ProvenanceClass.POST_HOC,
            reason="unparseable timestamp",
            threshold=threshold,
        )

    delta = (start_b - start_a).total_seconds()
    score = distribution.typicality(delta)
    if score is None:
        return unavailable(
            DELAY_CHANNEL,
            DELAY_DERIVATION,
            ProvenanceClass.POST_HOC,
            reason="delay distribution has no mass",
            threshold=threshold,
        )

    return ChannelValue(
        channel_id=DELAY_CHANNEL,
        derivation_tag=DELAY_DERIVATION,
        provenance_class=ProvenanceClass.POST_HOC,
        availability=True,
        positive_score=score,
        threshold=threshold,
        detail=f"dt={delta:.1f}s, local-mass typicality={score:.3f}",
    )
