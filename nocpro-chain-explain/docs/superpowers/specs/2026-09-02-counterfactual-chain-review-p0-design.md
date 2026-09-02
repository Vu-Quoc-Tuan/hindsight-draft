# Counterfactual Chain Review P0 Design

**Status:** approved for implementation  
**Date:** 2026-09-02  
**Base:** `feat/p2-topology-foundation` at `5fa099f`  
**Scope:** exact, review-only `REMOVE_MEMBER` and `SPLIT_CHAIN`

## 1. Purpose and boundary

Counterfactual Chain Review is an asynchronous subsystem downstream of the
immutable NocPro partition and the existing Tier-1/Tier-2 artifacts. It asks
whether a small local edit produces a partition that is better supported by
the same evidence engine.

It does not mutate the source partition, rewrite chain membership, overwrite
Audit results, feed a proposal back as a system fact, or run a second
clustering algorithm. Its production wording is `BETTER_SUPPORTED`,
`EXTERNALLY_SUPPORTED`, or `NO_CLEAR_ALTERNATIVE`; it never claims ground-truth
correctness without an eligible ground-truth source.

P0 supports only:

- `REMOVE_MEMBER`: remove one member from a chain and preserve it as a
  singleton.
- `SPLIT_CHAIN`: reuse a non-trivial exact Structural Audit cut.

`MOVE_MEMBER`, `ADD_MEMBER`, `ADD_CONNECTOR`, and `MERGE_CHAINS` are outside
this design.

## 2. Execution architecture

The React `REVIEW` tab first requests the latest compatible cached result. If
none exists, an explicit trigger creates an idempotent asynchronous job:

```text
React REVIEW
  -> Counterfactual Job API
  -> PostgreSQL job state
  -> Counterfactual orchestrator
       -> REMOVE branch from immutable Tier-1B artifacts
       -> SPLIT branch from exact Structural Audit cuts, when available
       -> exact affected-region recomputation
       -> hard gates and metric-vector comparison
       -> Pareto frontier
       -> external validation gate
       -> bounded recommendations
  -> versioned cached result
```

The job is snapshot-bound at creation. Every read is pinned to
`snapshot_id`, `snapshot_version`, `chain_id`, and artifact fingerprints. A
newer active snapshot cannot change an in-flight job.

Review is lazy and does not run automatically with Tier-2 Audit. `FAILED` is
reserved for infrastructure errors, unexpected exceptions, corrupt artifacts,
contract violations, or failed transactions. Capability, configuration,
calibration, data, and resource-limit outcomes are domain results.

Operations are independent. For example, `REMOVE_MEMBER` may be available
while `SPLIT_CHAIN` is unavailable because exact Structural Audit artifacts do
not exist; the overall job still succeeds.

## 3. Snapshot and artifact contract

`CounterfactualReviewInput` contains:

- snapshot ID and version;
- chain ID;
- alarm-universe fingerprint;
- analysis version;
- counterfactual engine and config versions;
- Tier-1B artifact reference and fingerprint;
- optional Structural Audit artifact reference and fingerprint;
- optional external-validation artifact reference and fingerprint.

The compatible-result cache key is a canonical fingerprint over all of these
identities. Rebuilding an input artifact with a new implementation or content
invalidates the cached Review result even when the Review config is unchanged.

## 4. Versioned configuration and calibration

All limits and improvement policies are required; the engine has no hidden
defaults:

```yaml
counterfactual:
  config_version: non_empty_string
  calibration_status: SYNTHETIC_ONLY | PRODUCTION_CALIBRATED

  limits:
    max_chain_members: positive_integer
    max_remove_candidates: positive_integer
    max_split_candidates: positive_integer
    max_recommendations: positive_integer

  remove_triggers:
    membership_support_below: unit_interval_number
    representativeness_below: unit_interval_number
    adverse_margin_below: finite_number

  improvement:
    minimum_membership_improvement: non_negative_number
    minimum_coverage_improvement: non_negative_number
    minimum_conductance_improvement: non_negative_number
    pareto_tolerance: non_negative_number
```

Missing or invalid required fields yield
`COUNTERFACTUAL_CONFIG_INCOMPLETE`. Technical limits protect computation and
materialization; improvement parameters are scientific calibration policy and
must not be conflated with limits.

A `SYNTHETIC_ONLY` config may recommend only for data explicitly labelled
`SYNTHETIC_TEST`. On production data, exact candidate metrics may still be
returned, but recommendation status is `UNAVAILABLE` with reason
`COUNTERFACTUAL_POLICY_NOT_CALIBRATED`. Synthetic parameters never enable or
calibrate production policy implicitly.

## 5. Operation availability

Each operation reports:

- `status`: `AVAILABLE`, `UNAVAILABLE`, or `NOT_APPLICABLE`;
- domain reason;
- `search_mode`: `BOUNDED` or `NOT_RUN`;
- discovered, evaluated, and rejected candidate counts;
- configured candidate limit;
- evaluated candidates.

