"""Pair-WHY adapter for frozen directed temporal compatibility."""

from channels.base import ChannelValue
from channels.temporal import DELAY_CHANNEL, DELAY_DERIVATION
from history import HistoricalTaxonomy
from libs.contracts import IngestedAlarm
from libs.provenance import ProvenanceClass

from .model import FrozenDelayModel, evaluate_ordered_delay_model


def evaluate_temporal_delay_channel(
    left: IngestedAlarm, right: IngestedAlarm, *, model: FrozenDelayModel | None,
    taxonomy: HistoricalTaxonomy | None, threshold: float | None,
    threshold_source: str | None = None,
    unavailable_reason: str | None = None,
) -> ChannelValue:
    if unavailable_reason is not None:
        lookup = None
        reason = unavailable_reason
    elif left.canonical_start_time is None or right.canonical_start_time is None:
        lookup = None
        reason = "UNPARSEABLE_TIMESTAMP"
    elif taxonomy is None:
        lookup = None
        reason = "TAXONOMY_UNAVAILABLE"
    else:
        lookup = evaluate_ordered_delay_model(
            taxonomy.resolve(left), taxonomy.resolve(right), left_start=left.canonical_start_time,
            right_start=right.canonical_start_time, model=model,
        )
        reason = lookup.reason
    if lookup is None or not lookup.available:
        return ChannelValue(DELAY_CHANNEL, DELAY_DERIVATION, ProvenanceClass.POST_HOC, False, 0.0, threshold, detail=reason, source_ref=model.model_version if model else None)
    relation = lookup.relation
    assert relation is not None
    metadata = {
        "model_source": "TEMPORAL_BEHAVIORAL", "resolved_level": lookup.resolved_level.value,
        "source_token": lookup.relation_key.source_token, "target_token": lookup.relation_key.target_token,
        "direction": f"{lookup.relation_key.source_token}->{lookup.relation_key.target_token}",
        "delay_seconds": lookup.delay_seconds, "history_model_id": model.model_version,
        "training_cutoff": model.training_cutoff, "estimator": relation.estimator.value,
        "selection_mode": relation.selection_mode, "estimator_parameter_seconds": relation.estimator_parameter_seconds,
        "local_mass_halfwidth_seconds": relation.local_mass_halfwidth_seconds,
        "raw_observation_count": relation.raw_observation_count,
        "episode_sample_count": relation.episode_sample_count,
        "local_mass": lookup.local_mass, "normalizing_peak_mass": lookup.normalizing_peak_mass,
        "peak_mass_procedure": relation.PEAK_MASS_PROCEDURE,
        "support_threshold": threshold, "support_threshold_source": threshold_source,
    }
    return ChannelValue(DELAY_CHANNEL, DELAY_DERIVATION, ProvenanceClass.POST_HOC, True, lookup.positive_score, threshold, detail="historical directed temporal compatibility", source_ref=model.model_version, source_id=model.taxonomy_source_id, source_version=model.taxonomy_source_version, evidence_metadata=metadata)
