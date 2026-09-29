"""Semantic channel ``S`` (§4A, POST_HOC).

Ordinal scale, frozen by the spec:

    same alarm_name 1.0 > same family 0.6 > same category 0.3
    edge <=> same family or above

Structured fields are used first; free-text template normalization is only a
fallback and is not implemented here, because the real export provides
``alarm_name`` and inventing a text model would be unfounded.
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.contracts import IngestedAlarm
from libs.provenance import ProvenanceClass

from .base import ChannelValue, unavailable
from .field_values import read_alarm_string_field

CHANNEL_ID = "S"
DERIVATION_TAG = "semantic"

SCORE_SAME_NAME = 1.0
SCORE_SAME_FAMILY = 0.6
SCORE_SAME_CATEGORY = 0.3
SCORE_UNRELATED = 0.0

#: "edge <=> same family or above", so the threshold is the family score.
THRESHOLD = SCORE_SAME_FAMILY


@dataclass(frozen=True)
class AlarmTaxonomy:
    """Optional alarm_name -> family/category mapping.

    Without a supplied taxonomy only exact-name equality is decidable; family and
    category are not guessed from string prefixes.
    """

    families: dict[str, str]
    categories: dict[str, str]

    def family_of(self, alarm_name: str) -> str | None:
        return self.families.get(alarm_name)

    def category_of(self, alarm_name: str) -> str | None:
        return self.categories.get(alarm_name)


EMPTY_TAXONOMY = AlarmTaxonomy(families={}, categories={})


def evaluate_semantic_channel(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    taxonomy: AlarmTaxonomy = EMPTY_TAXONOMY,
) -> ChannelValue:
    """Evaluate ``S`` for a pair."""
    left = read_alarm_string_field(alarm_a, "alarm_name")
    right = read_alarm_string_field(alarm_b, "alarm_name")

    if left is None or right is None:
        return unavailable(
            CHANNEL_ID,
            DERIVATION_TAG,
            ProvenanceClass.POST_HOC,
            reason="alarm_name missing on at least one alarm",
            threshold=THRESHOLD,
        )

    if left == right:
        score, detail = SCORE_SAME_NAME, "same alarm_name"
    else:
        family_a, family_b = taxonomy.family_of(left), taxonomy.family_of(right)
        category_a, category_b = taxonomy.category_of(left), taxonomy.category_of(right)
        if family_a is not None and family_a == family_b:
            score, detail = SCORE_SAME_FAMILY, f"same family {family_a!r}"
        elif category_a is not None and category_a == category_b:
            score, detail = SCORE_SAME_CATEGORY, f"same category {category_a!r}"
        else:
            # Different names with no taxonomy is a real computed result
            # (NEUTRAL), not missing data.
            score, detail = SCORE_UNRELATED, "different alarm_name"

    return ChannelValue(
        channel_id=CHANNEL_ID,
        derivation_tag=DERIVATION_TAG,
        provenance_class=ProvenanceClass.POST_HOC,
        availability=True,
        positive_score=score,
        threshold=THRESHOLD,
        detail=detail,
    )
