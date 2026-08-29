# P2 Topology Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fail-closed Tier-2 dominator annotations, configured RWR propagation hypotheses and exact dependency-scope overlap without changing normalized evidence, audit, membership or validation.

**Architecture:** Add a self-contained `tier2/topology_hypotheses` package and project its immutable results through the existing Tier-2 job, FastAPI serializer and React Deep Dive panel. Optional P2 configuration is parsed without preventing application startup; absent or incomplete P2 config becomes a structured `UNAVAILABLE` result. Algorithms operate per topology source/version/relation universe and never consume undirected IP adjacency.

**Tech Stack:** Python 3.12 dataclasses and standard library, existing YAML configuration loader, pytest, FastAPI/Pydantic, React 19/TypeScript, Vitest, Playwright.

## Global Constraints

- Follow ADR-0033 and `docs/superpowers/specs/2026-08-30-p2-topology-foundation-design.md` exactly.
- Production `IP_ADJACENCY` remains unavailable; no direction, mapping, timestamp, score or config value may be inferred.
- `UNAVOIDABLE_DEPENDENCY`, `PROPAGATION_HYPOTHESIS` and `DEPENDENCY_SCOPE_OVERLAP_SIGNAL` never enter `ChannelValue`, `G*_audit`, MembershipSupport or validation.
- RWR has no code defaults: every numeric input and `decay_type` comes from a complete versioned configuration.
- Scope computation and resource-list materialization use separate ceilings; neither path samples or truncates.
- Every task uses TDD and ends in an independently reviewable commit.

---

### Task 1: Optional versioned P2 topology configuration

**Files:**
- Modify: `services/analysis-worker/configuration/analysis_config.py`
- Modify: `services/analysis-worker/configuration/__init__.py`
- Test: `tests/test_analysis_config.py`

**Interfaces:**
- Produces: `PropagationConfig`, `DependencyScopeConfig`, and `P2TopologyConfig` immutable dataclasses.
- Produces: `AnalysisConfig.p2_topology: P2TopologyConfig`, whose incomplete fields are represented by `None` plus stable diagnostics rather than an application-startup exception.
- Preserves: the current required P0/P1 parameter registry and shipped `config/thresholds/v1.yaml` unchanged, so production P2 starts fail-closed.

- [ ] **Step 1: Write failing configuration tests**

Add tests proving an absent block loads with unavailable P2 configuration, a complete block preserves every value/source, and each missing field records `PROPAGATION_CONFIG_INCOMPLETE`. Add validation tests for `0 < alpha < 1`, positive tolerance/iterations/decay/limits, threshold in `[0,1]`, `max_materialized_resources <= max_scope_resources`, non-empty P2 config versions and `decay_type == exponential`.

```python
def test_shipped_config_keeps_p2_fail_closed():
    config = load_analysis_config(SHIPPED_CONFIG)
    assert config.p2_topology.propagation is None
    assert config.p2_topology.propagation_reason == "PROPAGATION_CONFIG_INCOMPLETE"
    assert config.p2_topology.dependency_scope is None

def test_complete_p2_config_preserves_parameter_provenance(tmp_path):
    config = load_analysis_config(_write(tmp_path, COMPLETE_P2_YAML))
    assert config.p2_topology.propagation.config_version == "propagation-test-v1"
    assert config.p2_topology.propagation.restart_probability.value == 0.2
    assert config.p2_topology.propagation.restart_probability.source is ParameterSource.DATA_DRIVEN
    assert config.p2_topology.dependency_scope.max_materialized_resources.value == 100
```

- [ ] **Step 2: Run configuration tests and confirm failure**

Run: `.venv/bin/python -m pytest tests/test_analysis_config.py -q`

Expected: FAIL because `AnalysisConfig` has no `p2_topology` field.

- [ ] **Step 3: Implement optional strict parsing**

Add dataclasses whose numeric fields remain `ConfiguredValue`:

```python
@dataclass(frozen=True)
class PropagationConfig:
    config_version: str
    restart_probability: ConfiguredValue
    convergence_tolerance: ConfiguredValue
    max_iterations: ConfiguredValue
    decay_type: str
    decay_parameter: ConfiguredValue
    score_threshold: ConfiguredValue
    max_candidate_edges: ConfiguredValue

@dataclass(frozen=True)
class DependencyScopeConfig:
    max_scope_resources: ConfiguredValue
    max_materialized_resources: ConfiguredValue

@dataclass(frozen=True)
class P2TopologyConfig:
    propagation: PropagationConfig | None
    propagation_reason: str | None
    dependency_scope: DependencyScopeConfig | None
    dependency_scope_reason: str | None
```

Implement `_load_optional_p2_topology(document)` so an absent/incomplete block returns `None` and the appropriate reason. A present complete block validates values using explicit rules and preserves `source`; it never inserts defaults. Malformed complete numeric values also fail closed in the P2 envelope instead of preventing P0/P1 startup.

- [ ] **Step 4: Run focused and config suites**

Run: `.venv/bin/python -m pytest tests/test_analysis_config.py tests/spec_sanity -q`

Expected: all tests pass; shipped configuration still loads.

- [ ] **Step 5: Commit**

```bash
git add nocpro-chain-explain/services/analysis-worker/configuration nocpro-chain-explain/tests/test_analysis_config.py
git commit -m "feat: parse fail-closed P2 topology configuration"
```

### Task 2: Public result models and directed topology universes

**Files:**
- Create: `services/analysis-worker/tier2/topology_hypotheses/__init__.py`
- Create: `services/analysis-worker/tier2/topology_hypotheses/models.py`
- Create: `services/analysis-worker/tier2/topology_hypotheses/dominator.py`
- Test: `tests/test_p2_dominator.py`

**Interfaces:**
- Produces: `HypothesisStatus`, `TopologyHypothesisReason`, `DirectedUniverse`, `DominatorResult` and `analyze_common_dominator(package, chain_id)`.
- `DirectedUniverse` identity is `(source_ref, relation_type)`; universes never mix.
- `DominatorResult` deliberately has no score field.

- [ ] **Step 1: Write failing dominator tests**

Build minimal `IngestedPackage` fixtures for a single root, multiple roots, a cycle, unmapped alarm, ambiguous/unavailable witness and undirected adjacency. Pin a unique chain-level strict witness and ensure the dataclass has no `positive_score` attribute.

```python
def test_chain_common_strict_dominator_is_annotation_only(package):
    result = analyze_common_dominator(package, "C1")
    assert result.status is HypothesisStatus.AVAILABLE
    assert result.semantic == "UNAVOIDABLE_DEPENDENCY"
    assert result.witness_resource_id == "CORE"
    assert result.covered_resource_ids == ("LEAF_A", "LEAF_B")
    assert not hasattr(result, "positive_score")

def test_ip_adjacency_cannot_enable_dominator(production_style_package):
    result = analyze_common_dominator(production_style_package, "C1")
    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.DIRECTED_TOPOLOGY_UNAVAILABLE
```

- [ ] **Step 2: Run dominator tests and confirm failure**

Run: `.venv/bin/python -m pytest tests/test_p2_dominator.py -q`

Expected: FAIL because the topology-hypotheses package does not exist.

- [ ] **Step 3: Implement models and universe isolation**

Define stable enum values from the design. `DirectedUniverse` stores sorted nodes, predecessor/successor maps, source reference, relation type and provenance. Build universes only from directed `LOGICAL_DEPENDENCY` and `SERVICE_DEPENDS_ON` edges, grouped by source ID/version plus relation type.

- [ ] **Step 4: Implement deterministic dominators**

Use a virtual super-root and fixed-point sets:

```python
dom[root] = {root}
dom[v] = all_nodes
while changed:
    dom[v] = {v} | intersection(dom[p] for p in predecessors[v])
```

