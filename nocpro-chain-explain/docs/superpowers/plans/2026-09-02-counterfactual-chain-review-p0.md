# Counterfactual Chain Review P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an exact, asynchronous, review-only Counterfactual Chain Review that evaluates bounded `REMOVE_MEMBER` and exact-Audit `SPLIT_CHAIN` alternatives end to end.

**Architecture:** A new `tier2.counterfactual` package owns typed configuration, immutable candidates, exact affected-region evaluation, hard gates, Pareto selection, and orchestration. A separate job manager and API surface pin snapshot/artifact identities and cache compatible results; PostgreSQL stores lifecycle/result envelopes, and the React REVIEW tab polls and renders operation-level partial results.

**Tech Stack:** Python 3.12 dataclasses/enums, existing indexed evidence/Tier-1B/Tier-2 modules, FastAPI/Pydantic, SQLAlchemy/Alembic/PostgreSQL JSONB, React/Vite/TypeScript/Vitest, pytest, Docker Compose, Playwright/Chromium.

## Global Constraints

- Work on `feat/counterfactual-review`, based on `feat/p2-topology-foundation`; do not merge `dev`.
- Recommendations never mutate the NocPro partition or become evidence/system facts.
- P0 operations are only `REMOVE_MEMBER` and `SPLIT_CHAIN`.
- Candidate evaluation is exact and bounded; no sampling, approximation, second clustering pass, or hidden default.
- `SYNTHETIC_ONLY` policy cannot recommend on production data.
- Missing Audit disables only Split; domain-level unavailability does not fail the job.
- Every job is pinned to snapshot, chain, engine/config, and artifact fingerprints.
- Existing immutable primitive evidence is reused; candidate-dependent aggregates are recomputed.
- Use TDD and commit each independently testable task.

---

### Task 1: Typed counterfactual config and domain contracts

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/models.py`
- Create: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/config.py`
- Create: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/__init__.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/configuration/analysis_config.py`
- Create: `nocpro-chain-explain/config/thresholds/e2e-counterfactual.yaml`
- Test: `nocpro-chain-explain/tests/test_counterfactual_config.py`

**Interfaces:**
- Produces `CounterfactualConfig`, `CalibrationStatus`, `Operation`, `DomainStatus`, `CandidateStatus`, `MetricAvailability`, `MetricVector`, `EditCost`, `PartitionDelta`, `CandidateEvaluation`, `OperationResult`, and `CounterfactualResult`.
- `AnalysisConfig.counterfactual` is `CounterfactualConfig | None`; invalid or absent envelopes retain a structured reason rather than supplying defaults.

- [ ] **Step 1: Write failing config and model tests**

```python
def test_counterfactual_config_requires_every_numeric_field(tmp_path):
    path = write_config(tmp_path, without="counterfactual.improvement.pareto_tolerance")
    config = load_analysis_config(path)
    assert config.counterfactual is None
    assert config.counterfactual_reason == "COUNTERFACTUAL_CONFIG_INCOMPLETE"

def test_partition_delta_rejects_alarm_loss():
    with pytest.raises(ValueError, match="alarm universe"):
        PartitionDelta(before=(("C", ("A", "B")),), after=(("C", ("A",)),))
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `uv run pytest tests/test_counterfactual_config.py -q`  
Expected: collection failure because `tier2.counterfactual` does not exist.

- [ ] **Step 3: Implement strict typed parsing and immutable contracts**

```python
@dataclass(frozen=True)
class CounterfactualConfig:
    config_version: str
    calibration_status: CalibrationStatus
    max_chain_members: int
    max_remove_candidates: int
    max_split_candidates: int
    max_recommendations: int
    membership_support_below: float
    representativeness_below: float
    adverse_margin_below: float
    minimum_membership_improvement: float
    minimum_coverage_improvement: float
    minimum_conductance_improvement: float
    pareto_tolerance: float
```

