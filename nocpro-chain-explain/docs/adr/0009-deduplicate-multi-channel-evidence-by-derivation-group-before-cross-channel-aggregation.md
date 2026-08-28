# ADR-0009: Deduplicate multi-channel evidence by derivation group before cross-channel aggregation

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evidence aggregation

## Context

Several channels may derive from the same underlying field or evidence source. Counting them independently can inflate agreement, graph weight and attribution.

## Decision

Each pair-evidence channel SHALL carry a derivation tag. Channel support is thresholded first:

`b_k = 1[available_k and s_k+ >= theta_k]`.

Then support is deduplicated by derivation group:

`b_g = max_{k in g} b_k`.

When `b_g=1`, `s_g+` is the maximum supported channel score inside the group. `s_g-` is aggregated separately. There is no arbitrary group threshold `theta_g`.

Agreement, eligible G* weights and Evidence Coverage Attribution SHALL operate on derivation groups, not raw channels.

**Derivation-group homogeneity invariant.** Each derivation group SHALL be homogeneous in `provenance_class` and in its normalized-evidence eligibility signature (`explain_eligible`, `role_eligible`, `audit_eligible`). Channels sharing a raw `derivation_tag` but differing in provenance class or eligibility signature — for example `Dep_*` from external inventory versus `Dep_*` inferred from alarm data — SHALL be split into distinct effective derivation groups.

This makes `provenance(g)`, `audit_eligible(g)`, `role_eligible(g)` and `Agreement_external` well-defined at group level, and ensures `availability_g = max_{k in g} availability_k` aggregates only channels in the same eligibility regime, so a non-eligible channel cannot make a group appear available to Audit/Role.

The semantic group key is `(derivation_tag, provenance_class, explain_eligible, role_eligible, audit_eligible)`. Implementations need not materialize this tuple literally.

`source_kind` and `chaining_usage` are NOT part of the homogeneity key, because they constrain Validate only and do not change Explain/Role/Audit eligibility (ADR-0010). External topology with `chaining_usage=UNKNOWN` and with `CONFIRMED_NOT_USED` therefore remain the same effective derivation group.

## Rationale

This preserves the semantics of “one underlying derivation = at most one vote”.

## Consequences

**Positive:** stable results under feature representation refactoring.

**Trade-offs:** every channel must define a derivation tag.

## Alternatives considered

1. Sum/mean channels directly — rejected.
2. Max score first then compare against one group threshold — rejected because channel thresholds can differ.

## Implementation implications

Keep channel threshold provenance in config. Group aggregation must not erase the channel-level decision trace.

## Invariants / required tests

- Adding three channels derived from `reference` changes group-level support by at most one group.
- The same derivation group cannot receive three attribution players.
- Channel-specific thresholds are applied before group aggregation.
- Channels with the same `derivation_tag` but different provenance class are split into different effective groups.
- Every effective derivation group has a single eligibility signature.
- Changing `chaining_usage` does not change Explain/Role/Audit grouping.

## References

V2.3.1 sections 0, 4B and 8.4.
