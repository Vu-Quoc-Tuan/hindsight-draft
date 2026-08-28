# ADR-MOCK-0007 — Direct Snapshot is the reference prototype output

- Status: Accepted

## Decision

Implement complete canonical snapshot output first.

Kafka is an optional transport adapter later and must preserve identical semantics.

## Invariant

Core mock tests run with no Kafka broker.
