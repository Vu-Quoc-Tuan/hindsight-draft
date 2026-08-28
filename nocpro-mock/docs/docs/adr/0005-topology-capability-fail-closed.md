# ADR-MOCK-0005 — Topology mapping and semantic capability fail closed

- Status: Accepted

## Decision

Exact/verified mapping is required. Unknown mapping => UNMAPPED.

Undirected adjacency enables adjacency/hop-style source representation only; it does not create upstream/active-path semantics.

## Invariant

No fuzzy prefix mapping or shortest-path inference is used to fabricate an active path.
