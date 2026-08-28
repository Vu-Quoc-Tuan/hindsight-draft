# Hybrid Indexed/Sufficient-Statistics Execution with Pairwise Oracle

**Status:** Approved design, awaiting written-spec review

**Date:** 2026-08-28

**Scope:** `nocpro-chain-explain` Tier-1 statistical execution, bounded Tier-1B analysis, pair-on-click, Tier-2 audit boundary, equivalence testing, and performance measurement

## 1. Goal

Replace dense all-pairs evaluation as the default Tier-1 execution path with semantics-preserving indexed or sufficient-statistics implementations. Preserve the existing pairwise implementation as a small-chain correctness oracle and as the evaluator for explicitly requested pairs.

The governing performance invariant is:

> No default dense pair scan.

This design does not change the methodology formulas, derivation-group rules, role semantics, temporal semantics, audit verdict semantics, contrastive math, or provenance rules.

## 2. Execution policy

1. Indexed/sufficient-statistics execution is the default for all Tier-1 statistical and membership computations.
2. Pairwise evaluation is not a production default path. It is retained for:
   - small-chain correctness-oracle tests;
   - pair-on-click evaluation;
   - debugging and explicit equivalence checks.
3. Each channel must provide either:
   - a semantics-preserving indexed implementation; or
   - `UNAVAILABLE`.
4. A channel must not silently fall back to dense all-pairs evaluation, regardless of chain size.
5. Tier-1B consumes reusable indexes and sufficient statistics and performs only bounded or local materialization.
6. Full `G*_audit` materialization and structural-robustness analysis belong to Tier-2.
7. Indexed and pairwise implementations must be equivalent on small fixtures for every observable result covered by both implementations.

`EXACT_INDEXED` means that every channel reported as available has exact indexed statistics. It does not imply that every possible channel is available.

## 3. Complexity contract by capability

The design does not claim that every channel is O(N). Complexity depends on the evidence family:

| Capability | Indexed strategy | Expected shape |
|---|---|---|
| `E_reference`, `E_device`, `E_card`, `E_site`, `E_remote`, exact-name `S` | Hash/group counts | Approximately O(N) |
| `T_burst` | Contextual segmentation plus group counts | O(N log N), or O(N) when input is already ordered |
| `T_delay` | Sorted/range/local-mass index | Data- and index-dependent |
| `Dep_hop` | Precomputed topology neighborhoods/postings | Sparse-topology dependent |
| `Dep_upstream` | Ancestor/active-path inverted postings | Posting-size dependent |
| Historical association `H` | Sparse historical association index | Sparse-history dependent |

If the required fitted distribution, topology semantics, mapping, path observation, or history is absent, the capability is `UNAVAILABLE`. Missing capability data is never converted to a neutral or zero-valued fit.

## 4. Semantic invariants

The indexed path must preserve the following order and meanings exactly:

```text
channel availability
  -> SUPPORT / NEUTRAL / UNAVAILABLE
  -> channel threshold
  -> derivation-group deduplication
  -> Fit_k
  -> Fit_g
  -> eligibility mask
  -> MembershipSupport
  -> role gate and verdict
```

For each member and channel, the indexed denominator is the number of computable peers for that member and channel, not the total chain size. A missing field on either endpoint removes that pair from the channel domain; it does not contribute a neutral observation.

Multiple channels with the same effective derivation group still contribute one group after deduplication. Indexed posting lists must not allow representational duplication to increase a group's weight.

## 5. Execution result modes

The execution result exposes three independent fidelity dimensions:

```text
statistics_mode:
  EXACT_INDEXED
  APPROXIMATED
  UNAVAILABLE

audit_graph_mode:
  NOT_COMPUTED
  EXACT_FULL
  SPARSIFIED
  SUPERNODE

pair_materialization:
  ON_DEMAND
  BOUNDED
  TRUNCATED
```

These modes describe different guarantees and must not be collapsed into one boolean. Tier-1B normally returns `audit_graph_mode=NOT_COMPUTED`. Pair detail returned for a bounded panel must identify its materialization mode and limit.

## 6. Tier boundaries

### Tier-1A

Tier-1A builds reusable snapshot-scoped indexes, grouped counts, contextual burst assignments, predicate indexes, and caches. It performs no dense pair scan.

### Tier-1B

Tier-1B performs:

- indexed membership statistics and roles;
- descriptor and contrastive analysis over reusable indexes;
- bounded/basic component and connectivity summaries;
- pair-on-click evaluation for explicitly requested pairs;
- no full `G*_audit` materialization.

Any basic structural output in Tier-1B must remain implicit or compressed. It must not expand large postings into clique edge lists. Tier-1B does not wait for Tier-2.

### Tier-2

Tier-2 owns:

- `G*_audit` evaluation;
- exact or compressed audit execution according to configured policy;
- conductance, over-merge, and structural-robustness analysis;
- explicit reporting of `EXACT_FULL`, `SPARSIFIED`, or `SUPERNODE` mode.

The exact/compressed policy and thresholds are derived from benchmark evidence. An inverted group of size 1,000 remains compressed unless edge expansion is explicitly allowed; an inverted representation does not make its approximately 500,000 clique edges cheap.

## 7. Components and data flow

### 7.1 Channel indexed providers

Each supported channel exposes a provider that returns per-member sufficient statistics:

- availability;
- computable domain size;
- supporting count;
- channel identifier;
- derivation tag;
- provenance class;
- any configuration/version identity required to reproduce the result.

