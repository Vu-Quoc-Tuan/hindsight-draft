# ADR-0023: Run Tier-2 asynchronously and only per chain

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Deep analysis execution

## Context

Structural robustness, similar incidents and attribution can exceed the interactive latency budget and are unnecessary for every chain.

## Decision

Tier-2 SHALL be invoked on demand per chain, asynchronously. Tier-1B remains available during execution. Results are cached by snapshot/chain fingerprint/config version.

## Rationale

This bounds cost and prevents deep analysis from blocking the UI.

## Consequences

**Positive:** responsive interaction.

**Trade-offs:** job state/progress handling is needed.

## Alternatives considered

1. Run Tier-2 on every snapshot — rejected.
2. Block the chain page until deep analysis finishes — rejected.

## Implementation implications

API may expose job IDs/SSE/polling; mechanism is implementation-specific.

## Invariants / required tests

- No Tier-2 job processes the entire snapshot by default.
- Tier-1B endpoint completes independently of Tier-2.

## References

V2.3.1 sections 3 and 8.
