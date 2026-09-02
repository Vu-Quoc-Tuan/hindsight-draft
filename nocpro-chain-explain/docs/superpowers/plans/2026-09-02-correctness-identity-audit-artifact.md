# Correctness, Identity, and Audit Artifact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce strict Role conjunctions, make `(snapshot_id, snapshot_version)` canonical across lineage/similarity, and persist immutable exact Audit artifacts for restart-safe Counterfactual SPLIT.

**Architecture:** Keep the three changes isolated. Role remains a pure classifier change; lineage/similarity extend existing keys and PostgreSQL schema; Audit persistence introduces a compact review-facing artifact and asynchronous state listener without storing dense pair evidence.

**Tech Stack:** Python 3.12 dataclasses, SQLAlchemy 2 async ORM, Alembic/PostgreSQL, FastAPI workspace services, pytest.

## Global Constraints

- Missing Role metrics never satisfy positive or negative conditions.
- Canonical snapshot identity is `(snapshot_id, snapshot_version)` everywhere.
- Existing ambiguous legacy lineage rows make migration fail instead of guessing.
- Review consumes persisted exact Audit artifacts and never starts Audit implicitly.
- Persist no dense pair graph or full pair evidence table.
- Do not add production thresholds or enable data-gated capabilities.

---

### Task 1: Strict Role conjunctions

**Files:**
- Modify: `services/analysis-worker/groups/roles.py`
- Test: `tests/test_fit_and_roles.py`

**Interfaces:**
- Consumes: `classify_membership(..., representativeness: float | None, margin_common: float | None)`
- Produces: frozen CORE/WEAK/PERIPHERAL/INSUFFICIENT_DATA behavior.

- [ ] Add the six-case regression matrix covering null representativeness, null margin, proven CORE, proven WEAK, and failed availability gate.
- [ ] Run `tests/test_fit_and_roles.py` and confirm the three null cases fail under the old `is None or` behavior.
- [ ] Replace the CORE conditions with explicit non-null checks and replace the WEAK condition with `margin_common is not None and margin_common <= 0`.
- [ ] Re-run the focused test and confirm it passes.
- [ ] Commit only Role code and tests.

### Task 2: Version-aware lineage and Similar Chains domain keys

**Files:**
- Modify: `services/analysis-worker/evolution/global_lineage.py`
- Modify: `services/analysis-worker/evolution/lifecycle.py`
- Modify: `services/analysis-worker/evolution/pipeline.py`
- Modify: `services/analysis-worker/similar_chains/temporal.py`
- Modify: `services/api/nocpro_api/tier1a_coordinator.py`
- Modify: `services/api/nocpro_api/persistence/models.py`
- Modify: `services/api/nocpro_api/persistence/repository.py`
- Test: `tests/test_evolution.py`
- Test: `tests/test_similar_chains.py`
- Test: `tests/test_tier1a_coordinator.py`
- Test: `tests/test_postgres_snapshot_ingest.py`

**Interfaces:**
- Produces: `LineageNodeKey(snapshot_id, snapshot_version, snapshot_chain_id)`.
- Produces: `TimedChainFingerprint(..., snapshot_id, snapshot_version)`.
- Produces: `load_similarity_index(snapshot_id, snapshot_version)` and `canonical_lineages(snapshot_id, snapshot_version)`.

- [ ] Add tests proving `(S1,v1,C1) != (S1,v2,C1)` and deterministic component hashes differ.
- [ ] Extend all domain constructors, serializers, repository mappings, and coordinator calls with version.
- [ ] Add repository tests that store and retrieve two versions of the same snapshot ID independently.
- [ ] Run evolution/similarity/coordinator tests and fix only version propagation failures.
- [ ] Commit domain and repository code separately from the migration.

### Task 3: PostgreSQL snapshot-version migration

**Files:**
- Create: `migrations/versions/0005_lineage_similarity_snapshot_version.py`
- Modify: `services/api/nocpro_api/persistence/models.py`
- Test: `tests/test_postgres_snapshot_ingest.py`

**Interfaces:**
- Extends lineage node/edge, similarity fingerprint/model/index keys with snapshot version.
- Preserves unambiguous existing rows by joining `snapshots` on snapshot ID.

