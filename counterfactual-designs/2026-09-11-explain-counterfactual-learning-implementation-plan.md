# Explain Counterfactual Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing deterministic Counterfactual Review into a versioned review-memory and learning system using the existing histogram/KDE delay model, deterministic similar reviewed-case retrieval, and an XGBoost learning-to-rank model, while keeping all real NocPro mutation fail-closed until an authoritative upstream contract exists.

**Architecture:** The deterministic REMOVE/SPLIT/MOVE/MERGE generator, exact metric evaluator, hard gates, and Pareto frontier remain the authority for candidate eligibility. A new review-learning plane freezes every candidate exposure, stores append-only human decisions, builds leakage-safe case fingerprints and temporal features, and optionally reorders eligible candidates with a promoted ranker. A separate mutation port supports only `L0_REVIEW_ONLY` and `L1_SHADOW_MUTATION` in this repository; production dispatch cannot be enabled without a documented NocPro compare-and-set/idempotency/post-state contract.

**Tech Stack:** Python 3.12, FastAPI/Pydantic v2, SQLAlchemy 2/Alembic/PostgreSQL, existing pure-Python temporal KDE implementation, XGBoost 3.3 `XGBRanker` with `rank:ndcg`, React 19/TypeScript/Vitest/Playwright, pytest.

## Global Constraints

- Implement review-only learning first. No task may silently enable authoritative chain mutation.
- Models rank only candidates already produced by the deterministic engine and passing mandatory hard gates.
- Preserve deterministic/Pareto ordering as the fallback and as the offline baseline.
- Store all evaluated candidates, including rejected, dominated, unshown, and unreviewed candidates. Never convert “not reviewed” into a negative label.
- Store human feedback as `PO_ASSERTED` initially. Approval does not prove application or operational benefit.
- Feedback is append-only. Corrections create a new record and supersede, retract, or contradict earlier records without overwriting history.
- Retrieval, KDE materialization, and training use an exclusive cutoff: only artifacts with `created_at < cutoff` or `event_time < cutoff` are eligible.
- Keep every review group and every lineage component wholly inside one train/validation/test partition.
- Exclude raw alarm IDs, chain IDs, snapshot IDs, reviewer IDs, and direct device codes from similarity/ranker features.
- Missing evidence has an explicit availability indicator. Never impute an unavailable topology/KDE/similarity feature as numeric zero.
- IP topology remains `PHYSICAL_ADJACENCY`; IT source relations remain navigation-only until dependency direction is verified.
- No immediate online retraining. Training, evaluation, approval, activation, rollback, and audit are separate batch operations.
- Rank scores are relative within one review group, not probabilities of correctness.
- The server derives reviewer identity. The browser must not submit `operator_id` as authority.
- XGBoost ranking weights are group-level, matching the `XGBRanker` API; candidate truth tiers determine relevance labels, while a frozen label policy derives one weight per review group.
- Real mutation remains `MUTATION_UNAVAILABLE` until stable identifiers, authoritative versioning, compare-and-set, idempotency, dry-run, ACK, post-state observation, and authorization are proven against an upstream sandbox.
- Preserve current API response compatibility through additive `counterfactual-review-v2` fields and an explicit legacy feedback normalization path.

---

## Verified repository baseline (2026-09-11)

- Branch: `feat/explain-refactor-model`, commit `b4a2c83`; worktree clean at plan creation.
- Alembic head: `0012`.
- Focused current behavior: 73 tests passed across temporal delay, counterfactual generation/evaluation/API, and operator feedback.
- Deterministic candidate generation already supports `REMOVE_MEMBER`, `SPLIT_CHAIN`, `MOVE_MEMBER`, and `MERGE_CHAINS` in `services/analysis-worker/tier2/counterfactual/`.
- Candidate IDs already hash the complete `ReviewIdentity`, operation, and canonical `PartitionDelta`.
- Exact before/after metrics, signed deltas, hard-gate status, Pareto state, and candidate exposure candidates already exist in `counterfactual-review-v1` output.
- Histogram/Gaussian-KDE selection, exclusive cutoff handling, episode balancing, lineage-prefix fingerprints, artifact serialization, PostgreSQL persistence, and runtime lookup already exist as `TEMPORAL_DELAY_MODEL_V2`.
- Similar Chains already provides a versioned TF-IDF/cosine fingerprint, active-block reporting, and same-lineage exclusion, but it is chain similarity rather than reviewed-operation similarity.
- Current `operator_feedback` is too coarse: it accepts only recommendation IDs, accepts client-supplied `operator_id`, supports only approved/rejected aliases, upserts mutable rows, and does not capture exposure, confidence, reasons, truth tier, lifecycle, manual correction, feature fingerprints, or supersession.
- Current UI calls PostgreSQL “Golden Ground Truth”; that wording is unsupported. Persisted feedback is currently only an operator assertion.
- `xgboost`, NumPy, and SciPy are not current project dependencies.
- There is no real NocPro mutation API/adapter contract in the repository.

## Delivery gates

| Gate | Deliverable | Permitted behavior |
|---|---|---|
| G0 | Current deterministic baseline | Existing proposal-only review |
| G1 | Exposure + rich append-only feedback | Store/retrieve PO experience; no ranking change |
| G2 | Review Case Store | Show deterministic similar prior cases |
| G3 | KDE candidate features | Show temporal evidence; no ranking change |
| G4 | Ranker shadow artifact | Compute scores, retain deterministic order |
| G5 | Promoted review ranker | Reorder eligible candidates with explicit fallback |
| G6 | Shadow mutation adapter | Build/dry-run requests against mock only |
| G7 | Controlled upstream canary | Blocked until a separate upstream contract review approves it |

