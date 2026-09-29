# ADR-0032: Freeze dependency evidence semantics, anti-hub specificity and failure-domain role

- **Status:** Accepted — frozen by V2.3.1 P1-Core
- **Date:** 2026-08-28
- **Scope:** Topology / dependency evidence

> **Runtime status (2026-09-28):** The pairwise `Dep_upstream`/CommonDependency
> implementation was removed because checked real replay inputs lack eligible
> directed dependency and active-path records. This ADR remains the semantic
> design reference if that capability is reconsidered; see
> [Deferred Directed Topology](../DEFERRED_DIRECTED_TOPOLOGY.md).

## Context

Topology relations have different meanings. A shared ancestor is weaker than a shared active path, and a core ancestor of half the network should not create overwhelming evidence. Failure domains are also set-valued rather than ordinary pairwise channels.

## Decision

Dependency evidence SHALL preserve relation type and semantics.

`Dep_hop`: physical/logical/service distances are not mixed. Baseline score may use `1/(1+d)` with configured D_max. Alarm→resource mapping MUST succeed first; unmapped => `⊥`.

`Dep_upstream` / CommonDependency SHALL distinguish:
`SHARED_ANCESTOR < SHARED_ACTIVE_PATH < UNAVOIDABLE_DEPENDENCY`.

This ordering is a **semantic strength** ordering (epistemic specificity of the
relation type), not a numeric constraint on `CD`. A narrow ancestor MAY score
higher than a shared active-core-path, because `CD` depends on scope
specificity and distance of the witnessing candidate `u`, not on the semantic
tier. If ranking needs the tier, store `dependency_semantic` separately from
`strength=CD`; the tier SHALL NOT be folded into `CD` as a hidden multiplier.

Capability gate:
- SHARED_ANCESTOR only when a valid directed hierarchy/dependency relation exists.
- SHARED_ACTIVE_PATH only when active-path semantics exist.
- UNAVOIDABLE_DEPENDENCY only when dominator/path semantics exist.
- Undirected device–port adjacency alone is insufficient for all three upstream/path claims.

Baseline CommonDependency, computed per capability `s ∈ {SHARED_ANCESTOR, SHARED_ACTIVE_PATH}`:

`CD_s(i,j) = max_u Specificity_s(u) * exp(-(d_s(i,u)+d_s(j,u))/lambda_dep)`

**Specificity SHALL be scope-dependent**, not a single `Desc(u)` shared across
capabilities ("descendant" is only a natural scope for hierarchy):

`Specificity_s(u) = log(1 + N_s/|Scope_s(u)|) / log(1 + N_s)`, bounded in [0,1].

- SHARED_ANCESTOR: `Scope_anc(u) = Descendants(u)` in the directed hierarchy;
  `N_anc` = total resources in that hierarchy.
- SHARED_ACTIVE_PATH: `Scope_path,t(u)` = the set of **distinct mapped
  resources** with a verified active path through `u` at path-context `t`.
  Multiple ECMP paths of the same resource through `u` SHALL count once, not
  once per path. `N_path,t` = the number of resources with a valid active-path
  observation **within that same path universe/context**, never the whole
  topology inventory (using the whole inventory as `N` while path coverage is
  partial would artificially inflate specificity).

Distance: `d_anc(i,u)` is the hop count up the hierarchy. `d_path(i,u)` is the
hop count on a verified **ordered** active path; under ECMP,
`d_path(i,u) = min` over the valid paths of `i` that pass through `u`.

**Fail-closed for SHARED_ACTIVE_PATH:** computing `CD` on this branch requires
resource mapping + verified active-path membership + ordered path/hop distance
+ snapshot/path-scope, all present. A relation known only as "A and B both
relate to path X" with no ordering/hop data MAY be reported as metadata, but
the normalized `CD` SHALL be `⊥`. Shortest path over topology adjacency SHALL
NOT substitute for a missing active-path distance — that would convert an
*observed* active path into a *possible* graph path, which D1 already forbids.

`UNAVOIDABLE_DEPENDENCY` (dominator semantics) remains P2 unless data/topology quality supports it.

Failure domains remain `H_domain` hyperedges as defined in ADR-0011.

## Rationale

This prevents topology hubs and semantic mixing from producing misleading dependency support.

## Consequences

**Positive:** interpretable dependency evidence and better weak/over-merge analysis.

**Trade-offs:** requires topology versioning, alarm-resource mapping quality and relation-type discipline.

## Alternatives considered

1. Treat any shared ancestor as strong failure dependency — rejected.
2. Mix physical/logical/service hop distances — rejected.
3. Project failure domains into a clique — rejected.

## Implementation implications

Alarm-resource mapping must carry topology layer, method, confidence, status, source version/freshness. Mapping and capability fail closed. These fields feed subtype-specific Quality evaluation under ADR-0010; missing required mapping/freshness data yields `quality_status=UNKNOWN` for validation.

Real external topology can be validation-eligible only after source-kind + chaining-usage + quality gates. External provenance alone is not independence.

## Invariants / required tests

- Specificity is always within [0,1].
- A very broad core ancestor receives lower specificity than a narrow shared dependency.
- A broad active-path hub (traversed by many distinct resources) receives lower specificity than a narrow one, mirroring the ancestor case.
- Active-path specificity counts distinct traversing resources, not ECMP path count.
- Active-path `N` is scoped to the path-observation universe, not the whole topology inventory.
- Active-path distance uses the verified ordered path, never a graph-adjacency shortest path.
- A relation with path membership but no ordered/hop semantics yields `CD=⊥`, not a graph-derived substitute.
- Shared ancestor and shared active path are distinguishable in output/provenance.
- The semantic tier ordering does not force a numeric ordering on `CD` values.
- Synthetic topology exercises the channel but cannot count as real validation.
- Unmapped alarm/resource => all affected Dep_* are UNAVAILABLE.
- Undirected adjacency cannot produce SHARED_ACTIVE_PATH/dominator.
- `chaining_usage=UNKNOWN` topology cannot validate NocPro.
- Mapping/source freshness uncertainty may allow Explain/Role/Audit according to their masks, but validation fails closed unless quality_status=PASS.

## References

V2.3.1 sections 4A, 4B, 6, 13 and 14.
