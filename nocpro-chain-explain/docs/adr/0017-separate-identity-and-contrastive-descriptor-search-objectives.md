# ADR-0017: Separate IDENTITY and CONTRASTIVE descriptor search objectives

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Descriptor mining

## Context

A globally common predicate can still strongly distinguish a chain from nearby competitors. One global precision floor would suppress useful contrastive rules.

## Decision

Implement two searches over the same bounded bitmap engine:

- IDENTITY: maximize coverage subject to `Precision_global >= p_min`.
- CONTRASTIVE: maximize coverage subject to `Precision_local >= p_local` on the fixed local competitor universe `U_local`.

Redundancy filtering applies within each descriptor type.

## Rationale

The two questions are semantically different: “what defines this chain?” vs “what distinguishes it from nearby chains?”.

## Consequences

**Positive:** explanations match the user question.

**Trade-offs:** two objective functions and metrics must be maintained.

## Alternatives considered

1. One descriptor ranking for all WHY questions — rejected.
2. Full gFIM in the interactive tier — rejected for latency.

## Implementation implications

Use bounded depth/beam/top-K predicates and bitmap-backed counts. `U_local` must be deterministic from the blocking index.

## Invariants / required tests

- A globally common but locally discriminative rule can appear as CONTRASTIVE.
- Redundant extents (e.g. Jaccard≥0.9) are filtered within each type.

## References

V2.3.1 section 5.
