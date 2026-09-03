# Attribution Deletion Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exact, deterministic deletion-curve evaluation for Evidence Coverage Attribution, including fixed cross-runtime randomization semantics and fail-closed domain results.

**Architecture:** Reuse the exact indexed group-support representation that produces attribution, then evaluate union coverage after each group deletion without constructing a dense pair matrix. Keep evaluation as an independent Tier-2 component result, configured by versioned seed/repetition values and serialized through API/UI.

**Tech Stack:** Python 3 dataclasses/enums/bitmaps, FastAPI/Pydantic, React/TypeScript, pytest, Vitest.

## Global Constraints

- PRIMARY sorts attribution descending and stable group_id ascending; REVERSE sorts attribution ascending and stable group_id ascending.
- Every curve point recomputes exact remaining-group union coverage; never use `1 - cumulative_phi`.
- Randomization is `SPLITMIX64_FISHER_YATES_V1`, one RNG stream, seed 42 and 100 repetitions from versioned config.
- Standard deviations are population standard deviations (`ddof=0`).
- Attribution unavailable makes evaluation `UNAVAILABLE / ATTRIBUTION_UNAVAILABLE`.
- For chain size at least two and zero eligible groups, attribution stays exact/available while evaluation is `NOT_APPLICABLE / NO_ELIGIBLE_GROUPS`, with empty curves, null AUCs, and zero RNG executions.

---

### Task 1: Reusable exact support model

**Files:**
- Modify: `services/analysis-worker/tier2/evidence_attribution.py`
- Test: `tests/test_evidence_coverage_attribution.py`

**Interfaces:**
- Produces: an internal exact group-support model shared by attribution and evaluation.
- Preserves: `compute_evidence_coverage_attribution(...)` public behavior.

- [ ] Extract exact eligible groups and per-left-member peer bitmaps into a focused immutable support model.
- [ ] Make attribution consume that model without changing its closed-form results or ceilings.
- [ ] Pin the exact `G=0` attribution result and existing singleton distinction with tests.
- [ ] Run `pytest tests/test_evidence_coverage_attribution.py -q`.

### Task 2: Deterministic exact deletion evaluator

**Files:**
- Create: `services/analysis-worker/tier2/attribution_evaluation.py`
- Create: `tests/test_attribution_evaluation.py`
- Modify: `services/analysis-worker/tier2/__init__.py`

**Interfaces:**
- Consumes: exact support model and `EvidenceCoverageAttributionResult`.
- Produces: `AttributionDeletionEvaluationResult` with primary, reverse, random baseline, AUCs, deltas, and structured unavailable/not-applicable states.

- [ ] Write failing tests for ordering, exact union recomputation, trapezoidal AUC, population std, and parent-unavailable semantics.
- [ ] Define `SPLITMIX64_FISHER_YATES_V1` completely with unsigned 64-bit state and rejection-sampled Fisher-Yates bounds.
- [ ] Pin golden permutations so the algorithm is independent of Python runtime shuffle behavior.
- [ ] Implement exact curves, random pointwise mean/std, random AUC mean/std, and deltas.
- [ ] Pin `G=0` to execute no RNG and return empty curves/null AUCs.
- [ ] Run `pytest tests/test_attribution_evaluation.py tests/test_evidence_coverage_attribution.py -q`.

### Task 3: Versioned configuration and Tier-2/API wiring

**Files:**
- Modify: `services/analysis-worker/configuration/analysis_config.py`
- Modify: `config/thresholds/v1.yaml`
- Modify: `config/thresholds/e2e-p2.yaml`
- Modify: `services/analysis-worker/tier2/audit_analysis.py`
- Modify: `services/analysis-worker/tier2/jobs.py`
- Modify: `services/api/nocpro_api/schemas.py`
- Modify: `services/api/nocpro_api/serializers.py`
- Test: `tests/test_analysis_config.py`
- Test: `tests/test_tier2_audit.py`
- Test: `tests/test_tier2_jobs.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `AnalysisConfig.attribution_evaluation`, analyzer input policy, Tier-2 result field, and API view.

- [ ] Add a fail-closed config loader requiring algorithm ID, seed, and positive repetitions while preserving source provenance for numeric fields.
- [ ] Add frozen v1 values to both shipped configs.
- [ ] Include the evaluation envelope in Tier-2 cache identity.
- [ ] Run evaluator only after exact attribution and keep domain unavailability from failing the job.
- [ ] Serialize all raw curves, AUCs, diagnostics, and null/empty values exactly.
- [ ] Run focused config, Tier-2, job, and API tests.

### Task 4: Operator UI, ADR, and full verification

**Files:**
- Modify: `services/web/src/types.ts`
- Modify: `services/web/src/EvidenceAttribution.tsx`
- Modify: `services/web/src/EvidenceAttribution.test.tsx`
- Modify: `docs/adr/0031-freeze-evidence-coverage-attribution-as-group-level-closed-form-coverage-allocation.md`

**Interfaces:**
- Consumes: API deletion-evaluation result.
- Produces: explicit lower-is-better evaluation summary without causal claims.

- [ ] Add typed evaluation result and display primary/reverse/random AUC plus both deltas and randomization provenance.
- [ ] Render unavailable/not-applicable reasons distinctly; do not show AUC zero for `G=0`.
- [ ] Record the frozen deletion semantics and fixed randomization algorithm in ADR-0031.
- [ ] Run Python tests, web tests/lint/build, and relevant Docker/browser acceptance if available.
- [ ] Review the diff for dense pair materialization, silent approximation, RNG runtime dependency, and unrelated changes.
