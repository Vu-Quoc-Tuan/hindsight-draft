# ADR-0008: Keep pair evidence, chain descriptors and chain rule annotations type-separated

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evidence type discipline

## Context

One raw field can generate pair evidence, chain descriptors and system annotations. If those objects are treated as interchangeable players, agreement and attribution double count the same information.

## Decision

The provenance DAG SHALL distinguish:

1. Normalized pair-evidence nodes in `K_pair` (`s+`,`s-` in [0,1]).
2. Pair-scope system metadata (`M_pair`): exact-pair raw score/veto/decision/status.
3. Chain-level descriptor nodes.
4. Chain/rule system annotations (`M_chain_rule`): rule, connector/extender, merge.
5. Aggregate chain system characteristics (`M_chain_characteristic`): characteristic/value/threshold/pair_count/coverage_scope.
6. NocPro Attribute configuration (`M_attribute_config`): type/content/algorithmType/filterName/weight.

Only normalized pair-evidence nodes may participate in pair-level Agreement/G*. `M_pair`, `M_chain_rule`, `M_chain_characteristic` and `M_attribute_config` remain `SYSTEM_FACT` and are displayed separately.

Raw NocPro scores/vetoes belong to `M_pair`, not `M_attribute_config`, and SHALL NOT be normalized into Evidence-channel `s_k`. Aggregate counts belong to `M_chain_characteristic` and SHALL NOT synthesize exact pair edges. NocPro `TimeWindow`, `HistorySimilarity`, `TopologySimilarity` SHALL NOT be collapsed into the module's `T_burst/T_delay`, `H`, or `Dep_*`.

## Rationale

The mathematical contract in V2.3.1 explicitly separates pair and chain semantics.

## Consequences

**Positive:** prevents representation artifacts and circular pair consensus.

**Trade-offs:** models and APIs need explicit evidence scope/type.

## Alternatives considered

1. Flatten all evidence into generic features — rejected.
2. Project aggregate chain characteristics into pair evidence — rejected unless the source resolves exact pairs.

## Implementation implications

Use typed enums/objects such as `PAIR_EVIDENCE`, `SYSTEM_PAIR_METADATA`, `CHAIN_DESCRIPTOR`, `CHAIN_RULE_ANNOTATION`, `CHAIN_CHARACTERISTIC`, `ATTRIBUTE_CONFIG`.

`M_pair` should carry `system_pair_status ∈ {EVALUATED, NOT_EVALUATED, UNKNOWN}` when available. Missing metadata defaults to `UNKNOWN`.

## Invariants / required tests

- A chain descriptor never changes pair Agreement.
- `M_chain_rule`, `M_chain_characteristic` and `M_attribute_config` never become pair players.
- Aggregate pair counts from NocPro do not create synthetic exact pair edges.
- Raw system score `2.0` or veto `-999999999` never enters normalized Fit/Agreement/G*/Attribution.
- Missing M_pair does not become NEUTRAL.
- System TimeWindow/History/Topology and module T/H/Dep remain distinct typed objects.

## References

V2.3.1 sections 4 and 4A.