No triggers or cuts is an exact available result with `NO_CANDIDATES` and an
empty candidate list. It is not capability failure.

For a singleton chain, both operations are `NOT_APPLICABLE`. For a two-member
chain, `SPLIT_CHAIN` is `NOT_APPLICABLE / NO_NONTRIVIAL_SPLIT`, while
`REMOVE_MEMBER` may still run. A missing, unavailable, compressed, or
non-exact Structural Audit artifact disables only `SPLIT_CHAIN`.

If `max_chain_members` is exceeded, the affected operation is unavailable with
`COUNTERFACTUAL_LIMIT_EXCEEDED`. P0 never samples or approximates exact
candidate evaluation.

## 6. Candidate generation

### 6.1 REMOVE_MEMBER

The bounded trigger union includes members identified by one or more of:

- `WEAK` membership role;
- membership support below the versioned trigger threshold;
- representativeness below the versioned trigger threshold;
- adverse contrastive margin;
- eligible external contradiction.

Trigger thresholds are versioned configuration, not engine constants. The
union is ranked deterministically. If it exceeds `max_remove_candidates`, the
engine evaluates only the configured number and records discovered/evaluated
counts and `search_mode=BOUNDED`. It does not claim a global optimum.

Connector or bridge members are not silently removed from the candidate pool;
exact after-state structural metrics and hard gates reject a removal that
damages the chain.

Removing `x` from `C` preserves the alarm universe:

```text
P' = (P - {C}) union {C - {x}} union {{x}}
```

### 6.2 SPLIT_CHAIN

Split candidates come only from deterministic, exact Structural Audit cuts.
The Review subsystem never invokes Louvain, Leiden, k-means, or another
partition search.

A cut with a singleton side is canonicalized to the corresponding
`REMOVE_MEMBER`; it is not returned twice. A `SPLIT_CHAIN` candidate therefore
has at least two members on each side.

When exact Audit supplies more cuts than `max_split_candidates`, Review reuses
Audit's deterministic ranking and evaluates the configured prefix. It records
the bounded search counts and does not claim exhaustive optimality.

## 7. Candidate identity and partition invariants

A deterministic candidate ID hashes snapshot and chain identity, operation,
canonical affected member sets, artifact fingerprints, and engine/config
versions. Member IDs and both sides of a split are canonically sorted.

Candidates store an affected partition delta rather than copying the snapshot:

- affected chains before;
- affected chains after;
- unchanged partition fingerprint;
- alarm-universe fingerprint.

Every candidate must satisfy:

- before and after alarm universes are identical;
- after chains are mutually disjoint;
- no alarm is lost or invented;
- source artifacts remain immutable.

Violation is a contract invariant failure, not a domain-level unavailable
result.

## 8. Exact affected-region evaluation

Review reuses immutable primitive evidence, including pair support,
availability, channel scores, historical models, and topology facts. It never
recomputes a primitive merely because candidate membership changed.

It exactly recomputes candidate-dependent aggregates for affected chains:

- group and membership fit;
- membership and structural roles;
- descriptor and representativeness metrics;
- evidence union coverage;
- connectivity and Audit aggregates;
- eligible external-validation summaries.

Unchanged chains and global primitive indexes are reused. Small fixtures must
prove affected-region output equivalent to full partition recomputation.

## 9. Metric vector and edit cost

Before and after states retain a typed availability value for every metric;
missing metrics are never converted to zero. The fixed P0 comparison vector is:

- `weak_member_count`, lower is better;
- `minimum_membership_support`, higher is better;
- `evidence_union_coverage`, higher is better;
- `component_count`, lower is better;
- `audit_conductance`, higher is better;
- `audit_verdict_severity`, lower is better;
- `eligible_external_contradiction_count`, which must be zero.

`audit_conductance` is the minimum exact feasible cut conductance among the
affected non-singleton chains under the same versioned Audit semantics. The
singleton produced by `REMOVE_MEMBER` is excluded because pair-based
conductance is not applicable to it. The current and candidate partitions must
both have a computable value when conductance is required by the operation
policy; otherwise the candidate yields `REQUIRED_METRIC_UNAVAILABLE`. This
prevents a skipped small-chain Audit from being interpreted as structurally
perfect. Improvement must meet `minimum_conductance_improvement`.

When an edit creates multiple affected chains, aggregation is exact and
conservative. Singleton chains created by removal remain in the partition but
are excluded from pair/structural metrics because those metrics are not
applicable to singletons. `weak_member_count` is summed, minimum membership is
the minimum computable support, union coverage is pair-count weighted as total
covered within-chain pairs divided by total within-chain pairs,
`component_count` is the maximum internal component count, conductance is the
minimum exact feasible internal conductance, and Audit severity is the maximum
(worst) affected-chain severity.

Edit cost is a structured deterministic tuple, not a weighted score:

