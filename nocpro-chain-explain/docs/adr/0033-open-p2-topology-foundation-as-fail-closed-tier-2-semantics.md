# ADR-0033: Open the P2 topology foundation as fail-closed Tier-2 semantics

- **Status:** Accepted — explicit scope amendment
- **Date:** 2026-08-30
- **Scope:** P2 topology extensions

## Context

ADR-0029 kept P2 closed until MVP, P0, integration acceptance and performance
evidence were complete. The isolated Docker/browser acceptance now exercises
the real `nocpro-mock -> Kafka -> PostgreSQL -> Tier-1A -> Tier-1B -> Tier-2`
path, including restart and lease recovery. The project owner explicitly
authorized the first P2 increment after that gate closed.

The production topology export still provides undirected IP adjacency only.
It does not prove direction, active propagation paths or dominator semantics.
P2 implementation therefore needs synthetic ground truth and strict capability
status without presenting synthetic results as production validation.

## Decision

Open only the P2 topology foundation:

1. chain-level common strict-dominator analysis as an exact semantic
   annotation;
2. a configured, deterministic Propagation Hypothesis DAG ranked by RWR; and
3. Dependency Scope Overlap anchored only to the explicit dominator witness.

These outputs are Tier-2 semantic results. They SHALL NOT contribute to
`G*_audit`, MembershipSupport, normalized evidence aggregation or validation.
They SHALL NOT be described as causal proof, root-cause probability or a
statement that NocPro's chain is correct.

`UNAVOIDABLE_DEPENDENCY` has no normalized `positive_score` in this increment.
It reports capability, witness and provenance only. Adding it as a normalized
channel requires a later formula and eligibility ADR.

Propagation requires directed topology, exact/verified alarm-resource mapping,
canonical timestamps and every required field in a versioned propagation
configuration. Missing capability or configuration produces `UNAVAILABLE`;
there is no numeric fallback.

Dependency Scope Overlap uses the explicit chain-level common strict dominator.
It reports intersection counts, coverage, precision, Jaccard, missing resources
and extra resources separately. It does not search topology for a witness that
maximizes overlap and does not collapse those metrics into one score.
Exact aggregate statistics and full resource-list materialization are separate:
a materialization ceiling may hide both full lists while retaining exact counts
and overlap metrics. Exceeding the computation ceiling makes the scope analysis
unavailable; neither ceiling permits sampling or witness substitution.

## Rationale

This opens useful P2 research without weakening the project's epistemic
boundaries. Exact semantic annotations can be tested on synthetic directed
topologies while the real undirected export continues to fail closed.

## Consequences

**Positive:** P2 gains deterministic topology analysis, complete provenance and
operator-visible reasons for unavailability.

**Trade-offs:** production output remains unavailable until a real directed
topology/path capability is supplied. The annotations cannot strengthen roles,
audit edges or validation verdicts.

## Invariants / required tests

- Undirected `IP_ADJACENCY` cannot enable any P2 topology capability.
- Unmapped or ambiguously mapped alarms make the affected analysis unavailable.
- Synthetic topology is labeled synthetic and cannot validate production.
- Dominator annotations carry no normalized score or audit vote.
- Propagation uses the configured RWR contract and never hard-codes parameters.
- Scope overlap has an explicit dominator witness or is unavailable.
- Scope aggregate statistics remain exact when detail materialization is
  unavailable; no partial list is presented as complete.
- No P2 topology output uses causal or root-cause wording.

## References

V2.3.1 sections 8 and 14; ADR-0010, ADR-0015, ADR-0016, ADR-0023,
ADR-0025, ADR-0026, ADR-0029 and ADR-0032.
