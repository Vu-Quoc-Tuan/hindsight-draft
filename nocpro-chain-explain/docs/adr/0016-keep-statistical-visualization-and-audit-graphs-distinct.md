# ADR-0016: Keep statistical, visualization and audit graphs distinct

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Graph semantics

## Context

Top-K pruning is useful for UI but can fabricate bridges/weak cuts. Statistical counts and structural audit have different correctness requirements.

## Decision

Maintain three graph purposes:

- `STATISTICAL`: full indexed counts/statistics, not a display graph.
- `VISUALIZATION`: bounded/top-K for UI only.
- `AUDIT`: full eligible graph under a size threshold; otherwise supernode/sparsifier policy with explicit guarantees.

Structural verdicts SHALL NOT run on the visualization graph.

## Rationale

This prevents UI sparsification artifacts from becoming methodology claims.

## Consequences

**Positive:** structural audit remains defensible.

**Trade-offs:** multiple representations/caches may coexist.

## Alternatives considered

1. One graph for everything — rejected.
2. Always full graph — rejected for very large chains.

## Implementation implications

Graph objects/DTOs should carry purpose/type explicitly.

### Current implementation status (checked 2026-09-27)

The accepted design above mentions a supernode/sparsifier policy above the Audit
size threshold. The current source does not implement that approximate Audit
path: Tier-2 builds the exact graph only when the chain is within its exact
member ceiling; otherwise the graph is `NOT_COMPUTED` and Structural Audit is
`UNAVAILABLE` with `AUDIT_LIMIT_EXCEEDED`. Do not claim an approximate Audit
result until a separately verified implementation and its guarantees exist.

## Invariants / required tests

- Changing visualization top-K does not change audit verdict on the same canonical inputs.
- Audit never reads a `VISUALIZATION` graph instance.

## References

V2.3.1 sections 6 and 11.