---

### Task 1: Freeze the review-learning configuration and data-readiness contract

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/config.py`
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/readiness.py`
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/__init__.py`
- Create: `nocpro-chain-explain/config/review-learning/v1.yaml`
- Create: `nocpro-chain-explain/tests/test_review_learning_config.py`

**Interfaces:**
- Produces: `ReviewLearningConfig`, `ReviewLearningMode`, `DataReadiness`, and `assess_data_readiness(...)` for all later tasks.
- Consumes: existing source kinds, taxonomy provenance, temporal-delay artifacts, and lineage identifiers.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_review_learning_defaults_are_fail_closed():
    config = load_review_learning_config("config/review-learning/v1.yaml")
    assert config.mode is ReviewLearningMode.REVIEW_MEMORY
    assert config.ranker.mode is RankerMode.DISABLED
    assert config.mutation.mode is MutationMode.REVIEW_ONLY

def test_readiness_rejects_single_export_as_sequential_training_data():
    result = assess_data_readiness(
        verified_episode_count=0,
        reviewed_group_count=0,
        taxonomy_status="UNVERIFIED",
        lineage_status="UNAVAILABLE",
        operation_counts={},
    )
    assert result.ranker_status == "BLOCKED_BY_REVIEW_DATA"
    assert result.kde_status == "BLOCKED_BY_EPISODE_AND_TAXONOMY_DATA"
```

- [ ] **Step 2: Run the tests and verify that the module is absent**

Run: `PYTHONPATH=services/analysis-worker .venv/bin/pytest -q tests/test_review_learning_config.py`

Expected: collection fails because `review_learning` does not exist.

- [ ] **Step 3: Implement frozen enums and validated configuration**

```python
class ReviewLearningMode(str, Enum):
    EXPOSURE_ONLY = "EXPOSURE_ONLY"
    REVIEW_MEMORY = "REVIEW_MEMORY"
    RANKER_SHADOW = "RANKER_SHADOW"
    RANKER_ACTIVE = "RANKER_ACTIVE"

@dataclass(frozen=True)
class PromotionThresholds:
    min_review_groups: int
    min_groups_per_enabled_operation: int
    min_explicit_positive_per_operation: int
    min_explicit_negative_per_operation: int

@dataclass(frozen=True)
class ReviewLearningConfig:
    config_version: str
    mode: ReviewLearningMode
    retrieval: RetrievalConfig
    ranker: RankerConfig
    mutation: MutationConfig
    promotion: PromotionThresholds
```

Use initial evidence-volume preconditions of 200 independent review groups, 30 groups per enabled operation, and at least 10 explicit positive and 10 explicit negative judgments per enabled operation. These are necessary readiness checks, never sufficient promotion evidence.

- [ ] **Step 4: Implement a versioned readiness report**

`assess_data_readiness(...) -> DataReadiness` must return independent statuses for taxonomy, episodes/lineage, exposure, feedback, retrieval, KDE, ranker training, ranker promotion, and mutation. It must never collapse them into one boolean.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=services/analysis-worker .venv/bin/pytest -q tests/test_review_learning_config.py`

Expected: all tests pass.

Commit: `feat(explain): add fail-closed review learning configuration`

---

### Task 2: Define immutable review, exposure, and truth-tier contracts

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/contracts.py`
- Create: `nocpro-chain-explain/tests/test_review_learning_contracts.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/public_contract.py`
- Test: `nocpro-chain-explain/tests/test_counterfactual_api.py`

**Interfaces:**
- Produces: `ReviewSession`, `CandidateExposure`, `ReviewFeedback`, `ManualCorrection`, `ReviewCase`, `TruthTier`, `FeedbackStatus`, and stable SHA-256 fingerprint helpers.
- Consumes: `ReviewIdentity`, `PartitionDelta`, and `counterfactual-review-v1` candidates.

- [ ] **Step 1: Write failing contract tests**

Test canonical decision normalization, confidence bounds, required candidate for candidate-level decisions, group-level `NONE_ACCEPTABLE`, manual correction partition conservation, append-only supersession references, and stable fingerprints under dictionary ordering.

```python
@pytest.mark.parametrize("legacy,canonical", [
    ("APPROVED", "APPROVE"), ("ACCEPTED", "APPROVE"), ("REJECTED", "REJECT")
])
def test_legacy_decisions_normalize_only_at_ingress(legacy, canonical):
    assert normalize_review_decision(legacy).value == canonical

def test_none_acceptable_cannot_name_a_candidate():
    with pytest.raises(ValueError):
        ReviewFeedback(decision=ReviewDecision.NONE_ACCEPTABLE, candidate_id="cand-1", ...)
```

- [ ] **Step 2: Implement exact enums**

```python
class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DEFER = "DEFER"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NONE_ACCEPTABLE = "NONE_ACCEPTABLE"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"

class TruthTier(str, Enum):
    PO_ASSERTED = "PO_ASSERTED"
    EXPERT_CONSENSUS = "EXPERT_CONSENSUS"
    APPLIED_CONFIRMED = "APPLIED_CONFIRMED"
    OUTCOME_VERIFIED = "OUTCOME_VERIFIED"
    OUTCOME_CONTRADICTED = "OUTCOME_CONTRADICTED"

class FeedbackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"
```

- [ ] **Step 3: Define immutable candidate exposure**

