# ADR-0027: Treat `spec_sanity` tests as executable methodology invariants

- **Status:** Accepted — governance decision
- **Date:** 2026-08-28
- **Scope:** Testing / methodology protection

## Context

The final spec contains invariants that are easy to violate accidentally, especially when code is written by multiple contributors or AI assistants. Markdown alone does not prevent regression.

## Decision

Create `tests/spec_sanity/` as a methodology firewall. These tests SHALL encode invariants that must remain true regardless of implementation refactoring.

The suite is distinct from ordinary unit/performance tests: failure means the implementation contradicts the frozen methodology.

## Rationale

Executable invariants make the design enforceable.

## Consequences

**Positive:** prevents silent methodological drift.

**Trade-offs:** tests must be maintained when the frozen spec intentionally changes.

## Alternatives considered

1. Rely only on code review/docs — rejected.
2. Put all checks in generic unit tests with no semantic grouping — rejected because methodology regressions become hard to recognize.

## Implementation implications

Minimum suite should include:
- SYSTEM_FACT not audit-eligible.
- BEHAVIORAL not validation-eligible.
- synthetic source not real-validation eligible.
- derivation-group dedup.
- descriptor/rule annotation not pair players.
- UNAVAILABLE != NEUTRAL.
- unavailable member not mislabeled WEAK.
- WEAK requires >=2 computable role groups.
- H_domain not clique-projected but may propose cut.
- visualization pruning does not change audit.
- multimodal midpoint temporal score low.
- directed delay not reversed.
- history lift<=1 gives zero positive.
- target snapshot not used to bootstrap its own history.
- small-chain over-merge is SKIPPED.
- CONFIG_DRIFT != DATA_DRIFT.
- attribution players are groups.
- large-chain attribution avoids C(n,2) materialization.
- external evidence with `chaining_usage=UNKNOWN` cannot validate.
- external evidence with `chaining_usage=CONFIRMED_USED` cannot validate.
- raw NocPro score/veto never enters normalized `s_k`.
- system `TimeWindow/HistorySimilarity/TopologySimilarity` remain distinct from module `T/H/Dep`.
- missing M_pair defaults to UNKNOWN/UNAVAILABLE, not NEUTRAL.
- unmapped alarm→topology gives `Dep_*=⊥`.
- undirected adjacency does not enable SHARED_ACTIVE_PATH/dominator.
- golden chain 2214039 may generate a two-block candidate but is not hard-coded as over-merge ground truth.
- `SYNTHETIC_TEST` and `BACKFILL` cannot validate.
- `REAL_EXPORT_REPLAY` does not validate unless all later gates pass.
- `quality_status=UNKNOWN/FAIL` cannot validate.
- `chaining_usage` is resolved in source-version + chaining-config/run context; a coarse store-level flag is insufficient.
- `chaining_usage` changes do not alter Explain/Role/Audit masks.
- raw system pair score/veto belongs to `M_pair`; attribute configuration fields belong to `M_attribute_config`.
- aggregate system pair-count characteristic belongs to `M_chain_characteristic` and does not create exact pair edges.
- singleton chain never becomes WEAK because pair evidence is unavailable.
- singleton Pair WHY / connector / over-merge returns NOT_APPLICABLE, not ERROR/stable.
- same `derivation_tag` with different provenance class splits into different effective derivation groups.
- every effective derivation group has a single eligibility signature.
- `chaining_usage` changes do not alter Explain/Role/Audit grouping.


## Invariants / required tests

- Every frozen invariant above has an automated test.
- Failing a spec-sanity test blocks merge unless the spec/ADR is intentionally revised first.

## References

V2.3.1 section 13 plus all methodology ADRs.
