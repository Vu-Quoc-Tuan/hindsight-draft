# ADR-0022: Use normalized fingerprint + cosine similarity as the Similar Chains baseline

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Tier-2 similar incidents

## Context

Similar-incident retrieval should start with a deterministic baseline before graph motifs or more complex embeddings.

## Decision

Fingerprint each chain using:
- TF-IDF alarm family,
- TF-IDF device type,
- top IDENTITY descriptor predicates,
- size bin,
- duration bin.

Normalize and use cosine similarity as the baseline. Exclude the same evolving incident using `lineage_component_id`; provide a separate “previous states of this chain” mode.

## Rationale

Cosine is natural for the TF-IDF-heavy fingerprint and easy to benchmark.

## Consequences

**Positive:** simple, deterministic baseline.

**Trade-offs:** may miss structural similarities that motifs could later capture.

## Alternatives considered

1. Weighted Jaccard — benchmark alternative, not baseline.
2. Graph motif first — deferred.
3. Vector DB mandatory — rejected for initial scale.

## Implementation implications

Persist enough fingerprint metadata to reproduce scores.

Alarm-taxonomy resolution for the fingerprint's family term is a **data-adapter
fallback**, distinct from the `BACKOFF type->family->category` rule defined for
`T_delay`/`H` (§4A), which backs a finer level off to a coarser one. Resolution
order: (1) real family taxonomy if it matches, (2) else `alarm_type_name`
labeled `TYPE_FALLBACK`, (3) else no term — never guessed from
`alarm_name`/`device_code`. `FAMILY` and `TYPE_FALLBACK` terms SHALL be
namespaced (e.g. `FAMILY:x` vs `TYPE_FALLBACK:x`) so identically spelled values
from the two levels cannot collide in the vocabulary.

IDF weights, taxonomy/descriptor/bin configuration, and an explicit
`model_version` SHALL be bundled into one `FingerprintModel` fit once per index
corpus. Every fingerprint compared within one request SHALL be scored under the
same `model_version`; re-fitting IDF per query batch, or scoring a
cached/persisted fingerprint against a model fit at a different time, silently
places the two vectors in different vector spaces even though a cosine number
still prints. Rebuilding the model (e.g. `sim-v1 -> sim-v2`) requires
re-encoding the whole index; vectors from different versions SHALL NOT be
compared.

A result's diagnostic SHALL report which fingerprint blocks actually
contributed to that specific comparison (e.g. `alarm_taxonomy`, `device_type`,
`identity_descriptors`, `size_bin`, `duration_bin`). A `similarity=1.0` between
two chains scored on a reduced block set (e.g. two singletons with no taxonomy
or descriptor content) reflects identical representation under an incomplete
basis, not proven incident identity; UI SHALL surface this as e.g. "basis: 3/5
feature blocks" rather than an unqualified confidence number.

## Invariants / required tests

- The nearest “different incident” result cannot be the same lineage component.
- Cosine result is deterministic for fixed fingerprint/config.
- Equal-similarity results break ties deterministically (e.g. by `chain_id`),
  independent of corpus iteration order.
- `FAMILY` and `TYPE_FALLBACK` terms for the same string value never collide in
  the vocabulary.
- Scoring a fingerprint stamped under one `model_version` against a
  `FingerprintModel` of a different version is rejected, not silently computed.
- A freshly built (unstamped) fingerprint may be scored under any model.

## References

V2.3.1 section 8.3.
