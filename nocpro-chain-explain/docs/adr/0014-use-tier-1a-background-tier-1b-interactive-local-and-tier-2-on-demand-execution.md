# ADR-0014: Use Tier-1A background, Tier-1B interactive-local and Tier-2 on-demand execution

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Execution tiers

## Context

The system must support large snapshots while keeping operator interaction fast. Global work, local chain explanation and deep analysis have different computational profiles.

## Decision

Use:
- Tier-1A: snapshot background indexes/counts/cache, design objective 10–30s per snapshot.
- Tier-1B: indexed/sufficient-statistics local analysis plus bounded/on-click
  materialization, design objective P95<5s.
- Tier-2: asynchronous per-chain deep dive, including full/compressed
  `G*_audit`, design objective 5–30s.

These numbers are design objectives pending benchmark, not guaranteed SLOs.

Tier-1B SHALL never wait for Tier-2.

Indexed execution is the Tier-1 statistical default. A channel without a
semantics-preserving indexed provider returns `UNAVAILABLE`; it does not fall
back silently to a dense pair scan. The pairwise implementation is retained as
a small-chain correctness oracle and for explicit pair-on-click requests.

Tier-1B SHALL report `audit_graph_mode=NOT_COMPUTED`. Exact, sparsified or
supernode audit execution and STRUCTURAL roles are Tier-2 results.

## Rationale

The split resolves the global-background vs local-materialization tension in earlier designs.

## Consequences

**Positive:** responsive UI and bounded deep computation.

**Trade-offs:** cache/version coordination is required.

## Alternatives considered

1. Compute everything every snapshot — rejected.
2. Compute everything on click — rejected because global indexes/lineage are reusable.

## Implementation implications

Cache keys include chain fingerprint/snapshot/config version as appropriate.
Execution results report statistics, pair-materialization and audit-graph modes
independently.

## Invariants / required tests

- Tier-2 runs per chain, never whole snapshot.
- Tier-1B returns without a Tier-2 result.
- Tier-1B does not call the dense pairwise oracle or materialize `G*_audit`.
- Indexed/oracle equivalence is pinned on small chains for availability,
  thresholded support, Fit, derivation grouping, MembershipSupport and contrastive margins.
- Drift tiers only compare artifacts that actually exist at both snapshots.

## References

V2.3.1 sections 3, 7, 8 and 11.
