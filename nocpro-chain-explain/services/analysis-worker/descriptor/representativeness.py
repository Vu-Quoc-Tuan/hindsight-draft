"""Representativeness (§4B).

    Representativeness(x,C) = share of top descriptors that x satisfies,
                              weighted by precision

Reuses the mined IDENTITY descriptors rather than introducing a second notion of
"typical member". A member satisfying the high-precision rules that define the
chain is representative of it.

Returns ``None`` (⊥) when no IDENTITY descriptor was mined: with nothing to be
representative *of*, a 0.0 would read as "atypical" when the truth is "unknown".
"""

from __future__ import annotations

from .mining import Descriptor
from .predicates import PredicateIndex


def representativeness(
    alarm_id: str,
    descriptors: tuple[Descriptor, ...],
    index: PredicateIndex,
) -> float | None:
    """Precision-weighted share of top descriptors satisfied by one member."""
    if not descriptors:
        return None
    try:
        position = index.position_of(alarm_id)
    except ValueError:
        return None

    total_weight = 0.0
    matched_weight = 0.0
    for descriptor in descriptors:
        # Precision is the weight: matching a sharp rule says more than
        # matching a rule that fires on half the network.
        weight = descriptor.metrics.precision
        total_weight += weight
        if descriptor.matches_alarm_bit(position):
            matched_weight += weight

    if total_weight <= 0:
        return None
    return matched_weight / total_weight


def representativeness_map(
    member_ids: list[str],
    descriptors: tuple[Descriptor, ...],
    index: PredicateIndex,
) -> dict[str, float | None]:
    """Representativeness for every member."""
    return {
        alarm_id: representativeness(alarm_id, descriptors, index)
        for alarm_id in member_ids
    }