Validate non-empty version, positive integer ceilings, unit-interval trigger fields, finite margins, and non-negative improvement values. Keep shipped production `v1.yaml` without an invented envelope, so it remains fail-closed. Add a separate explicit `e2e-counterfactual.yaml` with `calibration_status: SYNTHETIC_ONLY`; it remains unable to recommend for real production sources.

- [ ] **Step 4: Run config/model tests**

Run: `uv run pytest tests/test_counterfactual_config.py tests/test_analysis_config.py -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add nocpro-chain-explain/services/analysis-worker/tier2/counterfactual nocpro-chain-explain/services/analysis-worker/configuration/analysis_config.py nocpro-chain-explain/config/thresholds/e2e-counterfactual.yaml nocpro-chain-explain/tests/test_counterfactual_config.py
git commit -m "feat: add counterfactual review contracts"
```

### Task 2: Deterministic candidate generation and partition preservation

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/candidates.py`
- Test: `nocpro-chain-explain/tests/test_counterfactual_candidates.py`

**Interfaces:**
- Consumes Tier-1B member analysis and exact `StructuralAuditResult`.
- Produces `generate_remove_candidates(...) -> CandidateBatch` and `generate_split_candidates(...) -> CandidateBatch` with deterministic discovered/evaluated counts and canonical IDs.

- [ ] **Step 1: Write failing generation tests**

```python
def test_remove_preserves_alarm_as_singleton():
    batch = generate_remove_candidates(snapshot_ref, chain, suspicious_members, config)
    delta = batch.candidates[0].partition_delta
    assert delta.after == (("C", ("A", "B", "C")), ("singleton:X", ("X",)))

def test_singleton_audit_cut_is_canonical_remove():
    batch = generate_split_candidates(snapshot_ref, chain, audit_with_cut({"X"}), config)
    assert batch.candidates == ()
    assert batch.canonical_remove_member_ids == ("X",)

def test_candidate_limit_is_deterministic():
    first = generate_remove_candidates(snapshot_ref, chain, triggers_in_random_order(), config)
    second = generate_remove_candidates(snapshot_ref, chain, triggers_in_reverse_order(), config)
    assert first == second
    assert first.discovered_count > first.evaluated_count
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `uv run pytest tests/test_counterfactual_candidates.py -q`  
Expected: import failure for candidate generators.

- [ ] **Step 3: Implement bounded trigger union and exact-Audit cut reuse**

REMOVE triggers are the deterministic union of weak role, membership threshold, representativeness threshold, adverse margin, and eligible contradiction. SPLIT accepts only feasible exact Audit cuts. Canonicalize sorted IDs and hash the pinned identity, operation, affected sets, artifact fingerprints, engine version, and config version.

```python
def deterministic_candidate_id(identity: ReviewIdentity, operation: Operation, delta: PartitionDelta) -> str:
    payload = canonical_json((identity.cache_tuple(), operation.value, delta.canonical_tuple()))
    return sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run candidate tests**

Run: `uv run pytest tests/test_counterfactual_candidates.py -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/candidates.py nocpro-chain-explain/tests/test_counterfactual_candidates.py
git commit -m "feat: generate bounded counterfactual candidates"
```

### Task 3: Exact affected-region metrics, hard gates, and Pareto frontier

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/evaluator.py`
- Create: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/pareto.py`
- Test: `nocpro-chain-explain/tests/test_counterfactual_evaluator.py`
- Test: `nocpro-chain-explain/tests/test_counterfactual_equivalence.py`

**Interfaces:**
- Produces `evaluate_candidate(package, candidate, artifacts, config) -> CandidateEvaluation`.
- Produces `select_frontier(evaluations, config) -> FrontierResult`.
- `MetricVector` contains weak count, minimum membership support, union coverage, component count, exact minimum feasible Audit conductance, Audit severity, and eligible external contradiction count with per-field availability.

- [ ] **Step 1: Write failing exactness and Pareto tests**

```python
def test_missing_metric_is_not_zero():
    result = compare_vectors(current, replace(after, audit_conductance=MetricValue.unavailable()))
    assert result.reason == "REQUIRED_METRIC_UNAVAILABLE"

