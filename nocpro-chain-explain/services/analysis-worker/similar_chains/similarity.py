"""Cosine similarity baseline for Similar Chains (§8.3, ADR-0022).

Cosine over a normalized concatenated feature vector: TF-IDF(family) +
TF-IDF(device_type) + one-hot(top descriptor predicates) + one-hot(size_bin) +
one-hot(duration_bin). Weighted Jaccard is a benchmark alternative, not the
baseline, and is not implemented here.

Every fingerprint compared in one request MUST come from the same
``FingerprintModel`` (same ``model_version``). Fitting IDF per query batch, or
scoring a cached fingerprint against a model fit at a different time, silently
puts the two vectors in different vector spaces -- the resulting cosine number
would still print, just be meaningless. ``cosine_similarity`` raises rather
than compute a silently-wrong score across model versions.

Dedup rule: the nearest "different incident" result cannot be the same
``lineage_component_id`` -- otherwise the most similar chain to itself five
minutes ago is just itself. A separate mode intentionally returns exactly that
comparison ("previous states of this chain").
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .fingerprint import ChainFingerprint, FingerprintModel


class ModelVersionMismatch(ValueError):
    """Raised when two fingerprints/models being compared disagree on version."""


def _dot(a: dict[str, float], b: dict[str, float]) -> float:
    common = a.keys() & b.keys()
    return sum(a[term] * b[term] for term in common)


def _norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def _feature_vector(
    fingerprint: ChainFingerprint, model: FingerprintModel
) -> dict[str, float]:
    """Concatenate all fingerprint components into one namespaced sparse vector.

    Namespacing (``family:``, ``device:``, ...) keeps identically spelled terms
    from different components (e.g. a family name equal to a size bin id) from
    colliding.
    """
    vector: dict[str, float] = {}
    for term, weight in model.family_model.tfidf(fingerprint.family_terms).items():
        vector[f"family:{term}"] = weight
    for term, weight in model.device_model.tfidf(fingerprint.device_type_terms).items():
        vector[f"device:{term}"] = weight
    for term in fingerprint.descriptor_terms:
        # One-hot: presence of a top predicate, not its mined precision, so a
        # chain either shares that descriptor or it does not.
        vector[f"descriptor:{term}"] = 1.0
    vector[f"size:{fingerprint.size_bin}"] = 1.0
    vector[f"duration:{fingerprint.duration_bin}"] = 1.0
    return vector


def _check_model_version(fingerprint: ChainFingerprint, model: FingerprintModel) -> None:
    """Reject scoring a fingerprint against a different model than last scored it.

    Catches the concrete failure mode: a cached/persisted fingerprint stamped
    under ``sim-v1`` handed to a corpus/model that has since moved to
    ``sim-v2``. A freshly built fingerprint (``scored_with_model_version=None``)
    has nothing to check against yet -- that is the normal first-scoring path.
    """
    stamped = fingerprint.scored_with_model_version
    if stamped is not None and stamped != model.model_version:
        raise ModelVersionMismatch(
            f"fingerprint for chain {fingerprint.chain_id!r} was last scored with "
            f"model {stamped!r}, but is being compared under {model.model_version!r}. "
            "Re-encode with the current model instead of mixing vector spaces."
        )


def cosine_similarity(
    left: ChainFingerprint, right: ChainFingerprint, *, model: FingerprintModel
) -> float:
    """Cosine similarity in [0,1] (all weights are non-negative here).

    Raises :class:`ModelVersionMismatch` if either fingerprint was previously
    stamped as scored by a different model version than ``model``.
    """
    _check_model_version(left, model)
    _check_model_version(right, model)
    vector_a = _feature_vector(left, model)
    vector_b = _feature_vector(right, model)
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
    #: Fingerprint blocks that actually contributed to this specific score,
    #: i.e. the intersection of what target and candidate both had active.
    #: Lets the UI say "basis: 3/5 feature blocks" instead of implying the
    #: score reflects full-fidelity incident identity.
    compared_blocks: tuple[str, ...]


def _compared_blocks(target: ChainFingerprint, candidate: ChainFingerprint) -> tuple[str, ...]:
    return tuple(sorted(set(target.active_blocks()) & set(candidate.active_blocks())))


def find_similar_chains(
    target: ChainFingerprint,
    corpus: list[ChainFingerprint],
    *,
    model: FingerprintModel,
    top_k: int = 5,
    exclude_same_lineage: bool = True,
) -> list[SimilarChainResult]:
    """Rank ``corpus`` by similarity to ``target``, all under one ``model``.

    ``exclude_same_lineage=True`` is the default "different incident" mode
    (ADR-0022): chains sharing ``target``'s ``lineage_component_id`` are
    dropped. Set it to ``False`` explicitly for the "previous states of this
    chain" mode, which wants exactly those matches.

    Ties in similarity break on ``chain_id`` so ranking is stable regardless of
    corpus iteration order or the underlying similarity float's rounding.
    """
    # Reject up front if the target itself was stamped under a different model;
    # this also stamps nothing, since scoring against the corpus below is what
    # actually determines the version each fingerprint is being used under.
    _check_model_version(target, model)

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
        _check_model_version(candidate, model)
        score = cosine_similarity(target, candidate, model=model)
        results.append(
            SimilarChainResult(
                chain_id=candidate.chain_id,
                similarity=score,
                lineage_component_id=candidate.lineage_component_id,
                compared_blocks=_compared_blocks(target, candidate),
            )
        )

    results.sort(key=lambda r: (-r.similarity, r.chain_id))
    return results[:top_k]


def previous_states_of_chain(
    target: ChainFingerprint,
    corpus: list[ChainFingerprint],
    *,
    model: FingerprintModel,
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
        model=model,
        top_k=top_k,
        exclude_same_lineage=False,
    )
