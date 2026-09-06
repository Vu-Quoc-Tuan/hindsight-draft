# Evidence-Faithful UI Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace production-facing mock metrics and local-only actions with context-safe projections of persisted backend artifacts.

**Architecture:** Keep snapshot pages lightweight, use explicit request identities for lazy chain artifacts, and centralize unavailable/loading states. Extend only the canonical chain-list projection needed by the timeline; reuse existing Pair WHY, Deep Dive, Evolution, Review and feedback APIs.

**Tech Stack:** Python 3, FastAPI/Pydantic, React 19, TypeScript, Vitest, Playwright, PostgreSQL repository abstractions.

## Global Constraints

- No missing value may be coerced to a numeric evidence value.
- No snapshot-level dense Tier-2 or per-chain N+1 analysis.
- No cross-chain causal claim, topology semantic promotion, Apply, rollback or consensus claim.
- Preserve Counterfactual Review v1 and existing evidence semantics.
- Preserve concurrent user changes and commit each independently testable group separately.

---

### Task 1: Context-safe application shell

**Files:**
- Modify: `nocpro-chain-explain/services/web/src/App.tsx`
- Create: `nocpro-chain-explain/services/web/src/AppContext.test.tsx`

**Interfaces:**
- Consumes: `ChainList.snapshot_id`, `ChainList.snapshot_version`, selected chain ID and config epoch.
- Produces: matching `ChainAnalysis` or an explicit loading/unavailable state.

- [ ] Add a test with delayed chain B response proving chain A data is not rendered under chain B.
- [ ] Add an offline test proving no fabricated chain/member/metric is rendered and no `STREAM SYNCED` status appears.
- [ ] Key analysis state by snapshot ID, snapshot version, chain ID and config epoch; validate returned `payload.chain_id`.
- [ ] Remove `effectiveAnalysis` demo construction and render an artifact state card until matching analysis exists.
- [ ] Derive the displayed snapshot identity from `ChainList`; stop treating the header label callback as a snapshot activation.
- [ ] Run `npm test -- AppContext.test.tsx`, then the full frontend test suite.
- [ ] Commit as `fix(ui): enforce snapshot and chain analysis context`.

### Task 2: Honest snapshot views and exact temporal summary

**Files:**
- Modify: `nocpro-chain-explain/services/api/nocpro_api/schemas.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/routes.py`
- Modify: `nocpro-chain-explain/services/web/src/types.ts`
- Modify: `nocpro-chain-explain/services/web/src/views/ChainsExplorerView.tsx`
- Modify: `nocpro-chain-explain/services/web/src/views/MultiChainTimelineView.tsx`
- Modify: `nocpro-chain-explain/services/web/src/views/CompareChainsView.tsx`
- Test: `nocpro-chain-explain/services/api/tests/test_api.py`
- Create: `nocpro-chain-explain/services/web/src/SnapshotViewsDataTruth.test.tsx`

**Interfaces:**
- Produces: nullable `start_time`, `end_time`, `duration_seconds` on `ChainSummaryView` from canonical member timestamps.
- Consumes: only chain-list fields in the three snapshot views.

- [ ] Add serializer/API tests pinning min/max canonical timestamps, null behavior and no Deep Dive submission from `GET /chains`.
- [ ] Extend `ChainSummaryView` and `/chains` serialization with exact temporal summary fields.
- [ ] Add UI tests proving Explorer shows `Audit on demand`, Timeline uses returned times, and Compare contains no causal/upstream/delay claim.
- [ ] Remove conductance/weak-member heuristics, synthetic timeline tracks and static Compare evidence scores.
- [ ] Render explicit unavailable labels for fields absent from `ChainSummary`.
- [ ] Run focused API and frontend tests.
- [ ] Commit as `fix(ui): use factual snapshot chain summaries`.

### Task 3: Pair WHY and persisted Audit projections

**Files:**
- Modify: `nocpro-chain-explain/services/web/src/views/ChainDetailView.tsx`
- Modify: `nocpro-chain-explain/services/web/src/views/AuditStructureView.tsx`
- Modify: `nocpro-chain-explain/services/web/src/App.tsx`
- Create: `nocpro-chain-explain/services/web/src/PairWhyAndAudit.test.tsx`