def test_external_contradiction_hard_rejects():
    result = evaluate_candidate(package, candidate, artifacts_with_eligible_contradiction, config)
    assert result.status is CandidateStatus.EXTERNALLY_CONTRADICTED

def test_incomparable_candidates_both_remain_on_frontier():
    frontier = select_frontier((better_membership, better_structure), config)
    assert {item.candidate_id for item in frontier.items} == {"membership", "structure"}

def test_affected_region_equals_full_recompute(two_chain_package):
    assert evaluate_affected_region(two_chain_package, candidate) == evaluate_full_partition(two_chain_package, candidate)
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `uv run pytest tests/test_counterfactual_evaluator.py tests/test_counterfactual_equivalence.py -q`  
Expected: missing evaluator/Pareto symbols.

- [ ] **Step 3: Implement exact aggregate recomputation**

Reuse indexed primitive statistics and rebuild affected chain Fit, MembershipSupport, roles, descriptors, evidence coverage, graph/audit aggregates, and external summaries. Define conductance as the minimum exact feasible cut conductance among affected non-singleton chains; skipped/unscorable Audit remains unavailable.

- [ ] **Step 4: Implement hard gates and bounded deterministic Pareto order**

```python
def dominates(left: CandidateEvaluation, right: CandidateEvaluation, policy: CounterfactualConfig) -> bool:
    comparable = required_metric_pairs(left.after, right.after)
    return all(no_worse(pair, policy.pareto_tolerance) for pair in comparable) and any(
        materially_better(pair, policy) for pair in comparable
    )
```

Order an over-limit frontier by external support, material-improvement count, structured edit cost, operation enum, and stable candidate ID. Record pre-limit count and truncation.

- [ ] **Step 5: Run evaluator/equivalence tests**

Run: `uv run pytest tests/test_counterfactual_evaluator.py tests/test_counterfactual_equivalence.py -q`  
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/evaluator.py nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/pareto.py nocpro-chain-explain/tests/test_counterfactual_evaluator.py nocpro-chain-explain/tests/test_counterfactual_equivalence.py
git commit -m "feat: evaluate counterfactual alternatives exactly"
```

### Task 4: Operation orchestrator and synthetic calibration guard

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/analysis.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/__init__.py`
- Test: `nocpro-chain-explain/tests/test_counterfactual_analysis.py`

**Interfaces:**
- Produces `analyze_counterfactual_review(package, chain_id, *, tier1b_artifact, audit_artifact, external_artifact, config) -> CounterfactualResult`.
- The result has independent REMOVE/SPLIT operation states and an overall successful domain envelope.

- [ ] **Step 1: Write failing partial-result and calibration tests**

```python
def test_missing_audit_only_disables_split():
    result = analyze_counterfactual_review(package, "C1", tier1b_artifact=tier1b, audit_artifact=None, config=synthetic_config)
    assert result.remove.status is DomainStatus.AVAILABLE
    assert result.split.reason == "STRUCTURAL_AUDIT_UNAVAILABLE"

def test_synthetic_policy_cannot_recommend_on_real_source():
    result = analyze_counterfactual_review(real_package, "C1", tier1b_artifact=tier1b, audit_artifact=audit, config=synthetic_config)
    assert result.recommendation_status is DomainStatus.UNAVAILABLE
    assert result.reason == "COUNTERFACTUAL_POLICY_NOT_CALIBRATED"
    assert result.evaluated_candidates
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_counterfactual_analysis.py -q`  
Expected: analyzer missing.

- [ ] **Step 3: Implement operation isolation and recommendation guard**

Return `NOT_APPLICABLE` for singleton operations and two-member Split, merge singleton cuts into Remove generation, preserve exact evaluated metrics when recommendation is not calibrated, and never turn operation unavailability into an exception.

- [ ] **Step 4: Run analysis tests**

