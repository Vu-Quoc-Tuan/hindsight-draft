# Bounded Audit Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and render a deterministic 80-node/160-edge visualization projection of an exact Tier-2 Audit graph without changing any evidence, structural, or Counterfactual semantics.

**Architecture:** Tier-2 derives a versioned `AuditVisualization` only after exact Audit computation, embeds it in backward-compatible `review-audit-v2` artifacts, and exposes it through live job and persisted read-only API paths. React computes deterministic display coordinates from the typed projection and never treats the bounded graph as an analysis input.

**Tech Stack:** Python 3 frozen dataclasses, FastAPI/Pydantic, PostgreSQL JSONB persistence, React 19, TypeScript, SVG, pytest, Vitest, Playwright.

## Global Constraints

- `audit-visualization-v1` is `VISUALIZATION` only and never feeds Audit, Role, MembershipSupport, topology P2, or Counterfactual.
- Bounds are exactly 80 nodes and 160 edges.
- GET requests never rebuild pair evidence, rerun Tier-2, or use a dense fallback.
- Existing `review-audit-v1` artifacts remain readable and yield explicit visualization unavailability.
- No database migration or new table is added; the existing immutable JSONB Audit artifact stores v2 payloads.
- No unrelated `nocpro-mock` or roadmap worktree changes enter these commits.

---

### Task 1: Deterministic visualization projection

**Files:**
- Create: `services/analysis-worker/tier2/audit_visualization.py`
- Modify: `services/analysis-worker/tier2/audit_analysis.py`
- Modify: `services/analysis-worker/tier2/__init__.py`
- Create: `tests/test_audit_visualization.py`
- Modify: `tests/test_tier2_audit.py`

**Interfaces:**
- Consumes: `AuditGraph`, `StructuralAuditResult.best_cut`, and exact `structural_roles`.
- Produces: `build_audit_visualization(graph, structural_audit, structural_roles) -> AuditVisualization` and `Tier2AuditAnalysis.audit_visualization`.

- [ ] **Step 1: Write projection tests before implementation**

  Cover a small graph retaining every node/edge, an empty-edge graph remaining available, an over-cap graph enforcing 80/160, balanced representation of both best-cut sides, canonical edge endpoints, and equality after shuffled input order.

- [ ] **Step 2: Run the focused tests and confirm they fail because the module/type is absent**

  Run: `.venv/bin/pytest -q tests/test_audit_visualization.py tests/test_tier2_audit.py`

- [ ] **Step 3: Implement immutable projection values and builder**

  Define frozen node, edge, and projection dataclasses. Calculate weighted degree from the exact graph; select nodes by the approved side-balanced strategy; select induced edges by `(-weight, source, target)`; calculate shown/hidden counts without inventing nodes or edges.

- [ ] **Step 4: Attach the projection after exact Audit finishes**

  `analyze_structural_audit` builds the projection from `graph`, `structural_audit`, and `roles`. When exact Audit is unavailable, `audit_visualization` is an explicit unavailable value using the exact Audit reason rather than an empty available graph.

- [ ] **Step 5: Pin semantic isolation**

  Add a regression that changes visualization caps/selection inputs and proves the existing exact verdict, best-cut conductance, and structural roles are unchanged. Also assert the large-chain guard returns unavailable without calling `build_audit_graph` or the visualization builder.

- [ ] **Step 6: Run focused and full Tier-2 tests**

  Run: `.venv/bin/pytest -q tests/test_audit_visualization.py tests/test_tier2_audit.py tests/test_tier2_jobs.py tests/test_audit.py`

- [ ] **Step 7: Commit Task 1**

  Commit: `feat: derive bounded audit visualization`

### Task 2: Versioned artifact persistence and compatibility