`CandidateExposure` must include `review_id`, `candidate_id`, `candidate_fingerprint`, original deterministic rank, displayed rank, `shown_to_reviewer`, deterministic eligibility, hard-gate/Pareto state, generator/config versions, exposure policy, immutable feature payload, and feature fingerprint.

- [ ] **Step 4: Add `counterfactual-review-v2` as an additive projection**

Keep all v1 fields. Add `review_id`, `candidate_set_fingerprint`, `exposure_status`, `ranking`, `similar_case_status`, `temporal_feature_status`, `allowed_review_actions`, and `mutation_capability`. Default values must state deterministic order, no case memory, no promoted ranker, and `MUTATION_UNAVAILABLE`.

- [ ] **Step 5: Run contract regression and commit**

Run: `PYTHONPATH=services/analysis-worker:services/api:../nocpro-mock/src .venv/bin/pytest -q tests/test_review_learning_contracts.py tests/test_counterfactual_api.py`

Commit: `feat(explain): define immutable review learning contracts`

---

### Task 3: Add normalized PostgreSQL storage without mutating legacy history

**Files:**
- Create: `nocpro-chain-explain/migrations/versions/0013_review_learning_store.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/persistence/models.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/persistence/repository.py`
- Create: `nocpro-chain-explain/tests/test_postgres_review_learning_store.py`
- Modify: `nocpro-chain-explain/tests/e2e/test_postgres_migrations_runtime.py`

**Interfaces:**
- Produces repository methods `persist_review_bundle`, `append_review_feedback`, `supersede_feedback`, `retract_feedback`, `review_cases_before`, `persist_model_artifact`, and `active_model_artifact`.
- Consumes contracts from Task 2.

- [ ] **Step 1: Write PostgreSQL tests for atomicity and immutability**

Tests must prove: one transaction stores the session and every exposure; replay is idempotent by fingerprint; changing immutable payload raises conflict; feedback insert never updates an existing row; supersession changes lifecycle through a new event; and a failed exposure insert rolls back the entire bundle.

- [ ] **Step 2: Add migration `0013` after current head `0012`**

Create these tables:

```text
review_session(review_id PK, job_id UNIQUE, snapshot_id, snapshot_version,
 chain_id, review_time, source_kind, lineage_component_id,
 candidate_set_fingerprint, generator_version, config_version,
 delay_model_version, retrieval_version, ranker_version, exposure_policy,
 status, created_at)

candidate_exposure(review_id FK, candidate_id, candidate_fingerprint,
 operation, original_rank, displayed_rank, shown_to_reviewer,
 deterministic_eligibility, hard_gate_status, pareto_state,
 feature_schema_version, feature_payload JSONB, feature_fingerprint,
 created_at, PRIMARY KEY(review_id, candidate_id))

review_feedback(feedback_id PK, review_id FK, candidate_id NULL,
 reviewer_subject, reviewer_role, domain_scope JSONB, decision, confidence,
 reason_codes JSONB, reason_text, truth_tier, status,
 supersedes_feedback_id NULL FK, artifact_fingerprints JSONB, created_at)

feedback_lifecycle_event(event_id PK, feedback_id FK, event_type,
 actor_subject, reason, created_at)

manual_correction(correction_id PK, feedback_id UNIQUE FK,
 operation, partition_delta JSONB, correction_fingerprint, created_at)

review_case(case_id PK, review_id, candidate_id NULL, feedback_id,
 case_time, lineage_component_id, operation_pattern,
 fingerprint_schema_version, fingerprint_payload JSONB,
 fingerprint_hash, truth_tier, outcome_status, created_at)

review_model_artifact(model_version PK, model_family, feature_schema_version,
 label_policy_version, training_cutoff, corpus_fingerprint,
 artifact_uri, artifact_sha256, metadata_payload JSONB,
 approval_status, approved_by, approved_at, created_at)
```

Add indexes on `(case_time, operation_pattern)`, `(review_id, candidate_id)`, active feedback, lineage, and model family/approval status. Do not drop `operator_feedback`; migrate legacy records in a separate audited command after deployment.

- [ ] **Step 3: Implement repository DTOs and transaction boundaries**

`persist_review_bundle(session, exposures)` must compare existing fingerprints on conflict. `append_review_feedback` must use plain insert, never `ON CONFLICT DO UPDATE`.

- [ ] **Step 4: Verify upgrade/downgrade and restart read-back**

Run: `PYTHONPATH=services/analysis-worker:services/api:../nocpro-mock/src .venv/bin/pytest -q -m postgres tests/test_postgres_review_learning_store.py tests/e2e/test_postgres_migrations_runtime.py`

Expected: migration reaches `0013`, persisted bundles survive repository recreation, and downgrade refuses only when doing so would destroy non-migrated review-learning data.

- [ ] **Step 5: Commit**

Commit: `feat(explain): persist review sessions exposures and append-only feedback`

---

### Task 4: Replace client-asserted operator identity with a server principal

**Files:**
- Create: `nocpro-chain-explain/services/api/nocpro_api/review_principal.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/app.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/routes.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/schemas.py`
- Modify: `nocpro-chain-explain/services/web/src/api.ts`
- Modify: `nocpro-chain-explain/services/web/src/views/ValidationView.tsx`
- Create: `nocpro-chain-explain/tests/test_review_principal.py`
- Modify: `nocpro-chain-explain/tests/test_operator_feedback_api.py`

**Interfaces:**
- Produces: FastAPI dependency `reviewer_principal(request) -> ReviewerPrincipal`.
- Consumes: deployment-controlled identity mode and the rich feedback request from Task 2.