Run: `uv run pytest tests/test_counterfactual_analysis.py -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add nocpro-chain-explain/services/analysis-worker/tier2/counterfactual nocpro-chain-explain/tests/test_counterfactual_analysis.py
git commit -m "feat: orchestrate partial counterfactual review"
```

### Task 5: Snapshot-bound async jobs, compatible cache, and PostgreSQL persistence

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/jobs.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/persistence/models.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/persistence/repository.py`
- Create: `nocpro-chain-explain/migrations/versions/0004_counterfactual_jobs.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/workspace.py`
- Test: `nocpro-chain-explain/tests/test_counterfactual_jobs.py`
- Test: `nocpro-chain-explain/tests/test_postgres_counterfactual_jobs.py`

**Interfaces:**
- Produces `CounterfactualJobManager.submit(...)`, `.get(job_id)`, `.latest_compatible(...)`, `.wait(...)`, and `.shutdown()`.
- Repository persists job identity/status/progress/error, cache fingerprint, result JSONB, timestamps, and pinned artifact identities.

- [ ] **Step 1: Write failing job/cache/persistence tests**

```python
def test_same_pinned_identity_deduplicates_inflight(manager):
    first = manager.submit(request)
    second = manager.submit(request)
    assert second.job_id == first.job_id
    assert second.deduplicated is True

def test_artifact_fingerprint_change_misses_cache(manager):
    first = manager.submit(request_with(audit_fingerprint="audit-v1"))
    second = manager.submit(request_with(audit_fingerprint="audit-v2"))
    assert second.job_id != first.job_id

async def test_domain_unavailable_persists_succeeded(repository, manager):
    view = manager.wait(manager.submit(not_calibrated_request).job_id)
    assert view.status is JobStatus.SUCCEEDED
    assert (await repository.counterfactual_job(view.job_id)).result["reason"] == "COUNTERFACTUAL_POLICY_NOT_CALIBRATED"
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_counterfactual_jobs.py tests/test_postgres_counterfactual_jobs.py -q`  
Expected: missing manager/model/repository methods.

- [ ] **Step 3: Implement manager and DB migration/repository**

Use the existing job state enum and executor pattern, but keep a separate manager/cache namespace. Persist immutable submission identity before execution, update status transactionally, and store the serialized result on success. A source snapshot becoming inactive does not change the package/artifacts captured by submission.

- [ ] **Step 4: Run job and PostgreSQL tests**

Run: `uv run pytest tests/test_counterfactual_jobs.py tests/test_postgres_counterfactual_jobs.py -q`  
Expected: unit tests pass; PostgreSQL tests skip only when their documented test DSN is absent.

- [ ] **Step 5: Commit**

```bash
git add nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/jobs.py nocpro-chain-explain/services/api/nocpro_api/persistence nocpro-chain-explain/migrations/versions/0004_counterfactual_jobs.py nocpro-chain-explain/services/api/nocpro_api/workspace.py nocpro-chain-explain/tests/test_counterfactual_jobs.py nocpro-chain-explain/tests/test_postgres_counterfactual_jobs.py
git commit -m "feat: persist counterfactual review jobs"
```

### Task 6: FastAPI contracts and polling endpoints

**Files:**
- Modify: `nocpro-chain-explain/services/api/nocpro_api/schemas.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/serializers.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/routes.py`
- Test: `nocpro-chain-explain/tests/test_counterfactual_api.py`

**Interfaces:**
- Adds submission, job, operation, candidate, metric, frontier, and result Pydantic views.
- Adds `POST /api/v1/chains/{chain_id}/review`, `GET /api/v1/review-jobs/{job_id}`, and `GET /api/v1/chains/{chain_id}/review` with the active snapshot pinned at submission.

- [ ] **Step 1: Write failing endpoint tests**

```python
async def test_review_submit_poll_and_cached_lookup(client):
    submission = await client.post("/api/v1/chains/C1/review")
    assert submission.status_code == 202
    job_id = submission.json()["job_id"]
    completed = await poll_review(client, job_id)
    assert completed["status"] == "SUCCEEDED"
    cached = await client.get("/api/v1/chains/C1/review")
    assert cached.json()["job_id"] == job_id
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/test_counterfactual_api.py -q`  
Expected: 404 for new routes.

- [ ] **Step 3: Implement schemas, serialization, and routes**

Serialize null/unavailable metrics explicitly, expose discovered/evaluated/truncated diagnostics, and translate unknown jobs/chains through existing 404/422 conventions. The convenience GET never returns an incompatible cached result.

- [ ] **Step 4: Run API tests**

Run: `uv run pytest tests/test_counterfactual_api.py tests/test_api.py -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add nocpro-chain-explain/services/api/nocpro_api/schemas.py nocpro-chain-explain/services/api/nocpro_api/serializers.py nocpro-chain-explain/services/api/nocpro_api/routes.py nocpro-chain-explain/tests/test_counterfactual_api.py
git commit -m "feat: expose counterfactual review api"
```

### Task 7: React REVIEW tab and component tests

**Files:**
- Create: `nocpro-chain-explain/services/web/src/CounterfactualReview.tsx`
- Create: `nocpro-chain-explain/services/web/src/CounterfactualReview.test.tsx`
- Modify: `nocpro-chain-explain/services/web/src/types.ts`
- Modify: `nocpro-chain-explain/services/web/src/api.ts`
- Modify: `nocpro-chain-explain/services/web/src/App.tsx`
- Modify: `nocpro-chain-explain/services/web/src/App.css`

**Interfaces:**
- `api.submitReview`, `api.reviewJob`, and `api.latestReview` mirror Task 6.
- `CounterfactualReview` renders job/calibration status, independent operation availability, search diagnostics, proposal details, before/after metrics, external state, and review-only wording.

- [ ] **Step 1: Write failing component tests**

```tsx
it('renders partial REMOVE result while SPLIT is unavailable', async () => {
  render(<CounterfactualReview chainId="C1" />)
  expect(await screen.findByText('REMOVE_MEMBER')).toBeInTheDocument()
  expect(screen.getByText('STRUCTURAL_AUDIT_UNAVAILABLE')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /apply/i })).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run and confirm failure**