**Interfaces:**
- Consumes: `api.pairWhy`, `api.submitDeepDive`, `api.job`, `Job.result` typed as `DeepDive` when succeeded.
- Produces: pair evidence ledger and an Audit view sourced only from the selected chain's compatible job result.

- [ ] Add tests proving two selected distinct members trigger Pair WHY and null MembershipSupport renders `N/A`.
- [ ] Wire Pair WHY selection and render state/provenance/score without null coercion.
- [ ] Add tests proving Audit renders real verdict, best-cut phi and attribution AUC fields, and renders unavailable before a persisted result exists.
- [ ] Pass the matching Deep Dive result into Audit; remove static graph, cut and AUC claims from live rendering.
- [ ] Keep dynamic graph visualization unavailable until a bounded public graph artifact exists.
- [ ] Run focused and full frontend tests.
- [ ] Commit as `fix(ui): wire pair why and persisted audit results`.

### Task 4: Review, Evolution, topology and durable feedback

**Files:**
- Modify: `nocpro-chain-explain/services/web/src/CounterfactualReview.tsx`
- Modify: `nocpro-chain-explain/services/web/src/views/RecommendationsView.tsx`
- Modify: `nocpro-chain-explain/services/web/src/views/EvolutionView.tsx`
- Modify: `nocpro-chain-explain/services/web/src/views/TopologyOverlayView.tsx`
- Modify: `nocpro-chain-explain/services/web/src/views/ValidationView.tsx`
- Modify: `nocpro-chain-explain/services/web/src/components/OperatorValidationModal.tsx`
- Modify: `nocpro-chain-explain/services/web/src/App.tsx`
- Test: `nocpro-chain-explain/services/web/src/ValidationAndCutsFlow.test.tsx`

**Interfaces:**
- Consumes: Counterfactual Review v1, persisted Evolution response, topology projection, `submitReviewFeedback` and `reviewFeedback`.
- Produces: factual KPI projections, one Evolution artifact across both modes, topology navigation without dependency promotion, and durable candidate feedback.

- [ ] Add tests for Review-derived counts, Evolution unavailable, topology loading/unavailable and feedback request/reload.
- [ ] Remove static Review KPI values and derive only fields represented by Review v1.
- [ ] Make Timeline and DAG projections consume the same Evolution result.
- [ ] Remove topology fallback `AVAILABLE`, fabricated CMDB provenance, mapping ratio and cut/root labels.
- [ ] Replace consensus/ledger/rollback UI with APPROVED/REJECTED candidate feedback and persisted history.
- [ ] Run focused and full frontend tests.
- [ ] Commit as `fix(ui): project persisted review evolution and feedback`.

### Task 5: Assistant read-only boundary and browser acceptance

**Files:**
- Modify: `nocpro-chain-explain/services/api/nocpro_api/assistant.py`
- Test: `nocpro-chain-explain/services/api/tests/test_assistant.py`
- Create or modify: `nocpro-chain-explain/services/web/e2e/ui-data-truth.spec.ts`
- Modify: `nocpro-chain-explain/services/web/public/favicon.svg`

**Interfaces:**
- Consumes: persisted compatible Audit/Review/Evolution artifacts.
- Produces: Assistant unavailable actions without submitting jobs; browser evidence for stale-context and fail-closed UI.

- [ ] Add a backend test proving Assistant Audit inspection never calls `submit_deep_dive` and returns unavailable when no compatible artifact exists.
- [ ] Remove `_get_or_run_audit` submission/polling and replace it with persisted read-only lookup.
- [ ] Add Playwright tests for delayed chain switching, API offline, null metrics, Evolution unavailable, topology unavailable and feedback reload.
- [ ] Fix mobile overflow attributable to application layout and remove favicon trailing whitespace.
- [ ] Run the relevant Python suite, `npm test`, `npm run lint`, `npm run build`, Playwright and `git diff --check`.
- [ ] Commit as `fix(ui): enforce read-only evidence-backed interactions`.

