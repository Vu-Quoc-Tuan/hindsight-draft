# ADR-0026: Mark mock-generated topology, context and labels as synthetic test sources

- **Status:** Accepted — project/test provenance decision
- **Date:** 2026-08-28
- **Scope:** Mock data / evaluation hygiene

## Context

The mock may generate topology or context from the alarm data to enable development before real inventory/tickets are available. Such data can look operationally realistic but is not independent evidence.

## Decision

Mock-generated topology/context SHALL use `source_kind=SYNTHETIC_TEST`.

Replayed exports originating from real systems SHALL use a distinct kind such as `REAL_EXPORT_REPLAY`; replay origin does not automatically mean the data is current/independent enough for operational validation.

It MAY carry a structural provenance subtype needed for code-path testing, but the source-kind gate in ADR-0010 SHALL exclude it from real operational validation metrics/verdicts.

Synthetic edge/domain generation SHALL be deterministic for a fixed fixture/config/seed and SHALL record a generation rule.

## Rationale

This allows testing dependency channels without falsely claiming external validation.

## Consequences

**Positive:** development can proceed before real topology exists.

**Trade-offs:** demo wording must clearly indicate synthetic input.

## Alternatives considered

1. Pretend generated topology is `TOPOLOGY_EXTERNAL` real evidence — rejected.
2. Random topology with no generation trace — rejected.

## Implementation implications

Mock topology generators should derive plausible entities from available fields but preserve explicit synthetic provenance.

## Invariants / required tests

- Synthetic topology cannot satisfy real validation eligibility.
- `REAL_EXPORT_REPLAY` is distinguishable from `REAL_LIVE` and still passes through chaining-usage/quality validation gates.
- Same fixture/config/seed produces the same generated topology.
- Generated edges/domains include generation-rule metadata.

## References

V2.3.1 provenance/validation principles in sections 4B and 12.
