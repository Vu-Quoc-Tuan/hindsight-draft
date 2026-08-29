# P2 Topology Foundation Design

## Scope and boundaries

This increment adds three independently observable Tier-2 results:

1. `UNAVOIDABLE_DEPENDENCY` — exact chain-level common strict-dominator
   annotation;
2. `PROPAGATION_HYPOTHESIS` — deterministic RWR ranking on an admissible alarm
   DAG; and
3. `DEPENDENCY_SCOPE_OVERLAP_SIGNAL` — set statistics anchored to the explicit
   dominator witness.

None of these results enters `G*_audit`, MembershipSupport, normalized evidence
aggregation or validation. They do not change Tier-1A or lazy Tier-1B. They run
inside the existing asynchronous per-chain Tier-2 job and are cached under the
analysis configuration version.

The current production `topoIP` export is undirected adjacency and therefore
returns `UNAVAILABLE` for all three capabilities. Synthetic directed fixtures
exercise correctness but remain `SYNTHETIC_TEST`, never production validation.

## Architecture

The implementation adds a focused `tier2/topology_hypotheses/` package:

- `dominator.py` builds one directed graph per `(source_ref, relation_type)` and
  computes chain-level common strict dominators;
- `propagation.py` constructs the alarm candidate DAG and runs configured RWR;
- `scope_overlap.py` compares mapped observed resources with the witness scope;
- `models.py` defines public statuses, reason enums and immutable results; and
- `analysis.py` orchestrates the three analyses without coupling them to audit
  graph construction.

`Tier2AuditAnalysis` receives a `topology_hypotheses` field. The API serializer
preserves every status, reason, diagnostic, configuration version and source
reference. The React Deep Dive view renders a separate "Topology hypotheses"
panel. No code path converts these records into `ChannelValue` or audit edges.

## Capability isolation

Directed graph universes are never mixed. Each universe contains only one
underlying topology source/version and one relation type. V1 accepts directed
`LOGICAL_DEPENDENCY` and directed `SERVICE_DEPENDS_ON`; `IP_ADJACENCY` is never
eligible. A source edge and target edge from different universes cannot jointly
support a witness or propagation path.

Mappings resolve only through existing `EXACT` or `VERIFIED_ALIAS` semantics.
Every alarm participating in a chain-level P2 analysis must resolve. Every
propagation alarm must also have a parseable `canonical_start_time`. Failure is
reported explicitly; mappings and timestamps are never inferred from names,
IDs, raw text or adjacency.

## Common strict dominator

For one eligible directed universe, add a virtual super-root connected to all
real indegree-zero resources. Compute dominator sets by deterministic fixed-point
iteration. Cycles are allowed by the dominator algorithm; unreachable resources,
an empty root set or a virtual super-root as the only common dominator produce
`UNAVAILABLE`.

For chain resources `R_C`, the common strict dominators are the intersection of
their strict real-resource dominator sets. The witness is the immediate common
dominator: the deepest common node in the resulting dominator tree. If that
selection is not unique, return `UNAVAILABLE / AMBIGUOUS_DOMINATOR_WITNESS`
rather than applying a lexical or score-based tie-break.

The available result contains semantic `UNAVOIDABLE_DEPENDENCY`, witness
resource, covered chain resources, source reference, relation type and
provenance. It contains no `positive_score` field and cannot be adapted to a
normalized evidence group in this increment.

## Propagation candidate DAG

Candidate nodes are alarms in the requested chain. A directed alarm edge
`a -> b` is admissible only when all conditions hold:

- both alarms map to resources in the same eligible directed universe;
- that universe contains the direct resource edge `resource(a) -> resource(b)`;
- both canonical start timestamps parse; and
- `time(a) < time(b)` strictly.

Equal or reversed timestamps do not create an edge. The engine never reverses a
topology edge to fit time. Candidate nodes and edges are sorted by stable alarm
IDs before numerical processing. If construction creates a cycle, the result is
`UNAVAILABLE / INVALID_DAG`; no edge direction is repaired. If admissible edge
count exceeds configured `max_candidate_edges`, return
`UNAVAILABLE / CANDIDATE_LIMIT_EXCEEDED` without truncation.

## Required propagation configuration

All numeric values live in the existing versioned analysis parameter registry.
The conceptual configuration is:

```yaml
propagation:
  config_version: propagation-v1
  rwr:
    restart_probability: required
    convergence_tolerance: required
    max_iterations: required
  temporal:
    decay_type: required
    decay_parameter: required
  acceptance:
    score_threshold: required
  limits:
    max_candidate_edges: required
```

The repository YAML representation retains ADR-0025 provenance for every
numeric scalar as `{value, source}`. The propagation block's
`config_version` is non-empty and recorded independently in the result.

Dependency scope has two independently required limits:

```yaml
dependency_scope:
  limits:
    max_scope_resources: required
    max_materialized_resources: required
```

Validation requires `0 < restart_probability < 1`, positive tolerance,
positive integer iterations, positive decay parameter, score threshold in
`[0,1]`, positive integer candidate-edge limit and positive integer scope
limits with `max_materialized_resources <= max_scope_resources`. V1 implements
`decay_type=exponential`; another declared policy is rejected as unsupported,
not silently treated as exponential. Any missing required field yields
`UNAVAILABLE / PROPAGATION_CONFIG_INCOMPLETE` at the Tier-2 result boundary.

## RWR contract

