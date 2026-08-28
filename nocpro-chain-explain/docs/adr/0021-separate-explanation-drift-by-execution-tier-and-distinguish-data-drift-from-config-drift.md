# ADR-0021: Separate explanation drift by execution tier and distinguish DATA_DRIFT from CONFIG_DRIFT

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evolution / drift

## Context

Not every snapshot has Tier-1B/Tier-2 artifacts cached, and an explanation can change because thresholds/config changed rather than incident behavior.

## Decision

Implement:
- Tier-1A basic drift: membership/lifecycle/descriptor/coverage-discrimination changes.
- Tier-1B cached drift: roles/evidence composition only if both snapshots have corresponding 1B caches.
- Tier-2 deep drift: robustness/similar-incident differences only when both snapshots have Tier-2 results.

When config versions differ and the explanation changes because of analysis configuration, label `CONFIG_DRIFT`, not `DATA_DRIFT`.

## Rationale

This avoids fabricating historical roles/results and prevents config changes from being interpreted as incident behavior.

## Consequences

**Positive:** drift semantics are honest.

**Trade-offs:** some comparisons will be unavailable rather than forced.

## Alternatives considered

1. Recompute all historical Tier-1B/Tier-2 results automatically — rejected as default.
2. Ignore config version — rejected.

## Implementation implications

Every cached explanation artifact must include config version.

## Invariants / required tests

- Missing prior 1B cache yields unavailable 1B drift, not a recomputed hidden baseline.
- Changing only config can produce CONFIG_DRIFT with no DATA_DRIFT claim.

## References

V2.3.1 section 7.