- [ ] **Step 1: Write security tests**

Prove a request cannot self-assert subject/role/domain; disabled identity returns 503; local development identity is rejected when `APP_ENV=production`; trusted-proxy headers are rejected from an untrusted peer; and dependency-injected principals work in unit tests.

- [ ] **Step 2: Implement three explicit modes**

```python
class ReviewIdentityMode(str, Enum):
    DISABLED = "DISABLED"
    LOCAL_DEV = "LOCAL_DEV"
    TRUSTED_PROXY = "TRUSTED_PROXY"

@dataclass(frozen=True)
class ReviewerPrincipal:
    subject: str
    role: str
    domain_scope: tuple[str, ...]
    authenticated: bool
    identity_source: str
```

`DISABLED` is the default. `LOCAL_DEV` uses server environment values and is forbidden in production. `TRUSTED_PROXY` requires an explicit trusted-peer CIDR allowlist and deployment documentation; until the gateway identity contract is tested, it is not a production-authentication claim.

- [ ] **Step 3: Remove `operator_id` from browser request bodies**

The request accepts `candidate_id`, canonical decision, confidence, reason codes/text, expected snapshot version, optional superseded feedback ID, and optional manual correction. Identity fields in the JSON body must be rejected as extra fields.

- [ ] **Step 4: Update UI copy**

Remove the editable operator ID and replace “PostgreSQL Golden Ground Truth” with “PO-asserted review evidence”. Show the server-returned reviewer subject, role, truth tier, and lifecycle.

- [ ] **Step 5: Run API/UI security tests and commit**

Run: `PYTHONPATH=services/analysis-worker:services/api:../nocpro-mock/src .venv/bin/pytest -q tests/test_review_principal.py tests/test_operator_feedback_api.py`

Run: `npm --prefix services/web test -- --run src/views/ValidationView.test.tsx`

Commit: `fix(explain): derive reviewer authority on the server`

---

### Task 5: Freeze every candidate exposure, not only the selected recommendation

**Files:**
- Create: `nocpro-chain-explain/services/api/nocpro_api/review_learning_service.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/workspace.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/jobs.py`
- Modify: `nocpro-chain-explain/services/analysis-worker/tier2/counterfactual/public_contract.py`
- Create: `nocpro-chain-explain/tests/test_candidate_exposure.py`
- Modify: `nocpro-chain-explain/tests/test_postgres_counterfactual_jobs.py`

**Interfaces:**
- Produces: `freeze_review_bundle(job_view, *, exposure_policy) -> tuple[ReviewSession, tuple[CandidateExposure, ...]]`.
- Consumes: a terminal successful job and its complete `evaluated_candidates` list.

- [ ] **Step 1: Write tests proving complete exposure capture**

Create a result containing hard-gate rejected, dominated, frontier-truncated, selected, and unshown candidates. Assert every evaluated candidate is stored once, original deterministic positions remain stable, displayed positions are separate, and unreviewed records have no label.

- [ ] **Step 2: Freeze the bundle at the terminal job persistence boundary**

Extend the current terminal state listener so `counterfactual_job` and its `review_session`/`candidate_exposure` rows commit atomically. Compute `candidate_set_fingerprint` over ordered candidate fingerprints, generator/config versions, and the exposure policy.

- [ ] **Step 3: Permit feedback on any evaluated candidate**

Replace the current `candidate_id in recommendation_ids` check with `candidate_id in evaluated_candidates`. Still reject unknown IDs, hard-gate-rejected approval, stale `expected_snapshot_version`, and candidate fingerprints that do not match the frozen exposure.

- [ ] **Step 4: Add group-level and manual feedback**

Allow `NONE_ACCEPTABLE` without a candidate ID. Allow `MANUAL_CORRECTION` only with a normalized partition delta whose alarm universe exactly matches the frozen affected region.

- [ ] **Step 5: Verify persistence/restart behavior and commit**

Run: `PYTHONPATH=services/analysis-worker:services/api:../nocpro-mock/src .venv/bin/pytest -q tests/test_candidate_exposure.py tests/test_operator_feedback_api.py tests/test_postgres_counterfactual_jobs.py`

Commit: `feat(explain): freeze all counterfactual candidate exposures`

---

### Task 6: Build deterministic reviewed-case fingerprints and retrieval

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/case_fingerprint.py`
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/case_similarity.py`
- Create: `nocpro-chain-explain/services/api/nocpro_api/review_case_service.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/routes.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/schemas.py`
- Create: `nocpro-chain-explain/tests/test_review_case_similarity.py`
- Create: `nocpro-chain-explain/tests/test_review_case_api.py`

**Interfaces:**
- Produces: `build_review_case_fingerprint(...)`, `compare_review_cases(...)`, `find_similar_review_cases(...)`, and `GET /api/v1/review-jobs/{job_id}/similar-cases`.
- Consumes: frozen exposure features, feedback, lineage, chain fingerprints, KDE summaries, and topology availability.

- [ ] **Step 1: Test block-wise comparison and abstention**

Tests must prove ID fields do not affect similarity, incompatible operation/domain/schema gates abstain, missing blocks renormalize weights, low common-block coverage returns `UNAVAILABLE`, future cases are excluded, and same-lineage cases are separated from different-incident results.

- [ ] **Step 2: Implement five explicit blocks**

```python
REVIEW_CASE_BLOCKS = (
    "chain_context",
    "evidence_shape",
    "temporal_shape",
    "topology_shape",
    "operation_pattern",
)

similarity = sum(weight[b] * block_score[b] for b in common) / sum(weight[b] for b in common)
```

