# ADR-MOCK-0004 — Synthetic augmentation is scenario-scoped and never mutates Golden fixtures

- Status: Accepted

## Decision

Golden fixtures are immutable.

To test missing topology/history/context capability, create a separate scenario or clone with explicit mutation list and `source_kind=SYNTHETIC_TEST`.

## Invariant

`golden_2214039` remains unmapped to current topoIP even if a dependency-test variant exists.