Run: `pnpm --dir services/web test -- CounterfactualReview.test.tsx`  
Expected: missing component/types.

- [ ] **Step 3: Implement typed API client and REVIEW tab**

Opening REVIEW checks compatible cache, triggers only when missing, polls queued/running jobs, and leaves Explain/Audit usable. Render `BETTER_SUPPORTED`, `EXTERNALLY_SUPPORTED`, or exact unavailability wording; include a visible “proposal only; NocPro was not changed” notice.

- [ ] **Step 4: Run web tests and build**

Run: `pnpm --dir services/web test`  
Expected: all Vitest tests pass.  
Run: `pnpm --dir services/web build`  
Expected: TypeScript/Vite build succeeds.

- [ ] **Step 5: Commit**

```bash
git add nocpro-chain-explain/services/web/src
git commit -m "feat: add counterfactual review ui"
```

### Task 8: Synthetic mutation fixtures, benchmark, Docker/Chromium acceptance, and status docs

**Files:**
- Create: `nocpro-mock/docs/examples/synthetic/counterfactual_remove/snapshot_000.json`
- Create: `nocpro-mock/docs/examples/synthetic/counterfactual_remove/expected_assertions.yaml`
- Create: `nocpro-mock/docs/examples/synthetic/counterfactual_split/snapshot_000.json`
- Create: `nocpro-mock/docs/examples/synthetic/counterfactual_split/expected_assertions.yaml`
- Modify: `nocpro-mock/src/nocpro_mock/scenarios/sequence_fixtures.py`
- Create: `nocpro-chain-explain/tests/test_counterfactual_mutations.py`
- Create: `nocpro-chain-explain/benchmarks/benchmark_counterfactual.py`
- Create: `nocpro-chain-explain/tests/e2e/test_counterfactual_review.py`
- Modify: `nocpro-chain-explain/tests/e2e/run_acceptance.sh`
- Modify: `nocpro-chain-explain/README.md`