```text
(operation_count, membership_reassignments, affected_member_count)
```

Both P0 operations have one operation. A removal has one membership
reassignment. A split has `min(|S|, |C-S|)` membership reassignments. Edit cost
is used only after evidence comparison for preference and deterministic output;
it cannot rescue an evidence-inferior candidate.

## 10. Hard gates and Pareto semantics

A candidate is rejected if it:

- violates partition invariants;
- lacks a policy-required exact metric;
- creates an eligible external contradiction;
- worsens Audit severity;
- worsens a required metric beyond configured Pareto tolerance;
- or improves no metric beyond the corresponding minimum policy delta.

Candidate A dominates B when A is no worse on every comparable required metric
and is materially better on at least one. A policy-required comparison that
cannot be computed yields `REQUIRED_METRIC_UNAVAILABLE`; missing is not neutral
or zero.

The lifecycle is:

```text
GENERATED
  -> EVALUATED
  -> HARD_GATE_REJECTED | PARETO_FRONTIER
  -> EXTERNALLY_CONTRADICTED | BETTER_SUPPORTED | EXTERNALLY_SUPPORTED
```

External evidence is evaluated only when its source, chaining-usage, and
quality gates pass. Eligible contradiction rejects a candidate. Eligible
support upgrades wording to `EXTERNALLY_SUPPORTED`. External unavailability
does not prevent an internally `BETTER_SUPPORTED` result.

## 11. Bounded frontier

Review returns the Pareto frontier up to `max_recommendations`. If the frontier
is larger, the deterministic order is:

1. externally supported candidates;
2. more metrics materially improved;
3. smaller structured edit cost;
4. `REMOVE_MEMBER` before `SPLIT_CHAIN`;
5. stable candidate ID.

The result records frontier size before limiting, recommendations returned,
and whether the frontier was truncated. Incomparable candidates may coexist;
Review does not manufacture a single winner. An empty frontier yields
`NO_CLEAR_ALTERNATIVE`.

## 12. Persistence and API

Logical persistence separates job lifecycle, result summary, candidate
evaluation, and provenance/versioning. P0 may store result/candidate details in
JSONB, but Review data must not be embedded into the Structural Audit row.

The API exposes logical operations equivalent to:

```text
POST /snapshots/{snapshot_id}/chains/{chain_id}/counterfactual-jobs
GET  /counterfactual-jobs/{job_id}
GET  /counterfactual-jobs/{job_id}/result
GET  /snapshots/{snapshot_id}/chains/{chain_id}/review
```

Submission is idempotent for a compatible cache key. The latest-review endpoint
returns only a result compatible with the pinned snapshot, chain, config, and
artifact fingerprints.

## 13. UI

The React chain view gains a `REVIEW` tab. Opening the tab first requests a
compatible result and offers or triggers evaluation when missing. It polls an
in-flight job without blocking the rest of the chain UI.

The tab shows:

- job and calibration status;
- independent REMOVE and SPLIT availability/reasons;
- bounded-search discovered/evaluated counts;
- each recommendation's operation and affected members;
- exact before/after metric table and metric availability;
- external-validation state;
- `BETTER_SUPPORTED` or `EXTERNALLY_SUPPORTED` wording;
- an explicit statement that the proposal does not mutate NocPro.

There is no Apply action in P0.

## 14. Verification and acceptance

Unit and property tests pin:

- partition conservation and disjointness;
- deterministic candidate IDs, ordering, and cache keys;
- singleton/two-member semantics;
- singleton cuts canonicalized to removal;
- unavailable Audit disables only Split;
- bounded candidate and frontier counts;
- missing metrics remain unavailable;
- Pareto dominance, hard rejection, and abstention;
- external contradiction/support gates;
- synthetic-only policy cannot recommend on production;
- affected-region equivalence with full recomputation;
- repeatability for identical inputs and versions.

Synthetic mutation acceptance requires:

- an extra-member fixture returns the expected `REMOVE_MEMBER`;
- an over-merge fixture returns the expected `SPLIT_CHAIN`;
- a clean fixture returns `NO_CLEAR_ALTERNATIVE`;
- repeated execution produces identical output.

The benchmark reports issue detection precision/recall, top-1 and top-k repair
accuracy, operation accuracy, false recommendation and abstention rates,
partition edit distance, ARI/AMI, and latency. Before production calibration,
these measurements do not create a production quality claim or threshold.

Full acceptance covers engine, async job recovery/idempotency, PostgreSQL,
FastAPI, React, synthetic Kafka ingestion, Docker, and Chromium REVIEW flow.

## 15. Non-goals and invariants

P0 does not mutate partitions, apply recommendations, scan outside the current
chain, perform a second clustering pass, sample/approximate exact evaluation,
invent production thresholds, transfer synthetic calibration to production,
fail the whole job because one operation is unavailable, or read an unpinned
active snapshot during execution.