**Files:**
- Modify: `services/analysis-worker/tier2/audit_artifact.py`
- Modify: `services/analysis-worker/tier2/jobs.py`
- Modify: `services/api/nocpro_api/persistence/repository.py`
- Modify: `tests/test_audit_artifact.py`
- Modify: `tests/test_tier2_jobs.py`
- Modify: `tests/test_postgres_audit_artifacts.py`

**Interfaces:**
- Consumes: `Tier2AuditAnalysis.audit_visualization`.
- Produces: `review-audit-v2` payloads with an optional typed `visualization`; accepts legacy `review-audit-v1` payloads without rewriting their fingerprints.

- [ ] **Step 1: Add failing v2 round-trip and v1 compatibility tests**

  Assert that v2 round-trips byte-equivalent semantic data, tampering with a visualization edge fails fingerprint validation, and a valid v1 artifact hydrates with visualization unavailable reason `BOUNDED_PUBLIC_AUDIT_GRAPH_ARTIFACT_NOT_AVAILABLE`.

- [ ] **Step 2: Implement version-aware payload and fingerprint logic**

  Keep the v1 fingerprint input exactly unchanged. Include the canonical visualization object only for v2. Reject unknown versions, invalid counts, edges referencing omitted nodes, noncanonical endpoints, and cap violations.

- [ ] **Step 3: Pass the already-built projection into artifact creation**

  Update `Tier2JobManager._build_artifact` so cached and fresh jobs persist the same projection. Do not rebuild it in the persistence listener or repository.

- [ ] **Step 4: Verify insert-only persistence**

  Test that persisting the same identity/payload is idempotent and different visualization contents under the same artifact identity fail. If `TEST_DATABASE_URL` is absent, keep PostgreSQL tests explicitly skipped rather than claiming runtime proof.

- [ ] **Step 5: Run artifact/job/repository suites**

  Run: `.venv/bin/pytest -q tests/test_audit_artifact.py tests/test_tier2_jobs.py tests/test_postgres_audit_artifacts.py`

- [ ] **Step 6: Commit Task 2**

  Commit: `feat: persist bounded audit visualization`

### Task 3: Live and persisted read-only API

**Files:**
- Modify: `services/api/nocpro_api/schemas.py`
- Modify: `services/api/nocpro_api/serializers.py`
- Modify: `services/api/nocpro_api/workspace.py`
- Modify: `services/api/nocpro_api/routes.py`
- Modify: `services/web/src/types.ts`
- Modify: `services/web/src/api.ts`
- Modify: `tests/test_api.py`
- Modify: `tests/test_postgres_audit_artifacts.py`

**Interfaces:**
- Produces: typed `AuditVisualizationView` within `DeepDiveView` and `GET /api/v1/chains/{chain_id}/audit-visualization`.
- The endpoint returns `AVAILABLE` only for a compatible in-memory or persisted v2 artifact; otherwise it returns a typed `UNAVAILABLE` response and reason.

- [ ] **Step 1: Add failing API projection tests**

  Pin exact response identity, nodes, edges, counts, caps, selection strategy, and visualization disclaimer for a completed Deep Dive. Assert an unrun Audit and a legacy artifact return explicit unavailable states without job submission.

- [ ] **Step 2: Add Pydantic schema and one canonical serializer**

  Serialize node/edge order without re-sorting by request-specific state. Reuse the same serializer for live `DeepDiveView` and the dedicated persisted endpoint.

- [ ] **Step 3: Implement compatible lookup in Workspace**

  Check the latest succeeded in-memory job first, then flush and query `latest_compatible_audit_artifact` using current snapshot/version/membership/analysis/config identity. Never call `submit_deep_dive` from this path.

- [ ] **Step 4: Add the read-only route and frontend client types**

  The route returns HTTP 200 with `UNAVAILABLE` for missing capability/artifact and standard translated errors only for invalid chain/context. Add an abortable `api.auditVisualization(chainId, signal)` method.

- [ ] **Step 5: Verify live/persisted equality**

  Compare every visualization semantic field before repository restart and after hydration. Assert no analyzer, pair iterator, or job submission is invoked by GET.

