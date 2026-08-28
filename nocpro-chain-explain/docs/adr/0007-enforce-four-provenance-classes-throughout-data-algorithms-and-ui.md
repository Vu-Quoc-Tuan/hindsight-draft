# ADR-0007: Enforce four provenance classes throughout data, algorithms and UI

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Provenance model

## Context

Evidence from system metadata, raw alarm analysis, learned grouping behavior and external operational sources has different epistemic meaning. Combining them without labels creates circular validation.

## Decision

The system SHALL enforce exactly these top-level provenance classes:

- `SYSTEM_FACT`
- `POST_HOC`
- `BEHAVIORAL`
- `EXTERNAL_OPERATIONAL`

Subtypes MAY refine them, such as `TOPOLOGY_EXTERNAL`, `TICKET`, `MAINTENANCE`, `OPERATOR_LABEL`, `FAULT_INJECTION`.

`source_kind` is a separate dimension with baseline values `REAL_LIVE`, `REAL_EXPORT_REPLAY`, `SYNTHETIC_TEST`, `BACKFILL`. `BACKFILL` means bootstrap/training/backfill state; old-but-real observations replayed for evaluation use `REAL_EXPORT_REPLAY`.

`chaining_usage` is another metadata dimension: `CONFIRMED_USED`, `CONFIRMED_NOT_USED`, `UNKNOWN`. It is not a fifth provenance class. `EXTERNAL_OPERATIONAL` does not imply `CONFIRMED_NOT_USED`.

`quality_status ∈ {PASS, FAIL, UNKNOWN}` is also not a provenance class; it is an eligibility result computed from subtype-specific Quality fields under a versioned config.

## Rationale

The four-way separation is the central anti-circularity rule of V2.3.1.

## Consequences

**Positive:** claims remain auditable and validation is not self-confirming.

**Trade-offs:** every evidence producer must stamp provenance correctly.

## Alternatives considered

1. A single “independent evidence” class — rejected because raw fields may be chaining features.
2. Treat history as external validation — rejected as circular.

## Implementation implications

Provenance must be present in schemas, evidence objects, persisted claims and UI drill-down.

## Invariants / required tests

- Raw alarm-derived equality/burst/semantic evidence is not labeled independent.
- Grouping history is BEHAVIORAL.
- System metadata is not used as external validation.
- EXTERNAL_OPERATIONAL with `chaining_usage=UNKNOWN` is not treated as independent validation.
- `SYNTHETIC_TEST` and `BACKFILL` cannot validate; `REAL_LIVE`/`REAL_EXPORT_REPLAY` only enter the next validation gates.

## References

V2.3.1 sections 0, 4 and 12.
