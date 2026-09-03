# Evidence Coverage Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exact, derivation-group Evidence Coverage Attribution and make Tier-2 return partial domain results when exact structural components exceed their ceiling.

**Architecture:** Extend indexed channel statistics with exact peer-support bitmaps, then reduce those bitmaps into group-level coverage contributions without storing a pair list. Keep policy, computation, API projection, and UI rendering separate. Structural Audit and Attribution become independently unavailable domain results while Similar Chains and topology hypotheses continue.

**Tech Stack:** Python dataclasses/enums, Python integer bitmaps, FastAPI/Pydantic, React/TypeScript, pytest/Vitest.

## Global Constraints

- Attribution players are EXPLAIN_ELIGIBLE effective derivation groups; SYSTEM_FACT is excluded and BEHAVIORAL is labeled.
- Attribution modes are only EXACT and UNAVAILABLE; no approximation, sampling, truncation, visualization graph, or sparsified graph input.
- Reuse `audit.exact_max_members` through a dedicated attribution policy decision.
- Singleton attribution is NOT_APPLICABLE and never numeric zero.
- Domain unavailability does not fail the Tier-2 job.

---

### Task 1: Exact indexed support bitmaps

**Files:**
- Modify: `nocpro-chain-explain/services/analysis-worker/groups/indexed_statistics.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/channels/indexed_statistics.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/channels/dep_upstream_index.py`
- Test: `nocpro-chain-explain/tests/test_evidence_coverage_attribution.py`

**Interfaces:**
- Produces: exact per-member channel support bitmaps with stable member positions.

- [x] Write failing tests proving duplicate channels share one derivation vote and indexed statistics expose exact support without calling the pairwise evaluator.
- [x] Run the focused tests and confirm the missing interface failure.
- [x] Add peer-support bitmaps to indexed statistics and populate equality, burst, hop, ancestor, and active-path channels.
- [x] Run the focused tests and confirm exact support parity on tiny fixtures.

### Task 2: Attribution policy and exact calculator

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/tier2/evidence_attribution.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/tier2/__init__.py`
- Test: `nocpro-chain-explain/tests/test_evidence_coverage_attribution.py`

**Interfaces:**
- Consumes: indexed peer-support bitmaps and channel metadata.
- Produces: `EvidenceCoverageAttributionResult` with status, mode, reason, ceiling diagnostics, total coverage, and deterministic group contributions.

- [x] Write failing exact-formula, representation-invariance, limit, singleton, and brute-force-oracle tests.
- [x] Run tests and confirm failures.
- [x] Implement a separate `AttributionExecutionPolicy` and exact group bitmap reduction.
- [x] Run focused tests and confirm all cases pass.

### Task 3: Partial Tier-2 orchestration and API

**Files:**
- Modify: `nocpro-chain-explain/services/analysis-worker/audit/conductance.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/tier2/audit_analysis.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/tier2/jobs.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/schemas.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/serializers.py`
- Test: `nocpro-chain-explain/tests/test_tier2_audit.py`
- Test: `nocpro-chain-explain/tests/test_api.py`

**Interfaces:**
- Produces: a successful Tier-2 result whose Structural Audit and Attribution carry their own domain status.

- [x] Replace the old large-chain exception test with a partial-result regression test.
- [x] Add API projection tests for exact, limit-exceeded, and singleton Attribution results.
- [x] Refactor descriptors/similarity/P2 ahead of the exact-audit branch and return `UNAVAILABLE/AUDIT_LIMIT_EXCEEDED` without graph construction.
- [x] Wire Attribution into the result and serialized API.
- [x] Run Tier-2, job, and API tests.

### Task 4: Operator-facing attribution UI and verification

**Files:**
- Modify: `nocpro-chain-explain/services/web/src/types.ts`
- Modify: `nocpro-chain-explain/services/web/src/App.tsx`
- Modify: `nocpro-chain-explain/services/web/src/App.css`
- Create: `nocpro-chain-explain/services/web/src/EvidenceAttribution.test.tsx`

**Interfaces:**
- Consumes: serialized `evidence_attribution`.
- Produces: an exact coverage waterfall/list using only the wording `% evidence coverage`.

- [x] Add rendering tests for EXACT, UNAVAILABLE, and singleton states, including forbidden wording checks.
- [x] Render deterministic group contributions and explicit domain reasons.
- [x] Run Vitest, lint, and production build.
- [x] Run the complete Python suite and inspect the final diff before committing.