- [ ] **Step 6: Run API and persistence suites**

  Run: `.venv/bin/pytest -q tests/test_api.py tests/test_audit_artifact.py tests/test_postgres_audit_artifacts.py tests/test_assistant_tool_calling.py`

- [ ] **Step 7: Commit Task 3**

  Commit: `feat: expose persisted audit visualization`

### Task 4: Evidence-faithful React graph

**Files:**
- Create: `services/web/src/AuditGraphVisualization.tsx`
- Create: `services/web/src/AuditGraphVisualization.test.tsx`
- Modify: `services/web/src/views/AuditStructureView.tsx`
- Modify: `services/web/src/App.tsx`
- Modify: `services/web/src/PairWhyAndAudit.test.tsx`
- Modify: `services/web/e2e/ui-data-truth.spec.ts`

**Interfaces:**
- Consumes: `AuditVisualizationView` from either the matching completed job or persisted endpoint.
- Produces: deterministic two-region/grid SVG with no analytical side effects.

- [ ] **Step 1: Add component tests for all projection states**

  Test available best-cut graph, no-cut grid, zero-edge graph, truncated metadata, and explicit unavailable reason. Assert no causal/root-cause or complete-graph claim appears.

- [ ] **Step 2: Implement deterministic layout helpers and SVG**

  Compute coordinates in React only. Put side A and B in fixed left/right regions; use a full-width grid for `NONE`; render edges before nodes; emphasize cross-cut edges; expose alarm ID, role, degree, weight, and supporting groups via accessible labels and SVG titles.

- [ ] **Step 3: Wire context-safe artifact loading**

  Key loaded visualization by snapshot/version/chain/config context. Prefer the matching completed job projection and fetch the persisted endpoint on Audit navigation/reload. Abort stale requests and never retain graph A under chain B.

- [ ] **Step 4: Replace the placeholder without hiding unavailability**

  Render the graph only for `AVAILABLE`. Preserve a distinct unavailable card for legacy/missing/limit cases. Display shown/hidden node and edge counts plus `Visualization only; exact Audit uses the full eligible graph.`

- [ ] **Step 5: Add scoped Chromium acceptance**

  Pin an available graph, tooltip/accessibility content, truncation label, chain-switch stale protection, and `document.documentElement.scrollWidth <= clientWidth` at 390 pixels.

- [ ] **Step 6: Run frontend gates**

  Run: `npm test -- --run`, `npm run lint`, `npm run build`, and `npx playwright test e2e/ui-data-truth.spec.ts` from `services/web`.

- [ ] **Step 7: Commit Task 4**

  Commit: `feat(ui): render bounded audit graph`

### Task 5: Closure verification and documentation

**Files:**
- Modify: `IMPLEMENTATION_STATUS.md`
- Modify: `docs/superpowers/plans/2026-09-07-bounded-audit-visualization.md`

**Interfaces:**
- Produces: an evidence-tiered status entry and checked implementation plan matching verified results.

- [ ] **Step 1: Run the full Python suite**

  Run: `.venv/bin/pytest -q` from `nocpro-chain-explain`. Record exact passed/skipped totals and why runtime PostgreSQL tests were skipped, if applicable.

- [ ] **Step 2: Run all frontend and browser gates again**

  Run Vitest, lint, production build, and the scoped Chromium suite from the final tree.

- [ ] **Step 3: Run diff and scope hygiene**

  Run `git diff --check -- nocpro-chain-explain`, inspect `git status --short`, and stage only files belonging to this feature.

- [ ] **Step 4: Update implementation status honestly**

  Mark bounded Audit visualization implementation and synthetic/browser evidence separately. Do not call PostgreSQL restart or Docker acceptance `PASS` unless those paths actually ran in this phase.

- [ ] **Step 5: Commit closure metadata**

  Commit: `docs: record bounded audit visualization status`