- [ ] Write a migration test for a clean database and two versions of one snapshot ID.
- [ ] Add nullable version columns, reject legacy IDs that map to multiple persisted versions, backfill unambiguous rows, rebuild primary/foreign/unique constraints, then set columns non-null.
- [ ] Update downgrade to remove version-aware constraints and columns only when legacy uniqueness can be restored.
- [ ] Run PostgreSQL integration when `TEST_DATABASE_URL` is available; otherwise report it as skipped rather than claiming migration runtime proof.
- [ ] Commit migration and ORM alignment.

### Task 4: Compact immutable Audit artifact model

**Files:**
- Create: `services/analysis-worker/tier2/audit_artifact.py`
- Modify: `services/analysis-worker/tier2/__init__.py`
- Test: `tests/test_audit_artifact.py`

**Interfaces:**
- Produces: `ReviewAuditArtifact` with exact mode, `StructuralAuditResult`, snapshot/config/membership identities, artifact ID/version/fingerprint, and creation time.
- Produces: deterministic `audit_artifact_fingerprint(payload)` and JSON round-trip helpers.

- [ ] Add round-trip tests for exact scored candidates and deterministic fingerprinting.
- [ ] Implement serialization for candidate source/members/label, conductance, verdict, reason, and exact artifact metadata without graph edges.
- [ ] Reject non-exact artifacts and fingerprint mismatches during deserialization.
- [ ] Run focused artifact tests and commit.

### Task 5: Persist Audit artifacts and expose strict compatible lookup

**Files:**
- Create: `migrations/versions/0006_audit_artifact.py`
- Modify: `services/api/nocpro_api/persistence/models.py`
- Modify: `services/api/nocpro_api/persistence/repository.py`
- Test: `tests/test_postgres_snapshot_ingest.py`

**Interfaces:**
- Produces: `persist_audit_artifact(payload)` as insert-only storage.
- Produces: `latest_compatible_audit_artifact(snapshot_id, snapshot_version, chain_id, chain_fingerprint, analysis_config_version)`.

- [ ] Add schema/repository tests for immutable multiple runs, exact compatible lookup, and stale chain/config rejection.
- [ ] Create an insert-only `audit_artifact` table keyed by artifact ID with indexed compatibility columns and JSONB payload.
- [ ] Implement strict fingerprint verification before returning a deserialized artifact.
- [ ] Run PostgreSQL tests when configured and commit.

### Task 6: Persist successful Deep Dive artifacts and reuse them in Review

**Files:**
- Modify: `services/analysis-worker/tier2/jobs.py`
- Modify: `services/api/nocpro_api/workspace.py`
- Modify: `services/api/nocpro_api/routes.py`
- Test: `tests/test_tier2_jobs.py`
- Test: `tests/test_counterfactual_api.py`
- Test: `tests/test_postgres_counterfactual_jobs.py`

**Interfaces:**
- Tier-2 job manager emits an immutable successful-result listener event.
- Workspace persists exact artifacts through the async repository loop.
- Review context loads the latest compatible persisted artifact only when no compatible in-memory artifact exists.

- [ ] Add tests showing successful exact Audit emits one persistence event while unavailable/failed Audit emits none.
- [ ] Add restart tests: persisted exact artifact enables SPLIT; missing/stale artifact leaves REMOVE independent and SPLIT unavailable.
- [ ] Add a Tier-2 state listener following the existing Counterfactual listener pattern and flush it before API responses that require durable state.
- [ ] Build compact artifacts from successful exact Deep Dive results and insert them asynchronously.
- [ ] Make `_review_context` async so it can load strict compatible persisted Audit artifacts without running Audit.
- [ ] Run API/Counterfactual/PostgreSQL tests and commit.

### Task 7: Full verification

**Files:**
- Verify all modified files and documentation.

- [ ] Run `.venv/bin/python -m pytest tests -p no:cacheprovider`.
- [ ] Run Mock tests and React tests/lint/build to detect contract projection regressions.
- [ ] Run `git diff --check` and inspect the final diff for accidental production config changes.
- [ ] If Docker/PostgreSQL prerequisites are present, run the isolated restart acceptance; otherwise list the exact skipped proof level.
- [ ] Record final commits and remaining external data gates without changing their status.

