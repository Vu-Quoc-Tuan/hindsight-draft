# ADR-0019: Generate structural candidate cuts deterministically and score them on `G*_audit`

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Over-merge analysis

## Context

Running a second community detector would make the audit hard to explain and add another model. V2.3.1 instead defines deterministic candidate generators.

## Decision

Candidate blocks SHALL come from:
- dominant entity values,
- thresholded dependency connected components,
- failure-domain membership sets,
- extents of top non-redundant IDENTITY descriptors,
plus defined union/difference combinations.

Failure-domain membership may propose a set but SHALL NOT be clique-projected.

For each valid balanced candidate S, compute conductance on `G*_audit`:

`Phi(S)=cut_weight/min(Vol(S),Vol(Sbar))`

with balance constraints.

If no candidate yields a feasible cut with defined conductance, report the audit as `UNAVAILABLE`; do not report `NO_LOW_CONDUCTANCE_CUT`, which means at least one cut was actually scored and none crossed the calibrated threshold.

`epsilon_Phi` SHALL use conditional calibration with fallback: detailed bin if enough samples → coarser size bin → global weak baseline with low-confidence label.

For small chains where the balance rule is impossible, the result is **SKIPPED/NOT_APPLICABLE**, not “stable”.

## Rationale

The candidate source remains auditable: the system can say which evidence family proposed the split and which audit graph scored it.

## Consequences

**Positive:** deterministic, explainable and reproducible.

**Trade-offs:** may miss a cut not represented by any candidate family.

## Alternatives considered

1. Run Louvain again — rejected.
2. Spectral cut by name without implementing normalized Laplacian/Fiedler/sweep — rejected.

## Implementation implications

Log candidate source and calibration fallback level. Over-merge is a multi-evidence verdict, not conductance alone.

## Invariants / required tests

- H_domain candidate generation creates no pair edges.
- Small chain policy returns SKIPPED.
- Candidate Φ is computed only on `G*_audit`.
- Fallback calibration is explicitly labeled.

## References

V2.3.1 sections 6 and 13.
