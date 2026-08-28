# ADR-0010: Apply source-kind gating before the Explain/Role/Audit/Validate eligibility mask

- **Status:** Accepted — frozen methodology plus synthetic-source implementation guard
- **Date:** 2026-08-28
- **Scope:** Eligibility / anti-circularity

## Context

V2.3.1 defines different eligibility for system, post-hoc, behavioral and external operational evidence. Development fixtures add another dimension: synthetic sources can have the same structural shape as real external topology/tickets but must not be counted as operational validation.

## Decision

Validation SHALL be evaluated in four fail-closed stages:

1. **Source-kind gate** — only `REAL_LIVE` and `REAL_EXPORT_REPLAY` may proceed toward validation. `SYNTHETIC_TEST` and `BACKFILL` => Validate NO.
2. **Chaining-usage / independence gate** — validation requires `chaining_usage=CONFIRMED_NOT_USED`. `UNKNOWN` and `CONFIRMED_USED` => Validate NO.
3. **Provenance/subtype gate** — the subtype must be validation-eligible.
4. **Quality gate** — validation requires `quality_status=PASS`; `FAIL`/`UNKNOWN` => Validate NO. Quality thresholds are subtype-specific and versioned.

`chaining_usage` constrains **Validate only**. Explain/Role/Audit continue to follow their provenance/type masks.

Default methodology:
- POST_HOC: Explain yes, Role yes, Audit yes, Validate no.
- EXTERNAL_OPERATIONAL/TOPOLOGY_EXTERNAL: Explain yes, Role yes, Audit yes, Validate yes **only when source_kind∈{REAL_LIVE,REAL_EXPORT_REPLAY}, chaining_usage=CONFIRMED_NOT_USED, subtype allows validation, and quality_status=PASS**.
- SYSTEM_FACT: displayed separately; Role/Audit/Validate no by default.
- BEHAVIORAL: Explain yes with label; Role/Audit/Validate no by default.
- Ticket/operator/maintenance/fault-injection: explain/validate according to subtype; no positive structural audit edge by default.

## Rationale

The combined source-kind + chaining-usage + Quality gates prevent synthetic self-validation, real-but-not-independent topology/history, and low/unknown-quality sources from validating NocPro.

## Consequences

**Positive:** preserves evaluation validity.

**Trade-offs:** eligibility is multi-dimensional rather than one enum lookup.

## Alternatives considered

1. Provenance-only eligibility — rejected because synthetic external-shaped data can leak into validation.
2. Filter synthetic results after scoring — rejected because the contamination has already occurred.

## Implementation implications

Implement one central eligibility service/library; do not duplicate ad-hoc checks in engines.

`chaining_usage` SHALL be resolved using source identity/version plus chaining configuration/run context (executed rule/attribute set when known). It SHALL NOT be a single coarse USED/NOT_USED property for an entire topology/history store. If complete executed config is unavailable, resolve `UNKNOWN`.

## Invariants / required tests

- `SYNTHETIC_TEST + TOPOLOGY_EXTERNAL` cannot produce a real validation verdict.
- `BACKFILL + EXTERNAL_OPERATIONAL` cannot produce a validation verdict.
- `REAL_EXPORT_REPLAY` may proceed to later gates but does not automatically validate.
- `EXTERNAL_OPERATIONAL + chaining_usage=UNKNOWN` cannot produce a validation verdict.
- `EXTERNAL_OPERATIONAL + chaining_usage=CONFIRMED_USED` cannot produce a validation verdict.
- `quality_status=UNKNOWN` or `FAIL` cannot produce a validation verdict.
- Changing `chaining_usage` must not change Explain/Role/Audit eligibility for the same evidence object.
- SYSTEM_FACT support does not strengthen `G*_audit`.
- BEHAVIORAL support does not change external Agreement.

## References

V2.3.1 sections 4B and 12; synthetic guard supports development without violating those rules.