Resolve all chain mappings with the existing `ResourceResolver`. Intersect strict real dominators of every distinct mapped chain resource. Select the unique deepest common witness in the dominator relation; return structured unavailable reasons for no real witness, mapping failure or ambiguity. Sort all emitted identifiers.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/python -m pytest tests/test_p2_dominator.py tests/test_common_dependency.py -q`

Expected: all pass.

```bash
git add nocpro-chain-explain/services/analysis-worker/tier2/topology_hypotheses nocpro-chain-explain/tests/test_p2_dominator.py
git commit -m "feat: add exact P2 dominator annotations"
```

### Task 3: Configured propagation DAG and RWR

**Files:**
- Create: `services/analysis-worker/tier2/topology_hypotheses/propagation.py`
- Modify: `services/analysis-worker/tier2/topology_hypotheses/models.py`
- Modify: `services/analysis-worker/tier2/topology_hypotheses/__init__.py`
- Test: `tests/test_p2_propagation.py`

**Interfaces:**
- Produces: `PropagationResult`, `PropagationNodeScore`, `PropagationEdgeHypothesis`, `analyze_propagation(package, chain_id, config)`.
- Consumes: `PropagationConfig` and directed universes from Tasks 1–2.

- [ ] **Step 1: Write failing candidate-DAG tests**

Pin valid direction/time, reversed time, equal time, missing canonical time, unmapped alarms, cyclic low-level graph validation and candidate ceiling without truncation.

```python
def test_candidate_edge_requires_direction_and_strict_time(package, config):
    result = analyze_propagation(package, "C1", config)
    assert [(e.source_alarm_id, e.target_alarm_id) for e in result.hypotheses] == [("A", "B")]

def test_candidate_limit_never_truncates(package, config):
    result = analyze_propagation(package, "C1", replace(config, max_candidate_edges=cv(1)))
    assert result.status is HypothesisStatus.UNAVAILABLE
    assert result.reason is TopologyHypothesisReason.CANDIDATE_LIMIT_EXCEEDED
    assert result.candidate_edge_count == 2
    assert result.hypotheses == ()
```

- [ ] **Step 2: Write failing RWR contract tests**

Pin uniform restart over every indegree-zero node, `pi(0)=r`, exponential temporal weights, outgoing normalization, dangling redistribution, L1 convergence, failure at max iterations and edge flow `(1-alpha)*pi(u)*P_uv`. Use fixed test parameters supplied by each fixture; production code contains none.

- [ ] **Step 3: Run tests and confirm failure**

Run: `.venv/bin/python -m pytest tests/test_p2_propagation.py -q`

Expected: FAIL because `analyze_propagation` is absent.

- [ ] **Step 4: Implement candidate construction and RWR**

Parse `canonical_start_time` with timezone normalization. Create direct alarm edges only from eligible direct resource edges and strict temporal precedence. Reject cycles before RWR. Implement iteration in sorted node order:

```python
next_pi = alpha * restart
next_pi += (1 - alpha) * graph_transition_mass
next_pi += (1 - alpha) * dangling_mass * restart
l1 = sum(abs(next_pi[v] - pi[v]) for v in nodes)
```

Initialize with restart distribution, succeed when L1 is within tolerance including the final allowed iteration, and otherwise emit `RWR_NOT_CONVERGED` with diagnostics but no node/edge results. Emit edge hypotheses only when exact flow meets threshold.

- [ ] **Step 5: Verify determinism and commit**

Run: `.venv/bin/python -m pytest tests/test_p2_propagation.py -q`

Expected: all pass, including repeated identical output and changed config provenance.

```bash
git add nocpro-chain-explain/services/analysis-worker/tier2/topology_hypotheses nocpro-chain-explain/tests/test_p2_propagation.py
git commit -m "feat: rank propagation hypotheses with configured RWR"
```

### Task 4: Exact dependency-scope statistics with bounded detail

**Files:**
- Create: `services/analysis-worker/tier2/topology_hypotheses/scope_overlap.py`
- Create: `services/analysis-worker/tier2/topology_hypotheses/analysis.py`
- Modify: `services/analysis-worker/tier2/topology_hypotheses/models.py`
- Modify: `services/analysis-worker/tier2/topology_hypotheses/__init__.py`
- Test: `tests/test_p2_scope_overlap.py`

**Interfaces:**
- Produces: `DependencyScopeResult`, `ResourceDetails`, `TopologyHypothesesResult` and `analyze_topology_hypotheses(package, chain_id, config)`.
- Consumes: the exact dominator witness and its same directed universe; never searches for another witness.

- [ ] **Step 1: Write failing exact-statistics tests**

Pin `missing=Observed-Scope`, `extra=Scope-Observed`, every count and denominator, empty scope, computation ceiling, materialization ceiling and no partial lists.

```python
def test_scope_aggregates_remain_exact_when_details_are_too_large(fixture):
    result = analyze_dependency_scope(fixture.package, fixture.dominator, fixture.config)
    assert result.status is HypothesisStatus.AVAILABLE
    assert result.intersection_count == 2
    assert result.missing_resource_count == 1
    assert result.extra_resource_count == 3
    assert result.resource_details.status is HypothesisStatus.UNAVAILABLE
    assert result.resource_details.reason is TopologyHypothesisReason.MATERIALIZATION_LIMIT_EXCEEDED
    assert result.resource_details.missing_resources is None
    assert result.resource_details.extra_resources is None
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `.venv/bin/python -m pytest tests/test_p2_scope_overlap.py -q`