Unsupported or data-gated providers return explicit unavailable results.

### 7.2 Indexed aggregation

The aggregator converts provider outputs into the existing `ChannelFit`, `GroupFit`, and `MembershipSupport` output shapes. Downstream role classification therefore retains its public input contract.

The aggregation layer performs derivation grouping and eligibility exactly once. Providers do not pre-average across derivation groups.

### 7.3 Pair detail service

Pair evaluation becomes an explicit operation accepting two alarm IDs. It uses the reference channel evaluators and returns the complete per-channel WHY detail for that requested pair. A bounded multi-pair request must require an explicit limit and report truncation.

### 7.4 Contrastive execution

For a member `x` and rival chain `C'`, `Fit_g(x,C')` queries group membership and availability counts instead of enumerating `x` against every rival member. `Margin_common` uses only the intersection of computable derivation groups in the target and rival. A missing rival group remains unavailable and is never treated as zero.

### 7.5 Tier-2 audit representation

Tier-2 derives supported pair predicates from compressed postings such as common reference, burst, semantic family, or topology neighborhood. It preserves thresholding, derivation deduplication, provenance eligibility, and the required number of distinct audit-eligible groups before declaring an audit edge.

## 8. Migration strategy

1. Keep the current pairwise evaluator unchanged as the reference implementation.
2. Stabilize indexed provider and aggregation interfaces and export them through `groups`.
3. Add equivalence tests before switching orchestration.
4. Switch Tier-1B membership and contrastive computations to indexed execution by default.
5. Replace eager pair detail with explicit bounded/on-demand materialization.
6. Remove full audit construction from Tier-1B results and mark it `NOT_COMPUTED`.
7. Add the Tier-2 audit entry point with an explicit execution policy; do not invent an unbenchmarked large-chain threshold.
8. Update execution wording in the methodology-facing documentation without changing mathematical semantics.

No automatic fallback to the old dense path is permitted after the default switch. A debug-only oracle invocation must be explicit.

## 9. Error handling and fail-closed behavior

- Missing provider inputs produce `UNAVAILABLE` with a reason.
- Unsupported taxonomy-aware semantic indexing produces `UNAVAILABLE` unless exact semantics can be preserved; it does not silently downgrade to exact-name equality when a taxonomy was requested.
- Missing topology mapping does not create neutral dependency evidence.
- A provider/config version mismatch fails rather than mixing incompatible statistics.
- A request that would exceed a pair materialization limit returns bounded/truncated metadata or is rejected; it never silently expands all pairs.
- Tier-1B callers requesting full structural audit receive an explicit Tier-2-required status.

## 10. Correctness verification

The pairwise evaluator is the slow, simple correctness oracle. Equivalence coverage includes:

- synthetic tiny chains;
- Golden-compatible synthetic subsets that preserve sourced semantics; the current
  aggregate-only Golden fixture is not by itself a pairwise-equivalence input;
- real chains with approximately 20 and up to 50 members;
- deterministic randomized/property cases.

Boolean and status outputs must match exactly. Floating-point outputs must match within a documented tolerance.

The equivalence suite compares:

- channel availability;
- SUPPORT and NEUTRAL decisions;
- computable domain and supporting counts;
- `Fit_k`;
- `Fit_g` after derivation deduplication;
- `MembershipSupport`;
- membership gate and verdict;
- contrastive statistics and `Margin_common`;
- requested pair WHY output;
- audit-edge support predicates on small chains.

Mutation-style guards must demonstrate that removing an availability filter, treating missing as zero, changing a denominator to total peers, or bypassing derivation deduplication causes the equivalence suite to fail.

All existing tests and methodology `spec_sanity` tests remain required.

## 11. Benchmark and acceptance criteria

Benchmark workloads include chain sizes:

```text
1, approximately 10, approximately 50,
approximately 200, approximately 500, and 1,072
```

Reports separate:

- source/package load time;
- index build time;
- Tier-1B cache/index-hit latency;
- membership and role latency;
- contrastive latency;
- pair-on-click latency;
- memory peak;
- Tier-2 audit time and execution mode.

Percentiles must use enough repetitions and a documented percentile method. Three samples must not be labeled a reliable P95.

Acceptance requires:

1. Indexed/oracle equivalence for every supported observable listed above.
2. No default dense pair scan in Tier-1A or Tier-1B.
3. All existing suites pass.
4. Benchmark reports are reproducible and preserve singleton/common-path performance.
5. The 1,072-member result is reported honestly against the `<5s` Tier-1B design objective; the implementation must not claim success if the measured result misses it.
6. Tier-2 audit performance is reported separately and cannot be hidden inside a Tier-1B total.

## 12. Documentation changes

Implementation wording will be aligned in:

- methodology section 3, tier execution;
- methodology section 11, performance/data design;
- ADR-0014;
- ADR-0015;
- benchmark documentation and executable `spec_sanity` invariants.

These patches clarify execution architecture only. They do not change Fit formulas, evidence semantics, roles, `T_delay`, `T_burst`, `G*` semantics, audit verdicts, contrastive math, or provenance.

## 13. Non-goals

- Adding HTTP API, persistence, or web UI in this implementation cycle.
- Implementing Kafka or realtime replay.
- Claiming every channel is O(N).
- Making unavailable evidence neutral.
- Building full Tier-1B audit graphs.
- Removing the pairwise oracle.
- Revising the frozen methodology mathematics.
