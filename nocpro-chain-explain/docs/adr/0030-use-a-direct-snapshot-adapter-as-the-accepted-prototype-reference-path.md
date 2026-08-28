# ADR-0030: Use a Direct Snapshot Adapter as the accepted prototype reference path

- **Status:** Accepted — implementation sequencing decision
- **Date:** 2026-08-28
- **Scope:** Prototype transport

## Context

The research core needs a simple, deterministic way to ingest a complete snapshot before Kafka semantics are implemented. Direct JSON/file/HTTP ingestion can exercise the exact same canonical Input Contract without message-broker overhead.

## Decision

Implement a Direct Snapshot Adapter as the first supported prototype path.

It SHALL accept a complete versioned snapshot package containing the same logical records that later Kafka messages represent. It SHALL validate the Input Contract and produce the same canonical persisted/in-memory snapshot state as any future Kafka adapter.

The direct adapter is a first-class prototype path, not merely a throwaway unit-test hack.

## Rationale

This lets the team implement contracts, spec-sanity, evidence, roles and descriptors before messaging infrastructure.

## Consequences

**Positive:** very fast local iteration and deterministic fixtures.

**Trade-offs:** a later Kafka adapter must be checked for semantic equivalence.

## Alternatives considered

1. Kafka-first — rejected for implementation sequencing.
2. Direct path with a different schema — rejected because it would create two systems.

## Implementation implications

Support fixture replay modes (single snapshot / step sequence). HTTP vs file is an implementation choice; the semantic contract is identical.

## Invariants / required tests

- Same fixture via direct and Kafka paths yields identical canonical state.
- Direct adapter cannot bypass contract validation/provenance stamping.

## References

Implementation sequencing consistent with V2.3.1 snapshot model and ADR-0003.
