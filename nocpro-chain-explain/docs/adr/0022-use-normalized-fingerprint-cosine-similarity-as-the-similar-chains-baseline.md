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

## Invariants / required tests

- The nearest “different incident” result cannot be the same lineage component.
- Cosine result is deterministic for fixed fingerprint/config.

## References

V2.3.1 section 8.3.
