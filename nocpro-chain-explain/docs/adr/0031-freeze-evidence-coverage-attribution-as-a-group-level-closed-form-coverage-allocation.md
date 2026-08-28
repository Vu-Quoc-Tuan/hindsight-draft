# ADR-0031: Freeze Evidence Coverage Attribution as a group-level closed-form coverage allocation

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Tier-2 attribution

## Context

The final spec intentionally renamed the feature from generic Shapley language to Evidence Coverage Attribution. Channel-level players would over-credit repeated representations of the same derivation, while exact combinatorial Shapley is unnecessary and can violate latency constraints.

## Decision

Players SHALL be eligible derivation groups, not channels.

Define:

`v(S) = |{pairs p: exists g in S with b_g(p)=1}| / C(|C|,2)`.

For each group g:

`phi_g = (1/C(|C|,2)) * sum_{p supported by g} 1/g_p`

where `g_p` is the number of derivation groups supporting pair p.

This closed-form allocation is the baseline. It SHALL be named **Evidence Coverage Attribution**, not “exact Shapley”.

Default players are EXPLAIN_ELIGIBLE groups; BEHAVIORAL contribution is visually labeled; SYSTEM_FACT is excluded.

Large chains SHALL NOT materialize all C(n,2) pairs. Use inverted-index counts, sampling or supernode approximation according to the scalability guard.

## Rationale

The formula shares each covered pair equally among supporting derivation groups and is representation-invariant at the group level.

## Consequences

**Positive:** deterministic, explainable, consistent with derivation dedup.

**Trade-offs:** it measures evidence coverage contribution, not causal importance or connectivity value.

## Alternatives considered

1. Channel-level attribution — rejected.
2. Exact combinatorial Shapley — rejected as baseline.
3. Rename output “cohesion attribution” — rejected because the value function is coverage.

## Implementation implications

Evaluate with deletion curves and brute-force comparison on tiny synthetic cases where exhaustive subset computation is feasible.

## Invariants / required tests

- Duplicating channels inside one derivation group does not multiply attribution.
- Large-chain mode proves no full pair matrix was materialized.
- UI wording says “% evidence coverage”, not “causal importance/cohesion”.

## References

V2.3.1 section 8.4 and evaluation section 13.