Expected: FAIL because scope analysis is absent.

- [ ] **Step 3: Implement exact set/bitmap statistics**

Traverse reachable dependents of only the chosen witness. Count scope before evaluation; exceed computation ceiling with `SCOPE_LIMIT_EXCEEDED`. Otherwise compute exact intersection, union, missing and extra counts. Materialize both complete sorted lists only when their combined cardinality is within `max_materialized_resources`; otherwise return neither list and preserve exact aggregates.

- [ ] **Step 4: Implement independent orchestration**

`analyze_topology_hypotheses` runs dominator and propagation independently. Scope consumes the dominator result only when available. One unavailable subsystem never removes another available result. Missing optional configuration maps to the stable structured unavailable reasons.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/python -m pytest tests/test_p2_dominator.py tests/test_p2_propagation.py tests/test_p2_scope_overlap.py -q`

Expected: all pass.

```bash
git add nocpro-chain-explain/services/analysis-worker/tier2/topology_hypotheses nocpro-chain-explain/tests/test_p2_scope_overlap.py
git commit -m "feat: add exact bounded dependency scope overlap"
```

### Task 5: Tier-2 job, cache and API projection

**Files:**
- Modify: `services/analysis-worker/tier2/audit_analysis.py`
- Modify: `services/analysis-worker/tier2/jobs.py`
- Modify: `services/analysis-worker/tier2/__init__.py`
- Modify: `services/api/nocpro_api/schemas.py`
- Modify: `services/api/nocpro_api/serializers.py`
- Test: `tests/test_tier2_jobs.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Adds: `Tier2AuditAnalysis.topology_hypotheses: TopologyHypothesesResult`.
- Adds: explicit Pydantic views for dominator, propagation diagnostics/node/edge scores and dependency scope/resource detail.
- Keeps: one asynchronous Tier-2 submission and the existing versioned cache boundary.

- [ ] **Step 1: Write failing integration and separation tests**

Assert the analyzer attaches three results, incomplete production config becomes structured unavailable instead of a failed job, and the response contains no normalized score for dominator. Monkeypatch audit construction to prove topology hypotheses are not inputs to `build_audit_graph`.

- [ ] **Step 2: Run tests and confirm failure**

Run: `.venv/bin/python -m pytest tests/test_tier2_jobs.py tests/test_api.py -q`

Expected: FAIL because deep-dive schemas lack topology hypotheses.

- [ ] **Step 3: Integrate the analyzer**

Call `analyze_topology_hypotheses` beside structural audit and Similar Chains. Pass the optional P2 config envelope from `AnalysisConfig`. Extend the cache config-version stamp with available P2 sub-config versions so a propagation/scope config change cannot reuse stale Tier-2 output.

- [ ] **Step 4: Add explicit serializer schemas**

