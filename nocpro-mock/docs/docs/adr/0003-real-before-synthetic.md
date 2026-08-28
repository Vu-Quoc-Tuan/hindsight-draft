# ADR-MOCK-0003 — Prefer real exports before synthetic generation

- Status: Accepted

## Decision

Use real alarm/topology exports whenever they cover the required capability.

Synthetic data is only for missing capability, known-ground-truth edge cases, and contract testing.

## Invariant

A synthetic edge/context object is never presented as a real-export object.