Each block returns `AVAILABLE`, `UNAVAILABLE`, or `INCOMPATIBLE`; unavailable blocks are omitted from both numerator and denominator. Include the existing Similar Chains cosine as a versioned subscore inside `chain_context`, not as a replacement for the case fingerprint.

- [ ] **Step 3: Materialize a case only from active feedback**

Create the immutable case after an active candidate decision or manual correction. A superseded/retracted feedback remains auditable but is excluded from the serving retrieval corpus.

- [ ] **Step 4: Add API response diagnostics**

Return retrieval version, query fingerprint, corpus cutoff, common-block coverage, total compatible cases, top-k case IDs, per-block scores, decision, truth tier, outcome status, review time, and abstention reason.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=services/analysis-worker:services/api:../nocpro-mock/src .venv/bin/pytest -q tests/test_review_case_similarity.py tests/test_review_case_api.py`

Commit: `feat(explain): retrieve similar reviewed counterfactual cases`

---

### Task 7: Reuse Temporal Delay Model V2 as candidate evidence

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/temporal_features.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/review_learning_service.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/tier1a_coordinator.py`
- Create: `nocpro-chain-explain/tests/test_review_temporal_features.py`
- Modify: `nocpro-chain-explain/tests/test_temporal_delay_model.py`
- Modify: `nocpro-chain-explain/tests/test_postgres_snapshot_ingest.py`

**Interfaces:**
- Produces: `summarize_candidate_delay_features(package, candidate, *, model, taxonomy, cutoff) -> CandidateTemporalFeatures`.
- Consumes: existing `FrozenDelayModel`, `HistoricalTaxonomy`, and frozen candidate partitions.

- [ ] **Step 1: Write leakage and availability tests**

Test exact cutoff exclusion, same-lineage exclusion inherited by model construction, equal timestamp abstention, invalid timestamp abstention, missing taxonomy, insufficient relation support, TYPE-to-FAMILY fallback, and artifact/taxonomy mismatch.

- [ ] **Step 2: Compute candidate-level aggregates without retraining**

For pairs introduced/removed by the candidate delta, return available-pair count, eligible-pair count, coverage, mean and quartiles of positive score/local mass, atypical fraction, fallback fraction, relation counts, model version, cutoff, corpus fingerprint, and typed reason when unavailable.

- [ ] **Step 3: Preserve the current KDE authority boundary**

Do not call this output causal probability. Do not change hard-gate results or deterministic eligibility. If no valid model matches the snapshot/taxonomy/cutoff, persist an unavailable feature block and continue.

- [ ] **Step 4: Verify model persistence reuse**

Ensure the review path loads the exact immutable temporal model already persisted for the snapshot; it must not build an ad hoc model from the current review request.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=services/analysis-worker:services/api:../nocpro-mock/src .venv/bin/pytest -q tests/test_review_temporal_features.py tests/test_temporal_delay_model.py tests/test_postgres_snapshot_ingest.py`

Commit: `feat(explain): add frozen KDE evidence to review candidates`

---

### Task 8: Define the stable ranker feature and label schemas

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/features.py`
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/labels.py`
- Create: `nocpro-chain-explain/tests/test_review_ranker_features.py`
- Create: `nocpro-chain-explain/tests/test_review_ranker_labels.py`

**Interfaces:**
- Produces: `FEATURE_SCHEMA_VERSION = "cf-features-v1"`, `LABEL_POLICY_VERSION = "review-label-v1"`, `materialize_candidate_features(...)`, and `materialize_review_group_labels(...)`.
- Consumes: exact candidate metrics, operation evidence, KDE summaries, similar-case aggregates, source kind, quality, and eligible topology facts.

- [ ] **Step 1: Test deterministic feature ordering and identity exclusion**

Assert repeated materialization has the same vector/fingerprint; raw IDs never appear in feature names or values; available zero differs from unavailable; and operation one-hot order is fixed.

- [ ] **Step 2: Implement an explicit numeric schema**

Feature groups must include operation, exact before/after/signed deltas, edit cost, affected size, structural changes, evidence availability/quality, KDE aggregates, similar approved/rejected-case aggregates, source kind, and topology only when semantically eligible. Pair every optional numeric feature with `<name>__available`.

- [ ] **Step 3: Implement frozen label resolution**

```text
OUTCOME_VERIFIED approval       -> relevance 3
EXPERT_CONSENSUS/APPLIED approval -> relevance 2
PO_ASSERTED approval            -> relevance 1
REJECT/OUTCOME_CONTRADICTED     -> relevance 0
DEFER/INSUFFICIENT/unreviewed   -> excluded
NONE_ACCEPTABLE                 -> group has no positive candidate
```

Resolve only latest active feedback before the cutoff. Preserve disagreement diagnostics. Emit one group weight: `0.50` for PO-only evidence, `0.75` for expert consensus/applied confirmation, `1.00` for outcome-verified/contradicted evidence. Mixed groups use the highest tier actually used by an included label and record the tier mix.

- [ ] **Step 4: Test group integrity**

All candidates sharing a `review_id` must remain one `qid`. Reject groups with duplicate candidate IDs, mismatched feature schemas, no effective preference pairs, or feedback after cutoff.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=services/analysis-worker .venv/bin/pytest -q tests/test_review_ranker_features.py tests/test_review_ranker_labels.py`

Commit: `feat(explain): materialize leakage-safe ranker features and labels`

---

### Task 9: Add reproducible offline XGBoost training and evaluation

