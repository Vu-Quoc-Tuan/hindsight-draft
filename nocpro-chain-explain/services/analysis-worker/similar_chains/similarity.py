"""Cosine similarity baseline for Similar Chains (§8.3, ADR-0022).

Cosine over a normalized concatenated feature vector: TF-IDF(family) +
TF-IDF(device_type) + one-hot(top descriptor predicates) + one-hot(size_bin) +
one-hot(duration_bin). Weighted Jaccard is a benchmark alternative, not the
baseline, and is not implemented here.

Dedup rule: the nearest "different incident" result cannot be the same
``lineage_component_id`` -- otherwise the most similar chain to itself five
minutes ago is just itself. A separate mode intentionally returns exactly that
comparison ("previous states of this chain").
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .fingerprint import ChainFingerprint, TfIdfModel


def _dot(a: dict[str, float], b: dict[str, float]) -> float:
    common = a.keys() & b.keys()
    return sum(a[term] * b[term] for term in common)


def _norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def _feature_vector(
    fingerprint: ChainFingerprint,
    family_model: TfIdfModel,
    device_model: TfIdfModel,
) -> dict[str, float]:
    """Concatenate all fingerprint components into one namespaced sparse vector.

    Namespacing (``family:``, ``device:``, ...) keeps identically spelled terms
    from different components (e.g. a family name equal to a size bin id) from
    colliding.
    """
    vector: dict[str, float] = {}
    for term, weight in family_model.tfidf(fingerprint.family_terms).items():
        vector[f"family:{term}"] = weight
    for term, weight in device_model.tfidf(fingerprint.device_type_terms).items():
        vector[f"device:{term}"] = weight
    for term in fingerprint.descriptor_terms:
        # One-hot: presence of a top predicate, not its mined precision, so a
        # chain either shares that descriptor or it does not.
        vector[f"descriptor:{term}"] = 1.0
    vector[f"size:{fingerprint.size_bin}"] = 1.0
    vector[f"duration:{fingerprint.duration_bin}"] = 1.0
    return vector


def cosine_similarity(
    left: ChainFingerprint,
    right: ChainFingerprint,
    *,
    family_model: TfIdfModel,
    device_model: TfIdfModel,
) -> float:
    """Cosine similarity in [0,1] (all weights are non-negative here)."""
    vector_a = _feature_vector(left, family_model, device_model)
    vector_b = _feature_vector(right, family_model, device_model)
    norm_a, norm_b = _norm(vector_a), _norm(vector_b)
    if norm_a == 0.0 or norm_b == 0.0:
        # A zero vector only arises from a hand-built fingerprint with no
        # size/duration bin at all; build_fingerprint always sets both, so
        # this path defends against malformed input rather than real chains.
        return 0.0
    return _dot(vector_a, vector_b) / (norm_a * norm_b)


@dataclass(frozen=True)
class SimilarChainResult:
    chain_id: str
    similarity: float
    lineage_component_id: str | None


def fit_tfidf_models(
    fingerprints: list[ChainFingerprint],
) -> tuple[TfIdfModel, TfIdfModel]:
    """Fit family/device TF-IDF models over a corpus of fingerprints."""
    family_model = TfIdfModel.fit([fp.family_terms for fp in fingerprints])
    device_model = TfIdfModel.fit([fp.device_type_terms for fp in fingerprints])
    return family_model, device_model


def find_similar_chains(
    target: ChainFingerprint,
    corpus: list[ChainFingerprint],
    *,
    family_model: TfIdfModel,
    device_model: TfIdfModel,
    top_k: int = 5,
    exclude_same_lineage: bool = True,
) -> list[SimilarChainResult]:
    """Rank ``corpus`` by similarity to ``target``.

    ``exclude_same_lineage=True`` is the default "different incident" mode
    (ADR-0022): chains sharing ``target``'s ``lineage_component_id`` are
    dropped. Set it to ``False`` explicitly for the "previous states of this
    chain" mode, which wants exactly those matches.
    """
    results: list[SimilarChainResult] = []
    for candidate in corpus:
        if candidate.chain_id == target.chain_id:
            continue
        if (
            exclude_same_lineage
            and target.lineage_component_id is not None
            and candidate.lineage_component_id == target.lineage_component_id
        ):
            continue
        score = cosine_similarity(
            target, candidate, family_model=family_model, device_model=device_model
        )
        results.append(
            SimilarChainResult(
                chain_id=candidate.chain_id,
                similarity=score,
                lineage_component_id=candidate.lineage_component_id,
            )
        )

    # Deterministic tie-break by chain_id so equal scores do not depend on
    # corpus iteration order.
    results.sort(key=lambda r: (-r.similarity, r.chain_id))
    return results[:top_k]


def previous_states_of_chain(
    target: ChainFingerprint,
    corpus: list[ChainFingerprint],
    *,
    family_model: TfIdfModel,
    device_model: TfIdfModel,
    top_k: int = 5,
) -> list[SimilarChainResult]:
    """"Previous states of this chain" mode: same lineage, not excluded."""
    if target.lineage_component_id is None:
        return []
    same_lineage = [
        fp
        for fp in corpus
        if fp.lineage_component_id == target.lineage_component_id
        and fp.chain_id != target.chain_id
    ]
    return find_similar_chains(
        target,
        same_lineage,
        family_model=family_model,
        device_model=device_model,
        top_k=top_k,
        exclude_same_lineage=False,
    )
