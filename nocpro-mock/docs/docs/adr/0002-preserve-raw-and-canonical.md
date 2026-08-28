# ADR-MOCK-0002 — Preserve raw source values alongside canonical values

- Status: Accepted

## Decision

Every loader preserves raw fields and adds parsed/canonical fields plus quality flags.

No silent repair of timestamps or identifiers.

## Invariant

A dirty source row can always be reconstructed/audited from the mock output or retained raw store.