**Files:**
- Modify: `nocpro-chain-explain/pyproject.toml`
- Modify: `nocpro-chain-explain/uv.lock`
- Create: `nocpro-chain-explain/scripts/review_learning/materialize_training_corpus.py`
- Create: `nocpro-chain-explain/scripts/review_learning/train_ranker.py`
- Create: `nocpro-chain-explain/scripts/review_learning/evaluate_ranker.py`
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/ranker_artifact.py`
- Create: `nocpro-chain-explain/tests/test_ranker_training.py`
- Create: `nocpro-chain-explain/tests/test_ranker_evaluation.py`

**Interfaces:**
- Produces a frozen model JSON plus XGBoost model bytes and `RankerArtifactManifest`.
- Consumes feature/label rows grouped by `review_id` from Task 8.

- [ ] **Step 1: Add a separate ML dependency group**

Add XGBoost `3.3.x` to an `ml` dependency group and regenerate the lockfile. Keep the default API image free of training-only dependencies until Task 10 deliberately adds the serving runtime requirement.

- [ ] **Step 2: Write synthetic grouped-ranking tests**

Build at least six time-ordered review groups with multiple candidates. Assert each qid is contiguous, time/lineage splits do not overlap, training is deterministic under the frozen seed, and the serialized model reproduces predictions.

- [ ] **Step 3: Implement time-and-lineage split materialization**

Sort by review time, reserve later periods for validation/test, and move an entire lineage to the earliest partition in which it appears. Store excluded-group reasons and source-kind/operation/truth-tier distributions.

- [ ] **Step 4: Train `XGBRanker`**

Use `objective="rank:ndcg"`, `tree_method="hist"`, fixed CPU threads, fixed seed, explicit `qid`, and group-level weights. Start with a small frozen search grid over depth, learning rate, estimators, row/column subsampling, and L2 regularization; choose by validation NDCG@3, then regret, then model size.

- [ ] **Step 5: Evaluate against required baselines**

Report NDCG@1/3/5, top-1/top-3 approved recall, regret against the best explicitly reviewed candidate, no-positive-group coverage, abstention, and confidence intervals. Compare against deterministic/Pareto order and a simple linear/logistic baseline. Slice by operation, domain, time, source kind, and truth tier.

- [ ] **Step 6: Freeze the artifact manifest**

Include model/feature/label versions, cutoff, corpus and lineage fingerprints, qid counts, enabled operation coverage, hyperparameters, metrics, slices, source-kind mix, dependency versions, artifact SHA-256, approval status, and creation command.

- [ ] **Step 7: Run tests and commit**

Run: `uv sync --group dev --group ml && PYTHONPATH=services/analysis-worker:services/api .venv/bin/pytest -q tests/test_ranker_training.py tests/test_ranker_evaluation.py`

Commit: `feat(explain): train and evaluate grouped XGBoost counterfactual ranker`

---

### Task 10: Serve the ranker in shadow mode with strict fallback

**Files:**
- Create: `nocpro-chain-explain/services/analysis-worker/review_learning/ranker.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/review_learning_service.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/workspace.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/schemas.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/serializers.py`
- Create: `nocpro-chain-explain/tests/test_ranker_serving.py`
- Modify: `nocpro-chain-explain/tests/test_counterfactual_api.py`

**Interfaces:**
- Produces: `rank_review_group(candidates, artifact, config) -> RankingResult`.
- Consumes only hard-gate-passing candidates and the exact feature schema frozen in the artifact.

- [ ] **Step 1: Write fail-closed serving tests**

Cover missing artifact, unapproved artifact, checksum mismatch, feature-schema mismatch, label-policy mismatch, cutoff violation, missing required feature, out-of-distribution rule, prediction failure, and drift quarantine. Every case must retain deterministic order and return an explicit diagnostic.

- [ ] **Step 2: Implement shadow response**

In `RANKER_SHADOW`, return `shadow_rank`, raw relative score, artifact version, feature fingerprint, and top tree contributions, but leave `displayed_rank == original_rank` and `fallback == true` for ordering.

- [ ] **Step 3: Implement promoted ordering**

Only `approval_status=APPROVED`, exact schema/config/corpus compatibility, in-distribution status, and `RANKER_ACTIVE` may reorder eligible candidates. Hard-gate-rejected candidates remain outside the ranker. Ties break by original deterministic rank and candidate ID.

- [ ] **Step 4: Persist each exposure policy**

Record whether the request used deterministic, shadow, or active ranking and which lower-ranked audit sample was shown. Never rewrite old exposure records when a model is promoted.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=services/analysis-worker:services/api:../nocpro-mock/src .venv/bin/pytest -q tests/test_ranker_serving.py tests/test_counterfactual_api.py`

Commit: `feat(explain): serve counterfactual ranker with deterministic fallback`

---

### Task 11: Expose reviewed memory and model status in the web UI

**Files:**
- Modify: `nocpro-chain-explain/services/web/src/types.ts`
- Modify: `nocpro-chain-explain/services/web/src/api.ts`
- Modify: `nocpro-chain-explain/services/web/src/views/ValidationView.tsx`
- Create: `nocpro-chain-explain/services/web/src/components/SimilarReviewCases.tsx`
- Create: `nocpro-chain-explain/services/web/src/components/ReviewDecisionForm.tsx`
- Create: `nocpro-chain-explain/services/web/src/components/RankingStatus.tsx`
- Create: `nocpro-chain-explain/services/web/src/components/ReviewDecisionForm.test.tsx`
- Create: `nocpro-chain-explain/services/web/src/components/SimilarReviewCases.test.tsx`
- Modify: `nocpro-chain-explain/services/web/e2e/counterfactual-review.spec.ts`

