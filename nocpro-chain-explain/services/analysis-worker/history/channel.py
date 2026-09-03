"""Pair-WHY adapter for behavioural historical evidence ``H`` only."""

from __future__ import annotations

from channels.base import ChannelValue
from libs.contracts import IngestedAlarm
from libs.provenance import ProvenanceClass

from .evidence import (
    HISTORICAL_CHANNEL,
    HISTORICAL_DERIVATION,
    HistoricalEvidenceModel,
    HistoricalTaxonomy,
    evaluate_historical_evidence,
)


def evaluate_historical_channel(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    *,
    model: HistoricalEvidenceModel | None,
    taxonomy: HistoricalTaxonomy | None,
    unavailable_reason: str | None = None,
) -> ChannelValue:
    """Project a frozen H lookup into normalized Pair WHY evidence only."""
    value = evaluate_historical_evidence(
        alarm_a,
        alarm_b,
        model=model,
        taxonomy=taxonomy,
        unavailable_reason=unavailable_reason,
    )
    metadata = {
        "resolved_level": value.resolved_level.value if value.resolved_level else None,
        "support": value.support,
        "marginal_a": value.marginal_a,
        "marginal_b": value.marginal_b,
        "episode_population": value.episode_population,
        "lift": value.lift,
        "strength": value.strength,
        "reliability": value.reliability,
        "history_model_id": value.model_version,
        "training_cutoff": value.training_cutoff,
    }
    return ChannelValue(
        channel_id=HISTORICAL_CHANNEL,
        derivation_tag=HISTORICAL_DERIVATION,
        provenance_class=ProvenanceClass.BEHAVIORAL,
        availability=value.available,
        positive_score=value.positive_score,
        threshold=None,
        detail=value.reason,
        source_ref=value.model_version,
        source_id=value.taxonomy_source_id,
        source_version=value.taxonomy_source_version,
        evidence_metadata=metadata,
        support_override=value.supports if value.available else None,
    )
