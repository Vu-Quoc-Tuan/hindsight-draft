# ADR-0003: Keep Kafka as a proposed integration transport, not a prerequisite for the research core

- **Status:** Proposed — adopt only after the direct prototype path is working
- **Date:** 2026-08-28
- **Scope:** Messaging / integration

## Context

The target integration is naturally event-oriented and replayable, so Kafka is a plausible transport. However, the research contribution is the explanation methodology, not messaging infrastructure. Making Kafka the default path from week one creates plumbing work before the Evidence Engine is testable.

Cross-topic ordering and snapshot completeness also introduce non-trivial integration semantics.

## Decision

Kafka SHALL remain **Proposed** until the direct snapshot adapter and core Evidence/WHY path are working.

When adopted, Kafka SHALL be a transport adapter around the same versioned Input Contract. The Evidence Engine, Tier-1A/Tier-1B/Tier-2 logic and persistence semantics SHALL NOT depend on Kafka APIs.

Kafka MUST NOT be required to run unit tests, spec-sanity tests, or local algorithm experiments.

## Rationale

This preserves a realistic future integration path without allowing infrastructure to dominate the P0/P1 implementation schedule.

## Consequences

**Positive:** replay and decoupling remain available later; research logic stays transport-agnostic.

**Trade-offs:** direct and Kafka adapters must be kept behaviorally equivalent.

## Alternatives considered

1. Kafka as mandatory/default path immediately — rejected due to scope risk.
2. HTTP only forever — not selected because replay/decoupling may be useful later.
3. Shared DB polling — rejected due to tight upstream coupling.

## Implementation implications

If Kafka is accepted later, define snapshot barrier/completeness semantics before analysis is triggered. Multi-topic layouts are not allowed to rely on cross-topic ordering.

## Invariants / required tests

- Core tests run with no Kafka broker.
- Kafka and direct adapters produce identical canonical snapshot state for the same fixture.
- Incomplete Kafka snapshots never trigger Tier-1A.
- Replayed duplicate events are idempotent.

## References

Implementation decision; V2.3.1 sections 1, 3 and 11 motivate snapshot/replay but do not mandate Kafka.
