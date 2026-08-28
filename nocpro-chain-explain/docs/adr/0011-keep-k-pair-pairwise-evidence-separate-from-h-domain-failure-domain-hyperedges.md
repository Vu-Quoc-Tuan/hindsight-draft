# ADR-0011: Keep `K_pair` pairwise evidence separate from `H_domain` failure-domain hyperedges

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evidence representation

## Context

Failure domains such as SRLG/fiber/power/rack/site/service instance are set-valued operational structures, not naturally pairwise evidence channels.

## Decision

`K_pair` SHALL contain only atomic pairwise channels. `H_domain` SHALL remain a hyperedge/set representation with domain identity, type, members, source, quality and provenance.

`H_domain` SHALL NOT be clique-projected into `G*_explain` or `G*_audit`.

Failure-domain membership MAY propose a candidate block/cut, but the quality of that cut SHALL be evaluated on the pairwise `G*_audit` only.

## Rationale

This preserves the source semantics and prevents one shared domain from creating O(m²) artificial positive edges.

## Consequences

**Positive:** no representation inflation; failure-domain explanations stay human-readable.

**Trade-offs:** algorithms that need pairwise graphs must explicitly handle domain sets separately.

## Alternatives considered

1. Clique projection — rejected.
2. Ignore failure domains — rejected because they are valuable P1 context/explanation.

## Implementation implications

Provide explicit domain membership APIs and candidate-set generation functions rather than a generic `score(i,j)`.

## Invariants / required tests

- No `s(i,j)` is fabricated for `H_domain`.
- Adding a domain cannot directly increase `w*_audit`.
- Domain membership can generate a candidate cut without generating pair edges.

## References

V2.3.1 sections 0, 4, 4A and 6.
