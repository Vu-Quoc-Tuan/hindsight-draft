# ADR-0012: Use contextual burst segmentation and directed local-mass delay typicality

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Temporal evidence

## Context

Two temporal signals are needed: contextual burst membership and learned delay compatibility. Global burst segmentation is invalid for a nationwide continuous stream, and CDF centrality fails on multimodal delay distributions.

Data/Integration D1: NocPro's own `TimeWindow` Attribute is a SYSTEM_FACT with system semantics (including veto) and is not the same object as `T_burst` or `T_delay`.

## Decision

`T_burst` SHALL segment within a blocking context such as region/site/resource neighborhood/service domain, using configured silent-gap/change-point logic. It SHALL NOT segment the entire global alarm stream as one sequence.

`T_delay` SHALL use directed delay `Δt = t_B - t_A` for relation A→B. Typicality SHALL use normalized local probability mass:

`s+(Δt) = P_r(|T-Δt|<=h) / max_t P_r(|T-t|<=h)`.

CDF may be used only for tail extremeness, not typicality.

Histogram/KDE/fitted likelihood choice and bandwidth `h` SHALL be model-selected/validated on held-out data when enough data exists; otherwise a documented backoff/default is used and stamped in config.

## Rationale

These rules directly address the multimodal midpoint failure and directionality problem in the final spec.

## Consequences

**Positive:** semantically correct temporal evidence.

**Trade-offs:** temporal models need backoff and calibration data.

## Alternatives considered

1. Global silent-gap burst segmentation — rejected.
2. `2*min(F,1-F)` typicality — rejected for multimodal distributions.
3. Undirected absolute delay only — rejected when relation direction is known.

## Implementation implications

Backoff: type→family→category. Threshold/model source must be labeled domain/data-driven/behavioral as appropriate.

## Invariants / required tests

- Bimodal `{~2s,~100s}` gives low typicality near 50s.
- A system-provided `TimeWindow <600s` characteristic does not become `T_burst`/`T_delay` evidence.
- A→B learned delay does not automatically match B→A.
- Burst membership changes when the blocking context changes, not because unrelated national alarms fill the gap.

## References

V2.3.1 sections 4A and 13.