Use typed Pydantic models, not `dict[str, Any]`, for P2 output. Serialize enum values and complete diagnostics. Represent unavailable materialized resource lists as `null`, never empty arrays.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_tier2_jobs.py tests/test_api.py tests/test_tier2_audit.py -q`

Expected: all pass.

```bash
git add nocpro-chain-explain/services/analysis-worker/tier2 nocpro-chain-explain/services/api/nocpro_api nocpro-chain-explain/tests/test_tier2_jobs.py nocpro-chain-explain/tests/test_api.py
git commit -m "feat: expose P2 topology results through Tier-2 API"
```

### Task 6: React topology-hypothesis panel and browser acceptance

**Files:**
- Modify: `services/web/src/types.ts`
- Modify: `services/web/src/App.tsx`
- Modify: `services/web/src/App.css`
- Modify: `services/web/e2e/operator-flow.spec.ts`
- Create: `services/web/src/TopologyHypotheses.tsx`
- Create: `services/web/src/TopologyHypotheses.test.tsx`

**Interfaces:**
- Consumes: typed `topology_hypotheses` from `DeepDiveView`.
- Renders: three status cards under an accessible section labeled `Topology hypotheses`.
- Copy: only `Unavoidable dependency annotation`, `Propagation hypothesis score` and `Dependency scope overlap signal`; no causal/root-cause wording.

- [ ] **Step 1: Write failing UI tests**

Pin available and unavailable cards, diagnostics, materialization-unavailable behavior, absence of partial lists and forbidden wording (`caused`, `root cause probability`, `causal confidence`).
Use `react-dom/server`'s `renderToStaticMarkup` so the existing dependency set
is sufficient and no browser-DOM test library is added.

- [ ] **Step 2: Run UI tests and confirm failure**

Run: `pnpm --dir services/web test`

Expected: FAIL because the panel does not exist.

- [ ] **Step 3: Implement typed panel**

Add TypeScript discriminated result types and a focused
`TopologyHypotheses` component, then mount it from `App.tsx`. Render one
accessible section. Unavailable cards show their stable reason. Available
propagation lists node stationary mass separately from edge propagation flow.
Available scope retains aggregate metrics when resource details are unavailable
and does not render missing/extra list containers in that case.

- [ ] **Step 4: Extend production browser acceptance**

The real replay has undirected adjacency and the shipped config has no P2
block. After Deep Dive, assert all three cards are `UNAVAILABLE`, propagation
shows `PROPAGATION_CONFIG_INCOMPLETE`, dominator shows
`DIRECTED_TOPOLOGY_UNAVAILABLE`, and browser console remains clean.

- [ ] **Step 5: Verify and commit**

Run:

```bash
pnpm --dir services/web lint
pnpm --dir services/web test
pnpm --dir services/web build
```

Expected: all pass.

```bash
git add nocpro-chain-explain/services/web
git commit -m "feat: render fail-closed topology hypotheses"
```

### Task 7: Full regression, Docker/browser E2E and status documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents: P2 topology foundation implemented with production capability unavailable.
- Preserves: production-delta external-data block and unopened P2 subsystems such as KEDB, TempOpt, calibrated confidence and Louvain internals.

- [ ] **Step 1: Run all non-Docker verification**

Run:

```bash
.venv/bin/python -m pytest tests -q
pnpm --dir services/web lint
pnpm --dir services/web test
pnpm --dir services/web build
git diff --check
```

Expected: zero failures.

- [ ] **Step 2: Run isolated acceptance**

Run: `./tests/e2e/run_acceptance.sh`

Expected: real replay, Chromium operator flow, Docker recovery cases and 1,072-member Tier-1B benchmark all pass; stack cleans up.

- [ ] **Step 3: Update status without overclaiming**

Record the three implemented P2 topology semantics, test evidence, and production `UNAVAILABLE` capability. Keep the remaining P2 items explicitly not started/data-gated. Do not advertise synthetic ground truth as production validation.

- [ ] **Step 4: Review and final commit**

Run the completion verification commands again after documentation changes, inspect staged diff, then commit:

```bash
git add nocpro-chain-explain/README.md nocpro-chain-explain/tests/e2e
git commit -m "docs: record P2 topology capability status"
```
