# ADR-0025: Version all analysis configuration and record parameter provenance

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Configuration governance

## Context

The methodology contains many thresholds and scales. Hardcoding them across engines would make results irreproducible and would break CONFIG_DRIFT semantics.

## Decision

All analysis parameters SHALL live in versioned configuration, e.g. `config/thresholds/v1.yaml`.

Each parameter SHALL record value and source category where applicable:
- `SYSTEM_PROVIDED`
- `DATA_DRIVEN`
- `DOCUMENTED_DEFAULT`

Model-selection outcomes and threshold provenance SHALL be stampable into explanation provenance.

Every explanation/cache/run SHALL record `config_version`.

## Rationale

Versioned configuration is required for traceability, sensitivity analysis and correct drift labeling.

## Consequences

**Positive:** reproducibility and auditability.

**Trade-offs:** config migration/version management becomes part of the codebase.

## Alternatives considered

1. Constants inside engine code — rejected.
2. One unversioned runtime config — rejected.

## Implementation implications

Ship a concrete `v1.yaml` baseline before implementing multiple engines. Sensitivity analysis reads the same parameter registry.

## Invariants / required tests

- No methodology threshold exists only as an anonymous code literal.
- Re-running a snapshot with the same code/config is deterministic.
- Config changes are visible to drift logic.

## References

V2.3.1 sections 4A, 4B, 7, 11 and 13.
