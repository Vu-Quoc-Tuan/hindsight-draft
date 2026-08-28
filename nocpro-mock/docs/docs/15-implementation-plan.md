# Implementation Plan

## P0 — Must work first

1. repository skeleton
2. canonical contract consumer
3. alarm CSV loader
4. topoIP loader
5. raw + canonical models
6. quality flags
7. Direct Snapshot producer
8. observed chaining_id replay
9. Golden 2214039 fixture
10. singleton replay path
11. deterministic scenario runner
12. contract/provenance tests

## P0.5 — Synthetic capabilities necessary for Explain testing

Implement scenario generators for:
- directed hierarchy,
- explicit active path,
- failure-domain hyperedges,
- operational context,
- controlled history,
- split/merge/recombination,
- system pair-status/raw-score edge cases.

These are **necessary test inputs** because current real exports do not cover all Explain capabilities.

## P1 — Integration

- step/fast/realtime replay,
- topology freshness controls,
- alias mapping table,
- optional Kafka producer,
- large archive extraction/profile.

## P2 — Only if useful

- partial Attribute emulator,
- verified topoIT SERVICE adapter,
- richer real context/ticket source adapters.

## Do not block P0 on

- Kafka,
- full NocPro Attribute reimplementation,
- Louvain internals,
- topoIT extraction,
- real active-path source.
