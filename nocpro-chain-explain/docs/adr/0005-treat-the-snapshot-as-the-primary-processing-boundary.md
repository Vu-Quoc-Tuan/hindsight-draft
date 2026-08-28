# ADR-0005: Treat the snapshot as the primary processing boundary

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Processing model

## Context

NocPro re-groups the active alarm set approximately once per minute. Explanation and evolution therefore operate on snapshot state, not on an assumption of one permanent chain identity.

## Decision

Every analysis input SHALL be associated with `snapshot_id` and `snapshot_time`. Tier-1A SHALL run only on a complete canonical snapshot. Chain IDs are snapshot-scoped identifiers, not evolving incident identities.

## Rationale

This matches the production chaining process and makes evolution semantics explicit.

## Consequences

**Positive:** deterministic replay and correct evolution logic.

**Trade-offs:** snapshot completeness and versioning must be tracked carefully.

## Alternatives considered

1. Treat chain ID as globally stable — rejected.
2. Run analysis directly on a continuously mutating table — rejected for the baseline because it destroys reproducibility.

## Implementation implications

Snapshot state must include active alarms, partition/membership and any upstream metadata valid for that snapshot. Topology is linked by topology version/validity interval.

## Invariants / required tests

- Tier-1A never runs on an incomplete snapshot.
- Re-running `(snapshot, config_version)` is deterministic.
- Evolution compares canonical snapshot states, not raw chain IDs alone.

## References

V2.3.1 sections 1, 3 and 7.
