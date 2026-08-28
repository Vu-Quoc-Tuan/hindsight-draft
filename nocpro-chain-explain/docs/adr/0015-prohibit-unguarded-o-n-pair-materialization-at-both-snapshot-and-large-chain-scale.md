# ADR-0015: Prohibit unguarded O(N²) pair materialization at both snapshot and large-chain scale

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Scalability

## Context

A 100k-alarm snapshot has ~5e9 pairs. Even a single 20k-alarm chain has ~200M pairs. Merely banning global all-pairs is insufficient if Tier-1B or Tier-2 silently nests over all pairs of a huge chain.

## Decision

The system SHALL NOT materialize all alarm pairs for a global snapshot.

For large chains, unguarded `O(|C|²)` materialization is also prohibited by default.

Dense all-pairs evaluation is not a Tier-1 fallback even for channels that do
not yet have an indexed provider. Such a channel is `UNAVAILABLE` until an
equivalent provider exists.

Required patterns:
- Pair WHY: compute on click.
- Equality/entity Fit: indexed/grouped counts.
- Temporal: sort/window or bounded neighborhood.
- Descriptor: bitmap/inverted counts.
- Attribution: inverted counts/sampling/supernode approximation for large chains.
- Audit: Tier-2 only; full under an explicit configured chain-size threshold,
  otherwise a benchmark-derived supernode or guaranteed sparsification policy.

## Rationale

This turns the scalability statement into an enforceable implementation rule.

## Consequences

**Positive:** prevents catastrophic memory/time behavior.

**Trade-offs:** exactness may be replaced by controlled approximation on very large chains.

## Alternatives considered

1. “Per-chain all-pairs is fine” — rejected.
2. Top-K graph for all algorithms — rejected because audit correctness can be distorted.

## Implementation implications

A configurable guard threshold SHALL select exact vs bounded/aggregate execution. Benchmarks must include large-chain shapes, not only global N.

The three guarantees are independent and explicit:

- `statistics_mode`: `EXACT_INDEXED`, `APPROXIMATED`, or `UNAVAILABLE`;
- `pair_materialization`: `ON_DEMAND`, `BOUNDED`, or `TRUNCATED`;
- `audit_graph_mode`: `NOT_COMPUTED`, `EXACT_FULL`, `SPARSIFIED`, or `SUPERNODE`.

## Invariants / required tests

- No Tier-1B default code path executes nested loops over 20k members.
- No Tier-1B default code path calls the pairwise correctness oracle.
- Tier-1B reports `audit_graph_mode=NOT_COMPUTED`.
- Pair endpoints materialize only requested/bounded pairs.
- Attribution on a large chain proves it did not allocate C(n,2) state.

## References

V2.3.1 sections 8.4 and 11.