For candidate DAG `D=(V,E)`, source nodes are
`R={v in V | indegree(v)=0}` and restart distribution is uniform over all of
`R`. An empty source set is `UNAVAILABLE / INVALID_DAG`. Initialization is
exactly `pi(0)=r`.

For admissible edge `(u,v)`, temporal transition weight is supplied only by the
configured decay policy. For exponential decay,
`q_uv=exp(-delta_t_uv/decay_parameter)`. Outgoing weights normalize to
`P_uv=q_uv/sum_z(q_uz)`. Topology controls admissibility and adds no score.
Every dangling node redistributes its mass to restart distribution `r`.

With configured restart probability `alpha`, iteration is:

```text
pi(k+1) = alpha*r + (1-alpha)*P^T*pi(k)
```

Convergence is the L1 norm
`sum_v(abs(pi(k+1,v)-pi(k,v))) <= convergence_tolerance`. Convergence at the
configured final iteration succeeds. Exhausting `max_iterations` without that
condition returns `UNAVAILABLE / RWR_NOT_CONVERGED`; approximate results are
not emitted.

Node score is stationary probability `pi(v)`. Edge score is graph-following
flow `(1-alpha)*pi(u)*P_uv`. Only edges whose flow is at least configured
`score_threshold` appear as hypotheses. The UI labels this value
"Propagation hypothesis score", never causal probability.

Available diagnostics include candidate node/edge counts, iterations, final L1
distance, tolerance, restart probability, seed policy
`ALL_SOURCE_NODES_UNIFORM`, dangling policy `REDISTRIBUTE_TO_RESTART`, config
version and parameter provenance. Failure diagnostics retain the counts and the
last L1 distance when they exist.

## Dependency Scope Overlap

Scope analysis runs only when a unique available dominator witness exists.
`Observed(C)` is the exactly/alias-mapped chain resource set. `Scope(u)` is the
set of real descendants/reachable dependents of witness `u` within the same
directed source/relation universe; the witness itself is excluded.

The engine computes scope cardinality and intersection exactly using a compact
set/bitmap representation. It never searches for a smaller substitute witness
to pass a ceiling. If `|Scope(u)| > max_scope_resources`, the whole result is
`UNAVAILABLE / SCOPE_LIMIT_EXCEEDED` and reports actual scope count plus the
configured computation limit. It never samples or truncates scope before
computing statistics.

The result reports:

- `intersection_count = |Observed intersect Scope|`;
- `observed_coverage = |Observed intersect Scope| / |Observed|`;
- `scope_precision = |Observed intersect Scope| / |Scope|`;
- `jaccard = |Observed intersect Scope| / |Observed union Scope|`;
- `missing_resource_count = |Observed - Scope|`;
- `extra_resource_count = |Scope - Observed|`;
- sorted `missing_resources = Observed - Scope`; and
- sorted `extra_resources = Scope - Observed`.

An empty observed set or empty witness scope is unavailable with an explicit
reason. The metrics remain separate and are not collapsed into one score.

Aggregate statistics and detail materialization have separate statuses. When
both detail sets together contain at most `max_materialized_resources`,
`resource_details.status=AVAILABLE` and both complete sorted lists are returned.
When that count exceeds the limit, aggregate counts and metrics remain exact and
`AVAILABLE`, while `resource_details.status=UNAVAILABLE` with reason
`MATERIALIZATION_LIMIT_EXCEEDED`; the two exact counts remain present and no
partial list is returned. With no fault mode and no
`ExpectedAffectedObservable`, the semantic is only
`DEPENDENCY_SCOPE_OVERLAP_SIGNAL`, never Blast-Radius Validation.

## Error and status model

Each subsystem returns `AVAILABLE` or `UNAVAILABLE`; one unavailable subsystem
does not erase another available result. Reasons are stable enums, including:

- `DIRECTED_TOPOLOGY_UNAVAILABLE`;
- `RESOURCE_MAPPING_UNAVAILABLE`;
- `TEMPORAL_ORDERING_UNAVAILABLE`;
- `PROPAGATION_CONFIG_INCOMPLETE`;
- `INVALID_DAG`;
- `CANDIDATE_LIMIT_EXCEEDED`;
- `RWR_NOT_CONVERGED`;
- `COMMON_DOMINATOR_UNAVAILABLE`;
- `AMBIGUOUS_DOMINATOR_WITNESS`; and
- `DEPENDENCY_SCOPE_UNAVAILABLE`;
- `SCOPE_LIMIT_EXCEEDED`; and
- `MATERIALIZATION_LIMIT_EXCEEDED` (detail status only).

Unexpected implementation exceptions still fail the enclosing Tier-2 job as
they do today. Expected capability failures are structured results, not failed
jobs.

## Verification

Unit fixtures pin directed topology with valid time, reversed time, equal time,
cycle rejection, unmapped resources, multi-root dominators, ambiguous witness,
sink redistribution, exact RWR flow and all configuration failures. RWR tests
pin deterministic output for identical graph/config versions and provenance for
changed versions.

Scope tests pin every set and metric, witness absence, empty scope, computation
ceiling, exact aggregate/detail separation and the absence of partial lists.
Contract tests ensure undirected production-style adjacency cannot enable a P2 result.
Tier-2, serializer and React tests prove the new panel remains separate from
audit, membership and validation. Docker/browser acceptance verifies production
replay displays the three `UNAVAILABLE` reasons without console or API errors.
