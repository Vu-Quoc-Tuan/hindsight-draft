# ADR-0029: Freeze implementation scope: MVP/P0 first, P1-Core minimum bar is 3+1

- **Status:** Accepted — frozen by V2.3.1 scope
- **Date:** 2026-08-28
- **Scope:** Project scope / schedule

## Context

The methodology contains more features than one person should implement in one term. Treating every Accepted ADR as a mandatory feature backlog would create schedule failure and push effort into infrastructure or optional extensions.

## Decision

Implementation SHALL follow the scope hierarchy in V2.3.1.

MVP and P0-complete must form a usable project before P1.

MVP SHALL explicitly include:
- Gray-box NocPro Metadata Adapter for rule/merge/connector-extender/Attribute config/aggregate characteristics and optional exact `M_pair`; simiDict/A_ij/ΔQ are not required.
- A first-class singleton path: `|C|=1` still supports chain overview/system facts/descriptors/evolution; pair/connector/over-merge operations return NOT_APPLICABLE and singleton is not labeled WEAK merely due to unavailable pair evidence.

P1-Core minimum bar is exactly the committed 3+1:
1. CommonDependency capability engine + Specificity anti-hub + H_domain explanation; SHARED_ANCESTOR/SHARED_ACTIVE_PATH are enabled only when the corresponding topology semantics exist, otherwise `UNAVAILABLE`.
2. Multi-evidence over-merge verdict.
3. Similar Chains baseline.
4. Tier-1A Explanation Drift.

P1-optional and P2 features are stretch/data-gated and SHALL NOT block project completion.

Accepted methodology ADRs constrain how a feature is implemented **if/when the feature exists**; they do not imply that all optional features must be completed.

## Rationale

This aligns architecture governance with the explicit one-person/one-term commitment.

## Consequences

**Positive:** protects research contribution and schedule.

**Trade-offs:** some architecture hooks will exist before their optional feature is implemented.

## Alternatives considered

1. Implement all ADR-described features before demo — rejected.
2. Prioritize Kafka/UI polish over core evidence — rejected.

## Implementation implications

Backlog labels should map every issue to MVP, P0, P1-Core, P1-Optional or P2.

## Invariants / required tests

- A P0 demo does not fail because Kafka/LLM/full KEDB are absent.
- A P0/MVP demo is incomplete if it crashes/mislabels the common singleton path or if Gray-box metadata is only hard-coded rather than ingested through the adapter contract.
- P1 completion is judged against the 3+1 core bar.
- P1 is not considered incomplete merely because a dataset lacks active-path semantics; the engine must fail closed to UNAVAILABLE rather than fabricate output.
- Optional features cannot become hidden prerequisites for core endpoints.

## References

V2.3.1 section 14.