**Interfaces:**
- Produces review controls for any eligible evaluated candidate, none acceptable, defer, insufficient evidence, manual correction, supersession/retraction, and similar-case evidence.
- Consumes v2 API fields from Tasks 4, 6, and 10.

- [ ] **Step 1: Write component tests for semantics**

Assert the UI never labels PO feedback as golden truth, never displays rank score as a probability, distinguishes deterministic/ranker/shadow/fallback order, shows truth tier and outcome separately, and hides mutation apply controls.

- [ ] **Step 2: Implement decision form**

Render canonical decisions, confidence, controlled reason codes, optional explanation, and manual correction editor. Obtain reviewer identity only from the response/session context. Require explicit confirmation before superseding or retracting feedback.

- [ ] **Step 3: Implement similar-case evidence**

Show similarity, common-block coverage, per-block scores, operation pattern, earlier decision, truth tier, outcome state, and review time. Render abstention reason rather than an empty list when retrieval is unavailable.

- [ ] **Step 4: Implement ranking diagnostics**

Show `DETERMINISTIC`, `SHADOW`, `MODEL_RANKED`, or `FALLBACK`, artifact version, and limitations. Keep exact metrics, hard gates, and Pareto status adjacent to model evidence.

- [ ] **Step 5: Run browser tests and commit**

Run: `npm --prefix services/web test -- --run`

Run: `npm --prefix services/web run lint && npm --prefix services/web run build`

Run: `npm --prefix services/web run test:e2e -- counterfactual-review.spec.ts`

Commit: `feat(web): add review memory and ranking evidence`

---

### Task 12: Add model governance, batch promotion, and rollback

**Files:**
- Create: `nocpro-chain-explain/scripts/review_learning/promote_ranker.py`
- Create: `nocpro-chain-explain/scripts/review_learning/activate_ranker.py`
- Create: `nocpro-chain-explain/scripts/review_learning/rollback_ranker.py`
- Create: `nocpro-chain-explain/services/api/nocpro_api/model_registry.py`
- Create: `nocpro-chain-explain/tests/test_ranker_governance.py`
- Create: `nocpro-chain-explain/docs/runbooks/review-learning-model-governance.md`

**Interfaces:**
- Produces an audited transition `DRAFT -> EVALUATED -> APPROVED -> ACTIVE -> RETIRED/QUARANTINED`.
- Consumes immutable artifact manifests and evaluation reports.

- [ ] **Step 1: Test illegal transitions and checksum enforcement**

No artifact may become active directly from draft, without evaluation slices, without all enabled-operation gates, or with a checksum/config/schema mismatch. Quarantine must immediately force deterministic fallback.

- [ ] **Step 2: Implement promotion checks**

Require readiness preconditions, out-of-time/lineage holdout metrics, baseline comparison, operation/domain/source-kind/truth-tier slices, stable artifact checksum, named approver, and activation window. Store reasons for both approval and rejection.

- [ ] **Step 3: Implement one-active-version pointer**

Activation updates a small transactional registry pointer; model bytes remain immutable. Rollback changes the pointer to a previously approved compatible version and emits an audit event.

- [ ] **Step 4: Add monitoring contract**

Record feature availability, fallback rate, OOD rate, score distribution, ranking disagreement with deterministic order, review coverage, decision distribution, and delayed outcome contradictions. Monitoring may quarantine but never auto-promote.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=services/analysis-worker:services/api .venv/bin/pytest -q tests/test_ranker_governance.py`

Commit: `feat(explain): govern ranker promotion activation and rollback`

---

### Task 13: Add only an L1 shadow mutation boundary

**Files:**
- Create: `nocpro-chain-explain/services/api/nocpro_api/mutation/contracts.py`
- Create: `nocpro-chain-explain/services/api/nocpro_api/mutation/port.py`
- Create: `nocpro-chain-explain/services/api/nocpro_api/mutation/mock_adapter.py`
- Create: `nocpro-chain-explain/services/api/nocpro_api/mutation/policy.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/schemas.py`
- Modify: `nocpro-chain-explain/services/api/nocpro_api/routes.py`
- Create: `nocpro-chain-explain/tests/test_mutation_shadow.py`
- Create: `nocpro-chain-explain/docs/contracts/nocpro-mutation-required-contract.md`

**Interfaces:**
- Produces: `MutationPort.validate(request) -> DryRunResult`; no production `apply` implementation.
- Consumes a frozen approved candidate, expected snapshot version, server principal, and explicit L1 configuration.

- [ ] **Step 1: Write negative safety tests**

Prove models cannot invoke the port, browser-supplied deltas are ignored, synthetic/replay data cannot produce a production request, stale versions fail, unapproved/hard-gate-rejected candidates fail, disabled mode returns `MUTATION_UNAVAILABLE`, and no network call occurs.

- [ ] **Step 2: Define immutable request and state contracts**

Include mutation request ID, idempotency key, operation, expected snapshot/version/partition fingerprint, candidate/fingerprint, smallest exact delta, approval IDs, expiry, correlation ID, and source kind. Define the full state enum from `PROPOSED` through verification/outcome plus stale/conflict/unknown/partial/manual-intervention states, but permit only `PROPOSED -> SHADOW_VALIDATED` in this task.

- [ ] **Step 3: Implement mock dry-run adapter**

The adapter validates the delta against an in-memory authoritative partition and simulates stale, duplicate, timeout, partial, and mismatch responses. It must never connect to a configurable external URL.

- [ ] **Step 4: Document the upstream blocking contract**

The required contract document must list stable IDs, compare-and-set version, idempotency retention, dry-run semantics, atomicity/partial success, ACK/error taxonomy, status reconciliation, authoritative after-snapshot, auth/TLS, maintenance windows, rate/impact limits, and sandbox endpoints. G7 remains blocked until each item has evidence.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=services/analysis-worker:services/api .venv/bin/pytest -q tests/test_mutation_shadow.py tests/test_operator_feedback_api.py`

