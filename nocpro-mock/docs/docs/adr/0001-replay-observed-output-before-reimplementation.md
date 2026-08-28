# ADR-MOCK-0001 — Replay observed outputs before reimplementing chaining

- Status: Accepted

## Decision

Observed NocPro chain IDs/memberships and Gray-box metadata are replayed as source facts.

The mock does not recompute Louvain/Rule chaining to reproduce an observed fixture.

## Why

Reimplementation can diverge from the system and would make downstream tests depend on an invented NocPro.

## Invariant

Golden fixture output cannot change because a local emulator algorithm changed.
