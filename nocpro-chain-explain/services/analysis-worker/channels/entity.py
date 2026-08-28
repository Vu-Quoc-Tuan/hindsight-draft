"""Entity channels ``E_*`` (§4A, POST_HOC).

``E_reference``, ``E_device``, ``E_card`` and ``E_site`` are separate typed
channels. ``E_remote`` is a relation, deliberately outside the containment scale.

Critical detail: the derivation tag is the **source field**, so every channel
derived from ``reference`` shares one derivation group and therefore votes once.
That is what stops three views of the same field inflating agreement.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedAlarm
from libs.provenance import ProvenanceClass

from .base import ChannelValue, unavailable

#: Entity channel id -> (raw field, derivation tag).
#: device_code and node_reference are distinct fields, hence distinct groups.
ENTITY_CHANNELS: dict[str, tuple[str, str]] = {
    "E_reference": ("node_reference", "reference"),
    "E_device": ("device_code", "device"),
    "E_card": ("component", "card"),
    "E_site": ("location_code", "site"),
}

#: E_remote is a relation channel, not containment.
REMOTE_CHANNEL = "E_remote"
REMOTE_FIELD = "remote_node"
REMOTE_DERIVATION = "remote"

#: Boolean equality channels: support means equal.
EQUALITY_THRESHOLD = 1.0


def _field(alarm: IngestedAlarm, field: str) -> str | None:
    """Read a field from the canonical attribute or fall back to raw."""
    value = getattr(alarm, field, None)
    if value is None:
        value = alarm.raw.get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class EntityChannelSpec:
    channel_id: str
    field: str
    derivation_tag: str


def entity_channel(
    spec: EntityChannelSpec, alarm_a: IngestedAlarm, alarm_b: IngestedAlarm
) -> ChannelValue:
    """Evaluate one entity equality channel for a pair.

    If either side lacks the field the channel is ⊥: we cannot claim the
    entities differ when one value is simply missing.
    """
    left = _field(alarm_a, spec.field)
    right = _field(alarm_b, spec.field)

    if left is None or right is None:
        missing = spec.field
        return unavailable(
            spec.channel_id,
            spec.derivation_tag,
            ProvenanceClass.POST_HOC,
            reason=f"{missing} missing on at least one alarm",
            threshold=EQUALITY_THRESHOLD,
        )

    equal = left == right
    return ChannelValue(
        channel_id=spec.channel_id,
        derivation_tag=spec.derivation_tag,
        provenance_class=ProvenanceClass.POST_HOC,
        availability=True,
        positive_score=1.0 if equal else 0.0,
        threshold=EQUALITY_THRESHOLD,
        detail=f"{spec.field}: {left!r} vs {right!r}",
    )


def evaluate_entity_channels(
    alarm_a: IngestedAlarm, alarm_b: IngestedAlarm
) -> list[ChannelValue]:
    """Evaluate every ``E_*`` channel, including the remote relation."""
    values = [
        entity_channel(
            EntityChannelSpec(channel_id=channel_id, field=field, derivation_tag=tag),
            alarm_a,
            alarm_b,
        )
        for channel_id, (field, tag) in ENTITY_CHANNELS.items()
    ]
    values.append(evaluate_remote_channel(alarm_a, alarm_b))
    return values


def evaluate_remote_channel(
    alarm_a: IngestedAlarm, alarm_b: IngestedAlarm
) -> ChannelValue:
    """``E_remote``: shared remote node.

    Kept separate from containment channels because "same remote endpoint" is a
    relation between alarms, not a statement that one contains the other.
    """
    left = _field(alarm_a, REMOTE_FIELD)
    right = _field(alarm_b, REMOTE_FIELD)
    if left is None or right is None:
        return unavailable(
            REMOTE_CHANNEL,
            REMOTE_DERIVATION,
            ProvenanceClass.POST_HOC,
            reason=f"{REMOTE_FIELD} missing on at least one alarm",
            threshold=EQUALITY_THRESHOLD,
        )
    return ChannelValue(
        channel_id=REMOTE_CHANNEL,
        derivation_tag=REMOTE_DERIVATION,
        provenance_class=ProvenanceClass.POST_HOC,
        availability=True,
        positive_score=1.0 if left == right else 0.0,
        threshold=EQUALITY_THRESHOLD,
        detail=f"{REMOTE_FIELD}: {left!r} vs {right!r}",
    )