Commit: `feat(explain): add fail-closed shadow mutation port`

---

### Task 14: Migrate legacy feedback explicitly and verify the complete review-only flow

**Files:**
- Create: `nocpro-chain-explain/scripts/review_learning/migrate_legacy_feedback.py`
- Create: `nocpro-chain-explain/tests/test_legacy_feedback_migration.py`
- Create: `nocpro-chain-explain/tests/e2e/test_review_learning_flow.py`
- Modify: `nocpro-chain-explain/tests/e2e/run_acceptance.sh`
- Modify: `nocpro-chain-explain/docs/CURRENT_STATUS.md`
- Modify: `nocpro-chain-explain/README.md`

**Interfaces:**
- Produces an auditable legacy migration report and an end-to-end G1-G6 evidence bundle.
- Consumes all prior tasks.

- [ ] **Step 1: Implement dry-run-first legacy migration**

Map `APPROVED/ACCEPTED -> APPROVE` and `REJECTED -> REJECT`, assign `PO_ASSERTED`, mark identity source as `LEGACY_CLIENT_ASSERTED`, preserve original row fingerprints, and quarantine rows whose candidate cannot be matched to an immutable historical exposure. Require `--apply` for writes and make reruns idempotent.

- [ ] **Step 2: Write a complete review-only E2E test**

Exercise canonical snapshot ingest, deterministic candidate generation, atomic exposure persistence, review of a non-top candidate, PO-asserted feedback, case creation, historical retrieval, KDE available/unavailable branches, ranker shadow scoring, API restart/read-back, and proof that no mutation was dispatched.

- [ ] **Step 3: Add ranker-active acceptance using synthetic reviewed groups only**

Train/freeze/promote a tiny synthetic artifact, verify eligible candidate reordering and exact deterministic fallback on artifact mismatch. Label the evidence `SYNTHETIC_CORRECTNESS_ONLY`, never production calibration.

- [ ] **Step 4: Add L1 shadow mutation acceptance**

Validate a frozen request against the mock adapter and prove no external side effect. Exercise stale, duplicate, timeout-unknown, partial, and after-state mismatch simulations.

- [ ] **Step 5: Run the complete verification matrix**

Run backend unit suite:

```bash
PYTHONPATH=services/analysis-worker:services/api:../nocpro-mock/src .venv/bin/pytest -q
```

Run PostgreSQL and Docker acceptance:

```bash
PYTHONPATH=services/analysis-worker:services/api:../nocpro-mock/src .venv/bin/pytest -q -m postgres
bash tests/e2e/run_acceptance.sh
```

Run frontend verification:

```bash
npm --prefix services/web test -- --run
npm --prefix services/web run lint
npm --prefix services/web run build
npm --prefix services/web run test:e2e -- counterfactual-review.spec.ts
```

Expected: every suite passes; review feedback survives restart; no test or runtime path dispatches a real mutation; all availability/fallback states are visible.

- [ ] **Step 6: Update status documentation with evidence tiers**

Report deterministic implementation, synthetic correctness, review-memory availability, KDE corpus readiness, ranker shadow/active status, production calibration, and mutation capability independently. Do not call G7 ready without upstream sandbox evidence.

- [ ] **Step 7: Commit**

Commit: `test(explain): verify closed review learning loop and shadow mutation`

---

## Final definition of done

The implementation represented by this plan is complete at G6 only when:

1. every evaluated candidate exposure is immutable and queryable;
2. any eligible candidate, none acceptable, defer, insufficient evidence, manual correction, supersession, and retraction are supported;
3. reviewer identity is server-derived and feedback starts as `PO_ASSERTED`;
4. similar reviewed cases obey cutoff, lineage, compatibility, and block-coverage rules;
5. Temporal Delay Model V2 is reused with exact model/taxonomy/cutoff fingerprints and typed abstention;
6. XGBoost training keeps qids and lineages intact, compares against deterministic order, and produces reproducible immutable artifacts;
7. shadow scoring cannot alter ordering, and active ranking requires explicit artifact promotion;
8. any model/config/artifact mismatch falls back to deterministic/Pareto order;
9. UI separates deterministic facts, model evidence, human judgment, application, and outcome;
10. default mutation status is `MUTATION_UNAVAILABLE`, and L1 only validates against the internal mock adapter;
11. PostgreSQL restart tests, full backend tests, frontend tests/build, and browser E2E pass;
12. production ranking remains uncalibrated until real independent review groups pass the documented temporal/lineage gates;
13. production mutation remains blocked pending a separate approved upstream contract and sandbox integration plan.

## Explicitly deferred beyond this plan

- Siamese/DeepSets representation learning, until the deterministic retrieval and XGBoost baselines show a measured recall ceiling on a sufficiently large independent review corpus.
- Unattended automatic mutation.
- A real NocPro mutation adapter, transactional outbox, ACK reconciler, authoritative after-state verifier, outcome observer, and compensation executor. Those require the upstream contract listed in Task 13 and a separate design approval before implementation.
