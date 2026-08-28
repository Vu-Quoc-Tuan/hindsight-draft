# ADR-0004: Use PostgreSQL as the proposed primary persistent store

- **Status:** Proposed — research implementation default, benchmark before production commitment
- **Date:** 2026-08-28
- **Scope:** Persistence

## Context

The platform needs persistent state for snapshots, alarms, chain memberships, descriptors, lineage, topology versions, explanation runs, provenance and configuration versions. The dominant data model is relational and versioned. Pair evidence must not be materialized globally.

## Decision

PostgreSQL SHALL be the default candidate for the research implementation.

Core structured fields SHOULD be relational; raw/flexible payloads MAY use `JSONB`. Redis, object storage, graph databases or analytical stores MAY be added only after a measured need appears.

Kafka, if used, is transport/replay and SHALL NOT replace application state.

## Rationale

PostgreSQL minimizes infrastructure while fitting snapshot/membership/versioning/provenance queries. Topology being a graph is not sufficient reason to make a graph database the primary store.

## Consequences

**Positive:** transactional integrity, mature indexing, one primary store.

**Trade-offs:** very large historical analytics or specialized graph traversal may later require complementary systems.

## Alternatives considered

1. Neo4j primary — rejected for MVP/P1.
2. ClickHouse primary — rejected because the application needs transactional relational state.
3. TimescaleDB first — deferred; alarm chaining is not primarily a metric time-series workload.

## Implementation implications

Do not design any table requiring O(N²) rows per snapshot. Pair details are lazy/cacheable. Schema migrations must preserve snapshot/config provenance.

## Invariants / required tests

- Membership rows cannot exist without corresponding snapshot/chain/alarm state.
- Ingestion is idempotent on natural identifiers.
- Every persisted explanation run identifies snapshot, engine/config version and source provenance.
- No all-pairs evidence table is created for global snapshots.

## References

V2.3.1 sections 3, 4, 7, 8 and 11.