**Interfaces:**
- Synthetic fixtures are labelled `SYNTHETIC_TEST`, use an explicit synthetic config version, and encode known true partitions plus one intentional extra-member or over-merge mutation.
- Benchmark emits issue detection, repair accuracy, false recommendation, abstention, edit distance, ARI/AMI, and latency without setting a production threshold.

- [ ] **Step 1: Write failing mutation acceptance tests**

```python
def test_extra_member_mutation_recommends_expected_remove():
    result = run_fixture("counterfactual_remove")
    assert result.recommendations[0].operation == "REMOVE_MEMBER"
    assert result.recommendations[0].member_ids == ("X",)

def test_overmerge_mutation_recommends_expected_split():
    result = run_fixture("counterfactual_split")
    assert result.recommendations[0].operation == "SPLIT_CHAIN"

def test_clean_truth_abstains():
    assert run_clean_fixture().outcome == "NO_CLEAR_ALTERNATIVE"
```

- [ ] **Step 2: Run and confirm fixtures fail before generator registration**

Run: `uv run pytest tests/test_counterfactual_mutations.py -q`  
Expected: fixture lookup failure.

- [ ] **Step 3: Add labelled fixtures and benchmark harness**

Keep truth and mutation metadata explicit, preserve topology/source version provenance when topology exists, and never expose synthetic configuration as production calibrated.

- [ ] **Step 4: Add Docker/Chromium flow**

The test sends the synthetic snapshot from Mock through Kafka chunks/barrier, waits for READY, opens the chain, opens REVIEW, polls the separate job, verifies REMOVE/SPLIT output and the no-Apply notice, and checks persisted job/result provenance.

- [ ] **Step 5: Run complete verification**

Run: `uv run pytest -q` in `nocpro-chain-explain`  
Expected: all non-environment-gated tests pass.  
Run: `uv run pytest -q` in `nocpro-mock`  
Expected: all non-environment-gated tests pass.  
Run: `pnpm --dir services/web test && pnpm --dir services/web build`  
Expected: tests and build pass.  
Run: `./tests/e2e/run_acceptance.sh`  
Expected: Docker recovery, existing browser flows, synthetic P2, and Counterfactual REVIEW flow pass; cleanup succeeds.

- [ ] **Step 6: Update status and commit**

Document exact proof levels: synthetic correctness, measured latency, production policy not calibrated, and no production topology/delta claim.

```bash
git add nocpro-mock nocpro-chain-explain/benchmarks nocpro-chain-explain/tests/e2e nocpro-chain-explain/tests/test_counterfactual_mutations.py nocpro-chain-explain/README.md
git commit -m "test: verify counterfactual review end to end"
```

### Task 9: Final regression, diff review, and delivery commit audit

**Files:**
- Verify all files changed by Tasks 1-8.

**Interfaces:**
- Produces a clean feature branch with focused commits, no unrelated changes, and evidence-backed completion status.

- [ ] **Step 1: Run whitespace, status, and change-scope checks**

Run: `git diff --check feat/p2-topology-foundation...HEAD`  
Expected: no output.  
Run: `git status --short`  
Expected: empty after final documentation commit.

- [ ] **Step 2: Run complete focused regression one final time**

Run: `uv run pytest -q` in both Python projects, then web tests/build.  
Expected: all non-gated tests pass and gated tests report explicit skips.

- [ ] **Step 3: Inspect commit and diff summary**

Run: `git log --oneline feat/p2-topology-foundation..HEAD`  
Expected: design plus focused Task commits.  
Run: `git diff --stat feat/p2-topology-foundation...HEAD`  
Expected: only Counterfactual Review, synthetic fixture, API/UI, migration, tests, benchmark, and status-doc files.
