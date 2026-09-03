"""Immutable, episode-deduplicated behavioural-history evidence (``H``)."""

from .evidence import (
    HISTORICAL_CHANNEL,
    HISTORICAL_DERIVATION,
    HistoricalChainState,
    HistoricalEpisode,
    HistoricalEvidenceConfig,
    HistoricalEvidenceModel,
    HistoricalEvidenceValue,
    HistoricalTaxonomy,
    TaxonomyLevel,
    TaxonomyTokens,
    build_historical_model,
    evaluate_historical_evidence,
    evaluate_historical_oracle,
    model_from_dict,
    model_to_dict,
    taxonomy_from_dict,
    taxonomy_to_dict,
)
from .bootstrap import episodes_from_lineage_prefix

__all__ = [
    "HISTORICAL_CHANNEL",
    "HISTORICAL_DERIVATION",
    "HistoricalChainState",
    "HistoricalEpisode",
    "HistoricalEvidenceConfig",
    "HistoricalEvidenceModel",
    "HistoricalEvidenceValue",
    "HistoricalTaxonomy",
    "TaxonomyLevel",
    "TaxonomyTokens",
    "build_historical_model",
    "evaluate_historical_evidence",
    "evaluate_historical_oracle",
    "episodes_from_lineage_prefix",
    "model_from_dict",
    "model_to_dict",
    "taxonomy_from_dict",
    "taxonomy_to_dict",
]
