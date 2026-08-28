# ADR-0013: Use episode-deduplicated grouping history with positive evidence only for lift > 1

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Behavioral history

## Context

Repeated snapshots of one long storm can inflate co-grouping counts. Behavioral history also cannot validate the grouping engine because it is learned from the engine's own outputs.

Data/Integration D1: NocPro `HistorySimilarity` or aggregate historical-pair characteristics, when provided by Gray-box metadata, are SYSTEM_FACT and are not the module's behavioral `H`.

## Decision

History SHALL be episode-deduplicated per evolving incident. Positive history evidence is zero when support is below `s_min` or lift≤1.

For lift>1:

`strength_H = min(1, log(lift)/log(L_cap))`

and

`reliability(s)=1-exp(-s/lambda_H)`,

with versioned parameters/backoff.

History bootstrap SHALL use a strict temporal split: history window precedes the target snapshot being explained. The target snapshot SHALL NOT enter H before its explanation/evaluation result is produced.

## Rationale

This prevents storm inflation, accidental anti-association-as-support, and same-data leakage.

## Consequences

**Positive:** behavioral support has controlled semantics.

**Trade-offs:** history requires episode/lineage awareness and temporal evaluation splits.

## Alternatives considered

1. Raw co-occurrence count — rejected.
2. Learn H from the same target snapshot — rejected as leakage.
3. Use history as validation — rejected as circular.

## Implementation implications

`bootstrap_history.py` in the mock must mark data as backfill/test state and must not act as an online feed for the target snapshot.

## Invariants / required tests

- lift≤1 => `s_H+ = 0`.
- One repeated incident episode does not count as dozens of independent history samples.
- Target snapshot is absent from the history store used to explain itself.
- A NocPro-reported historical pair count is never copied directly into `H.support` or `H.lift`.

## References

V2.3.1 sections 4A, 12 and 13.
