# ADR-0020: Track evolving incidents with lineage rather than raw chain IDs

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evolution

## Context

A chain can receive a different snapshot-local ID even when its membership persists. Split/merge/recombination also require a graph of correspondence, not simple ID equality.

## Decision

Evolution SHALL:
1. Determine NEW/CLEARED alarms.
2. Restrict chain correspondence to `Active_both`.
3. Build bipartite lineage edges using intersection/containment rules with a small-chain exception.
4. Assign evolving-chain lineage components/branches.
5. Classify CONTINUE/GROW/SHRINK/SPLIT/MERGE/NEW/DISSOLVE/RECOMBINATION.
6. Decompose joined/left into new/reassigned/cleared/reassigned counts.

## Rationale

This measures actual production evolution rather than raw identifier churn.

## Consequences

**Positive:** correct turnover and branch semantics.

**Trade-offs:** lineage state must be persisted across snapshots.

## Alternatives considered

1. Compare chain IDs — rejected.
2. Use Jaccard alone without lifecycle decomposition — rejected.

## Implementation implications

Persist `lineage_component_id`, `branch_id`, `snapshot_chain_id` separately.

## Invariants / required tests

- Same membership with new raw chain ID can be CONTINUE.
- Δsize=0 with +10/-10 reports turnover 20.
- Small-chain matching follows the explicit exception.

## References

V2.3.1 section 7.
