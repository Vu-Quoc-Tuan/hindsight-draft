"""Similar Chains: fingerprint + cosine similarity baseline (§8.3, ADR-0022)."""

from .fingerprint import (
    DEFAULT_DURATION_BINS,
    DEFAULT_SIZE_BINS,
    DEFAULT_TOP_DESCRIPTOR_PREDICATES,
    ChainFingerprint,
    TermVector,
    TfIdfModel,
    build_fingerprint,
    duration_bin,
    size_bin,
)
from .similarity import (
    SimilarChainResult,
    cosine_similarity,
    find_similar_chains,
    fit_tfidf_models,
    previous_states_of_chain,
)

__all__ = [
    "DEFAULT_DURATION_BINS",
    "DEFAULT_SIZE_BINS",
    "DEFAULT_TOP_DESCRIPTOR_PREDICATES",
    "ChainFingerprint",
    "SimilarChainResult",
    "TermVector",
    "TfIdfModel",
    "build_fingerprint",
    "cosine_similarity",
    "duration_bin",
    "find_similar_chains",
    "fit_tfidf_models",
    "previous_states_of_chain",
    "size_bin",
]
