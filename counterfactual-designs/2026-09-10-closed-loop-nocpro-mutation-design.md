# Closed-loop Counterfactual Review and NocPro Mutation

**Date:** 2026-09-10
**Status:** Proposed design; not implemented
**Operating mode:** Human-approved recommendation, controlled mutation, and outcome verification
**Repository scope:** `nocpro-mock`, `nocpro-chain-explain`, and a future authoritative NocPro mutation adapter
**Default safety level:** No unattended automatic application

## 1. Executive decision

This design uses the same three learning components as the review-only design:

1. histogram/KDE temporal-delay evidence;
2. deterministic similar reviewed-case retrieval; and
3. an XGBoost learning-to-rank model over candidates that already pass exact
   deterministic hard gates.

It then adds a separate, policy-controlled mutation plane. A recommendation is
never applied merely because its model score is high or a similar PO-approved
case exists. An authenticated human approves a frozen candidate against an
authoritative snapshot version. The system dispatches an idempotent mutation,
waits for an authoritative post-change snapshot, verifies the actual partition
against the intended delta, and records the outcome.

PO experience is stored immediately as `PO_ASSERTED` ground truth. A successful
API acknowledgment upgrades only the action state, not the truth of the
benefit. `OUTCOME_VERIFIED` is assigned only after the post-change observation
and stability policy pass.

## 2. Relationship to the review-only direction

This file is independently implementable, but the first part intentionally
keeps the review-only guarantees:

- deterministic candidate generation remains authoritative for validity;
- KDE supplies temporal typicality, not causality;
- XGBoost ranks rather than generates candidates;
- similar cases are reviewer evidence, not commands;
- unreviewed candidates are not negatives;
- all training/retrieval obey exclusive time and lineage cutoffs;
- LLM output can narrate existing facts but cannot authorize or dispatch.

The additional mutation plane begins only after a candidate has been frozen,
reviewed, and approved under policy.

## 3. Goals

- Support controlled `REMOVE`, `MOVE`, `SPLIT`, and `MERGE` changes in the
  authoritative upstream partition.
- Prevent stale, duplicated, partially applied, or unverifiable changes.
- Make every approval, dispatch attempt, response, post-state, verification,
  failure, and compensation auditable.
- Feed human decisions and verified outcomes back into later similar-case
  retrieval and batch model training.
- Preserve a safe review-only fallback whenever mutation capability is absent
  or unhealthy.
- Separate recommendation quality, transport success, state application, and
  operational benefit as distinct facts.

## 4. Non-goals

- No fully autonomous model-triggered changes in the initial system.
- No bypass of deterministic invariants, hard gates, authorization, or
  concurrency checks.
- No claim of exactly-once delivery. Transport is at least once; upstream
  effects must be idempotent.
- No assumption that an inverse edit is always a true rollback.
- No mutation through an LLM, browser automation, direct database edits, or an
  undocumented private endpoint.
- No upgrading `PO_ASSERTED` directly to `OUTCOME_VERIFIED` based on approval or
  HTTP 2xx alone.

## 5. Current repository state and blocking gaps

The repository currently provides canonical snapshot contracts, provenance,
deterministic counterfactual review, hard gates, Pareto results, asynchronous
jobs, web UI, and basic feedback persistence. The current review flow is
proposal-only and tracks that mutation was not dispatched.

The following upstream capabilities are not yet established and block real
closed-loop operation:

- documented NocPro mutation API for each operation;
- stable authoritative chain/member identifiers;
- partition or snapshot version used for optimistic concurrency;
- server-side idempotency-key behavior and retention window;
- dry-run/validation endpoint and validation semantics;
- authorization roles, service identity, credential rotation, and audit actor;
- acknowledgment/event contract and error taxonomy;
- authoritative post-mutation snapshot/event stream;
- atomicity and partial-success semantics for multi-member operations;
- native undo/version-history support, if any;
- maintenance/change-window rules, rate limits, maximum impact, and SLA;
- test/staging environment whose data cannot be confused with production.

Until these exist and pass integration tests, the application must operate as
review-only and return `MUTATION_UNAVAILABLE`.

## 6. Required input contracts

### 6.1 Analysis package

The recommendation input is the canonical versioned snapshot package:

```json
{
  "schema_version": "1.0",
  "snapshot": {
    "snapshot_id": "snap-20260910-0900",
    "snapshot_version": "42",
    "event_time": "2026-09-10T02:00:00Z",
    "source": "nocpro-live",
    "source_kind": "REAL_LIVE",
    "quality_status": "PASS"
  },
  "alarms": [],
  "chains": [],
  "memberships": [],
  "system_metadata": {
    "taxonomy_version": "taxonomy-7",
    "chaining_config_version": "nocpro-config-31"
  },
  "topology": {
    "relation_type": "PHYSICAL_ADJACENCY",
    "mapping_version": "map-12"
  },
  "operational_context": {},
  "provenance_manifest": {
    "input_fingerprint": "sha256:..."
  }
}
```

Only `REAL_LIVE` data from an authoritative mutable environment is eligible for
dispatch. `REAL_EXPORT_REPLAY` can validate analysis and simulate mutation;
`SYNTHETIC_TEST` can test behavior; neither can authorize a production change.

### 6.2 Frozen candidate

```json
{
  "candidate_id": "cand-4",
  "candidate_fingerprint": "sha256:...",
  "generator_version": "cf-generator-v5",
  "operation": "MOVE",
  "expected_before": {
    "snapshot_id": "snap-20260910-0900",
    "snapshot_version": "42",
    "partition_fingerprint": "sha256:before"
  },
  "delta": {
    "remove": [{"chain_id": "chain-A", "alarm_id": "a-101"}],
    "add": [{"chain_id": "chain-B", "alarm_id": "a-101"}]
  },
  "hard_gate": "PASS",
  "pareto_eligible": true,
  "before_metrics": {},
  "after_metrics": {},
  "metric_deltas": {},
  "model_context": {
    "ranker_version": "cf-ranker-2026-11-15",
    "delay_model_version": "delay-2026-10-01",
    "review_case_retrieval_version": "review-case-sim-v1"
  }
}
```

The server reconstructs or verifies the candidate from immutable artifacts; it
does not trust client-submitted members or metric deltas.

### 6.3 Approval

```json
{
  "approval_id": "approval-322",
  "candidate_id": "cand-4",
  "candidate_fingerprint": "sha256:...",
  "expected_snapshot_version": "42",
  "decision": "APPROVE_FOR_APPLY",
  "confidence": 0.85,
  "reason_codes": ["KNOWN_MAINTENANCE_PATTERN"],
  "comment": "Move access alarm to active maintenance chain",
  "requested_window": {
    "not_before": "2026-09-10T02:15:00Z",
    "expires_at": "2026-09-10T02:30:00Z"
  }
}
```

Reviewer identity, role, domain, separation-of-duty eligibility, and permission
are derived from authentication and policy, not request fields.

## 7. Current data inventory and remaining model data

### 7.1 Audited repository data snapshot

These values describe the repository data inspected for this design. Training
must regenerate them as a versioned profile tied to exact source-file
fingerprints.

| Alarm export | Rows | Chain IDs | Singleton chains | Largest chain | Main limitation |
|---|---:|---:|---:|---:|---|
| `alarm_data.csv` | 8,714 | 2,824 | 2,072 (73.37%) | 1,072 | Future timestamps and end-before-start anomalies |
| `alarmIP.csv` | 212,636 | 87,206 | 64.84% | 1,018 | No dependable reviewed/root label |
| `alarmIT.csv` | 258,344 | 82,453 | 78.03% | 59,176 | `is_root_alarm` meaning/provenance unverified; `label_alarm` nearly empty |

Topology observations:

| Topology export | Size | Alarm mapping | What is not proved |
|---|---:|---:|---|
| IP | 201,977 device-port adjacency edges | 140,596/212,636 exact (66.121%) | Dependency direction, active path, failure domain |
| IT | 128,322 nodes; 218,635 edges | 169,836/258,344 uniquely resolved (65.74%) | Dependency direction and ambiguous/unmapped semantics |

`alarm_data.csv` has `node_reference` on approximately 98.06% of rows, but
presence is not correctness. `alarmIT.csv` contains non-empty
`is_root_alarm` values 0, 1, and 2; they are not labels until producer,
semantics, and validity are documented. Large row counts do not become large
effective training counts because snapshots, chains, episodes, and lineages
are correlated.

### 7.2 What the current data supports

- deterministic review and synthetic/replay mutation testing;
- schema, feature, KDE, similar-case, and XGBoost pipeline development;
- provisional KDE experiments only after timestamp/taxonomy/episode gates;
- collection of new PO review cases.

It does not yet support a production claim for the ranker or real mutation.

### 7.3 Missing model and governance data

Closed-loop operation does not remove the data requirements of review-only
learning. A full repository still needs:

- time-valid authoritative alarm TYPE/FAMILY/CATEGORY mappings;
- multiple verified sequential snapshots, episodes, and lineage;
- complete candidate exposure, including lower-ranked and unshown candidates;
- review of any evaluated candidate, `NONE_ACCEPTABLE`, manual correction,
  confidence, reason, domain, role, supersession, and retraction;
- versioned KDE and XGBoost artifacts with training cutoffs and corpus
  fingerprints;
- explicit topology semantics and mapping coverage;
- authoritative post-action snapshots and stability/outcome observations.

The current alarm/topology exports support development but contain high
singleton rates, unusual large chains, incomplete topology mappings, and
unverified label/direction semantics. They cannot by themselves establish a
safe production mutation policy.

### 7.4 Required historical and taxonomy formats

```text
taxonomy_id, taxonomy_version, alarm_code, type, family, category,
valid_from, valid_to, source_system, source_record_id, mapping_status

snapshot_id, snapshot_version, captured_at, ingest_at, source_kind,
incident_id, episode_id, lineage_component_id, predecessor_snapshot_id,
quality_status, completeness_window
```

### 7.5 Candidate exposure and PO feedback formats

Every evaluated candidate must be persisted whether it was shown or reviewed:

```json
{
  "review_id": "review-991",
  "candidate_id": "cand-4",
  "original_rank": 4,
  "displayed_rank": 1,
  "shown_to_reviewer": true,
  "deterministic_eligibility": "HARD_GATES_PASSED",
  "exposure_policy": "TOP_K_PLUS_AUDIT_SAMPLE",
  "generator_version": "cf-generator-v5",
  "ranker_version": "cf-ranker-2026-11-15",
  "feature_fingerprint": "sha256:..."
}
```

The reviewer record is append-only:

```json
{
  "feedback_id": "fb-1207",
  "review_id": "review-991",
  "candidate_id": "cand-4",
  "reviewer_id": "user-17",
  "reviewer_role": "PRODUCT_OWNER",
  "domain_scope": ["IP_CORE"],
  "decision": "APPROVE",
  "confidence": 0.85,
  "reason_codes": ["KNOWN_MAINTENANCE_PATTERN"],
  "reason_text": "Move access alarm to maintenance chain",
  "truth_tier": "PO_ASSERTED",
  "created_at": "2026-09-10T02:08:00Z",
  "status": "ACTIVE",
  "supersedes_feedback_id": null,
  "candidate_set_fingerprint": "sha256:...",
  "feature_fingerprint": "sha256:..."
}
```

The contract also supports `REJECT`, `DEFER`, `INSUFFICIENT_EVIDENCE`, a
group-level `NONE_ACCEPTABLE`, manual corrected operation/partition, and later
retraction or supersession. Reviewer authority is server-derived.

## 8. Learning architecture

### 8.1 KDE temporal-delay model

The KDE layer builds positive directed delay observations per taxonomy relation
from eligible episodes strictly before a cutoff. It deduplicates and balances
by episode, uses grouped time/episode validation, records source-kind and
lineage fingerprints, and falls back from TYPE to FAMILY only under a frozen
policy. Missing taxonomy, invalid times, insufficient episodes, or artifact
mismatch produce typed unavailability.

Its candidate features include delay-model coverage, local mass/typicality
summaries, atypical ratio, fallback ratio, and model identity. These features
cannot prove a root cause or authorize an edit.

Illustrative KDE result:

```json
{
  "status": "AVAILABLE",
  "relation_key": ["FAMILY", "POWER", "CONNECTIVITY"],
  "delay_seconds": 47.0,
  "density": 0.013,
  "local_mass": 0.72,
  "independent_episode_count": 184,
  "fallback_level": null,
  "model_kind": "GAUSSIAN_KDE",
  "model_version": "delay-2026-10-01",
  "training_cutoff": "2026-10-01T00:00:00Z",
  "corpus_fingerprint": "sha256:..."
}
```

### 8.2 Similar reviewed cases

Every review freezes chain context, evidence shape, KDE summaries, eligible
topology summaries, abstract operation pattern, candidate set/exposure, human
decision, reason, truth tier, and later outcome.

Similarity is a deterministic multi-block score:

```text
S = sum(w_b * S_b for common eligible blocks b) / sum(w_b)
```

Blocks cover chain context, evidence shape, temporal shape, topology shape, and
abstract operation pattern. Weights are renormalized over common available
blocks. Raw chain/alarm/device IDs are excluded from similarity. Retrieval is
strictly historical and normally excludes the same lineage.

Each result exposes the case ID, block scores, common-block coverage, reviewer
decision, truth tier, outcome state, and timestamp. Low common coverage causes
abstention. A single previous PO approval is never a direct apply rule.

### 8.3 XGBoost ranker

Each training row is one deterministic candidate; all candidates from a review
share one `qid` and remain together across splits. The ranker receives exact
before/after/delta metrics, operation pattern, edit cost, structural facts,
quality/availability, KDE aggregates, similar-case aggregates, and eligible
topology summaries. It does not receive raw identity keys.

Labels come only from explicit active judgments or verified outcomes:

- verified approved outcome: relevance 3;
- consensus/applied approved action: relevance 2;
- asserted approval: frozen lower-weight positive;
- explicit rejection or contradicted outcome: relevance 0;
- defer, insufficient evidence, unreviewed: excluded;
- none acceptable: group-level no-safe-choice record.

The ranker reorders hard-gate-passing candidates only. Deterministic/Pareto
order is the fallback for missing, mismatched, drifting, or unapproved models.

Illustrative ranker result:

```json
{
  "candidate_id": "cand-4",
  "deterministic_status": "HARD_GATES_PASSED",
  "rank": 1,
  "rank_score": 1.734,
  "score_semantics": "RELATIVE_WITHIN_REVIEW_GROUP",
  "model_version": "cf-ranker-2026-11-15",
  "feature_fingerprint": "sha256:...",
  "availability": "AVAILABLE",
  "similar_cases": ["case-71", "case-44"]
}
```

The rank score is not a calibrated probability of correctness. Model artifacts
also freeze feature schema, label policy, group count, operation/source-kind
coverage, training cutoff, corpus fingerprint, evaluation, and approval.

## 9. Ground-truth and outcome semantics

| Truth tier | What it proves | What it does not prove |
|---|---|---|
| `PO_ASSERTED` | An authorized PO judged the edit appropriate | Application or benefit |
| `EXPERT_CONSENSUS` | Required reviewers agreed | Application or benefit |
| `APPLIED_CONFIRMED` | Authoritative state matches intended delta | Long-term operational benefit |
| `OUTCOME_VERIFIED` | Defined observation window passed success criteria | Universal causal law |
| `OUTCOME_CONTRADICTED` | Defined observation conflicts with expected benefit | That every similar case is wrong |

Feedback and outcomes are append-only and can be retracted or superseded.
Verified outcomes enter retrieval/training only in a later frozen batch whose
cutoff is after verification. The serving model never learns immediately from
its own latest action.

## 10. Authorization and approval policy

### 10.1 Roles

- `VIEWER`: inspect proposals and evidence.
- `REVIEWER`: accept/reject as feedback, without apply authority.
- `PRODUCT_OWNER`: approve within declared domain and impact limit.
- `CHANGE_APPROVER`: second approval for policy-sensitive edits.
- `MUTATION_SERVICE`: dispatch only an already authorized immutable request.
- `VERIFIER`: confirm authoritative after-state/outcome; may be automated where
  policy allows but must be attributable.

### 10.2 Policy examples

- `REMOVE`/small `MOVE`: one PO approval when impact is below configured limit.
- `SPLIT`/`MERGE`, cross-domain move, or large affected region: two distinct
  authorized approvers.
- Reviewer cannot approve outside their domain scope.
- Candidate creator/reviewer and second approver separation may be required.
- Approval expires and is invalidated by any upstream version change.
- Model rank never reduces the required approval count.

The exact matrix is configuration and governance data, not hard-coded model
logic.

## 11. Mutation request contract

```json
{
  "mutation_request_id": "mut-778",
  "idempotency_key": "cf:cand-4:before-42",
  "operation": "MOVE",
  "expected_snapshot_id": "snap-20260910-0900",
  "expected_snapshot_version": "42",
  "expected_partition_fingerprint": "sha256:before",
  "candidate_id": "cand-4",
  "candidate_fingerprint": "sha256:...",
  "delta": {
    "remove": [{"chain_id": "chain-A", "alarm_id": "a-101"}],
    "add": [{"chain_id": "chain-B", "alarm_id": "a-101"}]
  },
  "approval_ids": ["approval-322"],
  "expires_at": "2026-09-10T02:30:00Z",
  "correlation_id": "review-991",
  "requested_by_service": "nocpro-chain-explain"
}
```

The adapter must send the smallest authoritative delta supported by NocPro and
must not infer extra changes. Secrets never enter the request artifact or log.

## 12. Preconditions before dispatch

Every condition must pass immediately before enqueue and again before dispatch:

- candidate and analysis artifact fingerprints match;
- all deterministic hard gates still pass under frozen inputs;
- approval count, roles, domains, and separation-of-duty policy pass;
- approval is active, not expired, retracted, or superseded;
- upstream authoritative snapshot/partition version equals the expected value;
- affected chains/members still exist and memberships equal the before-state;
- operation is supported by the currently healthy adapter version;
- dry-run/validation passes, if supported;
- change window, rate, edit-cost, and impact limits pass;
- idempotency key is unique for the intended effect;
- no conflicting in-flight mutation touches the affected region;
- post-state observation and verification channels are healthy.

Failure is fail-closed. A stale or unobservable mutation remains a review
artifact; it is not dispatched.

## 13. State machine

```text
PROPOSED
  -> APPROVAL_PENDING
  -> APPROVED
  -> QUEUED
  -> DISPATCHING
  -> ACKNOWLEDGED
  -> VERIFYING
  -> APPLIED_CONFIRMED
  -> OUTCOME_OBSERVING
  -> OUTCOME_VERIFIED | OUTCOME_CONTRADICTED
```

Terminal or intervention states:

- `REJECTED`: human/policy rejected.
- `EXPIRED`: approval window ended before dispatch.
- `STALE`: upstream version changed.
- `CONFLICT`: overlapping change or concurrency token failed.
- `DISPATCH_FAILED`: upstream rejected before an accepted effect.
- `TIMED_OUT_UNKNOWN`: no conclusive response; reconcile before retry.
- `PARTIAL`: some requested effects appear applied.
- `VERIFY_FAILED`: ACK exists but authoritative after-state does not match.
- `COMPENSATION_REQUIRED`: safe automated completion/undo is unavailable.
- `COMPENSATING`: approved compensation in progress.
- `COMPENSATED`: authoritative state matches the compensation target.
- `MANUAL_INTERVENTION`: automated progress is unsafe.

State transitions are append-only events with actor, timestamp, cause, request
and response fingerprints. No API caller can directly set an arbitrary state.

## 14. Reliable dispatch

### 14.1 Transactional outbox

In one database transaction:

1. validate current approval and expected version;
2. create immutable mutation request;
3. append `QUEUED` transition;
4. create an outbox event.

A dispatcher claims the outbox record, revalidates preconditions, and calls the
NocPro adapter. Retries reuse the same idempotency key. Transport can be at
least once; the upstream or adapter must make the effect idempotent.

### 14.2 Unknown result handling

Network timeout after sending does not mean failure and must not trigger a new
idempotency key. The reconciler queries mutation status and authoritative
partition state. Until reconciled, the state is `TIMED_OUT_UNKNOWN` and
overlapping mutations are blocked.

### 14.3 Concurrency

Optimistic concurrency uses the authoritative version/fingerprint. Per-region
advisory locking may reduce races, but it does not replace upstream compare-and-
set. If NocPro cannot reject stale writes, production mutation remains blocked.

## 15. Verification: ACK is not success

After acknowledgment, the verifier consumes or fetches a new authoritative
snapshot and compares actual state with the frozen intent:

```text
actual_removed == intended_removed
actual_added   == intended_added
unintended_changes_in_affected_region == empty
after_snapshot_version > before_snapshot_version
```

The verification artifact contains:

```json
{
  "verification_id": "verify-881",
  "mutation_request_id": "mut-778",
  "before_snapshot_version": "42",
  "after_snapshot_version": "43",
  "intended_delta_fingerprint": "sha256:intended",
  "actual_delta_fingerprint": "sha256:actual",
  "partition_match": true,
  "unintended_changes": [],
  "verified_at": "2026-09-10T02:17:23Z",
  "evidence_fingerprint": "sha256:..."
}
```

Only a matching authoritative after-state yields `APPLIED_CONFIRMED`.

## 16. Outcome observation

Application success and operational success are measured separately. A
versioned policy defines per-domain signals and observation windows, for
example:

- chain stability and absence of rapid undo/reassignment;
- recurrence of the same incident pattern;
- alert volume/churn in the affected region;
- operator escalation or correction;
- SLA/acknowledgment/triage measures where available;
- absence of defined safety regressions.

Outcome evaluation must account for censoring and concurrent changes. If the
window lacks enough observable evidence, it remains `OUTCOME_UNKNOWN`; it is
not labeled successful.

## 17. Rollback and compensation

A true rollback requires authoritative upstream version history or an explicit
undo token with documented guarantees. Without that, an inverse mutation is
only compensation because the environment may have changed.

Rules:

- never auto-compensate a partial/unknown result before reconciliation;
- build compensation against the latest authoritative snapshot;
- run the same deterministic gates, policy, concurrency, approval, dispatch,
  and verification flow;
- store links from compensation to original mutation;
- require human approval unless a narrowly documented emergency policy says
  otherwise;
- if a safe inverse cannot be constructed, enter `MANUAL_INTERVENTION`.

## 18. Similar cases after human review and mutation

When the PO approves, rejects, changes destination, requests a split/merge, or
submits a manual partition, the Review Case Store captures the decision as
`PO_ASSERTED`. Retrieval for a later case can then say:

```text
Case 71 similarity 0.89
- same abstract operation: move weak non-connector to higher-fit local chain
- evidence-shape similarity: 0.88
- temporal-shape similarity: 0.84
- PO approved, no verified outcome yet
```

After authoritative application, the case gains `APPLIED_CONFIRMED`. After the
observation window, it may gain `OUTCOME_VERIFIED` or
`OUTCOME_CONTRADICTED`. Retrieval always displays that distinction. XGBoost
receives aggregates by truth tier, not a single “past approval = apply” bit.

## 19. Full closed-loop flow

```text
Authoritative snapshot + provenance
  -> deterministic evidence and counterfactual candidates
  -> exact metrics + hard gates + Pareto
  -> KDE features + historical reviewed-case retrieval
  -> approved XGBoost ranker or deterministic fallback
  -> human review of any candidate / none / manual correction
  -> append PO_ASSERTED feedback and immutable review case
  -> authorization and approval policy
  -> freeze mutation request with expected version + idempotency key
  -> transactional outbox
  -> NocPro adapter dry-run/revalidation/dispatch
  -> ACK reconciliation
  -> authoritative post-snapshot partition verification
  -> outcome observation window
  -> append truth-tier update
  -> later cutoff-frozen retrieval index and batch model training
```

## 20. Public output

Before approval:

```json
{
  "status": "APPROVAL_REQUIRED",
  "recommendation": {
    "candidate_id": "cand-4",
    "operation": "MOVE",
    "rank": 1,
    "rank_score": 1.734,
    "hard_gate": "PASS",
    "before_metrics": {},
    "after_metrics": {},
    "similar_cases": [
      {"case_id": "case-71", "similarity": 0.89, "truth_tier": "PO_ASSERTED"}
    ]
  },
  "mutation_capability": {
    "status": "AVAILABLE",
    "adapter_version": "nocpro-mutation-v1",
    "required_approvals": 1
  }
}
```

After dispatch and verification:

```json
{
  "mutation_request_id": "mut-778",
  "state": "APPLIED_CONFIRMED",
  "transport_acknowledged": true,
  "authoritative_partition_verified": true,
  "before_snapshot_version": "42",
  "after_snapshot_version": "43",
  "outcome_status": "OBSERVING",
  "audit_event_count": 9,
  "limitations": ["Operational success window has not completed"]
}
```

The UI must show model recommendation, human decision, dispatch state,
authoritative verification, and outcome as separate fields.

## 21. Storage and audit model

Recommended logical tables/streams:

- `review_session`, `candidate_exposure`, `review_feedback`,
  `manual_correction`, `review_case`, `outcome_observation`;
- `delay_model_artifact`, `review_case_similarity_index`,
  `ranker_model_artifact`;
- `mutation_request` immutable intent;
- `mutation_approval` append-only approvals/retractions;
- `mutation_transition` append-only state history;
- `mutation_outbox` and dispatch-attempt records;
- `upstream_acknowledgment` with redacted request/response fingerprints;
- `mutation_verification` authoritative before/after comparison;
- `compensation_link` relating original and corrective actions.

Retention must support incident investigation and model reproducibility. Logs
must redact credentials and avoid copying unrestricted raw payloads where a
fingerprint/reference is sufficient.

## 22. Security and feedback integrity

- Short-lived service credentials in a secret manager; never in artifacts.
- Mutual authentication/TLS and strict destination allowlist.
- Least privilege per operation/domain/environment.
- Server-derived identity, role, domain, and policy.
- Tamper-evident append-only audit trail and synchronized timestamps.
- Signed or integrity-checked model/config/artifact references.
- Rate and impact limits, circuit breaker, and global kill switch.
- Reviewer anomaly monitoring, duplicate influence caps, disagreement
  preservation, and label quarantine.
- No immediate online learning; batch training and independent promotion avoid
  a self-reinforcing feedback loop.
- Production and mock/staging identities and source kinds cannot mix.

## 23. Evaluation and production gates

### 23.1 Recommendation plane

- KDE grouped out-of-time/episode validation and coverage;
- similar-case recall@k and common-block abstention;
- XGBoost NDCG/top-k recall/regret against deterministic/Pareto baseline;
- slices by operation, domain, source kind, truth tier, and time;
- no time, lineage, review-group, taxonomy, or outcome leakage;
- reproducible frozen artifacts and fallback on mismatch/drift.

### 23.2 Mutation plane

- contract tests against a documented upstream sandbox;
- stale-version rejection and compare-and-set proof;
- duplicate delivery with one idempotent effect;
- timeout-after-send reconciliation;
- partial-response detection;
- service restart with outbox recovery;
- exact before/intended/actual partition verification;
- compensation and manual-intervention paths;
- authorization, two-person rule, expiry, revocation, and domain limits;
- metrics/alerts for queue age, attempt count, stale/conflict/partial/unknown,
  verification latency, and unintended deltas.

### 23.3 Rollout levels

1. `L0_REVIEW_ONLY`: store reviews; never dispatch.
2. `L1_SHADOW_MUTATION`: build/validate requests against mock or upstream
   dry-run; no real effect.
3. `L2_CONTROLLED_CANARY`: one low-impact operation/domain, manual approval,
   tiny rate, staffed observation, immediate kill switch.
4. `L3_BOUNDED_PRODUCTION`: more operations only after operation-specific
   evidence and governance approval.

Any future unattended mode requires a separate design/ADR, risk assessment,
and approval. It is not implied by this document.

## 24. Test strategy

- Contract tests for every canonical, review, model, approval, mutation, ACK,
  verification, outcome, and compensation object.
- Property tests that hard-gate failures can never become dispatchable.
- Leakage tests with future cases/outcomes and same-lineage duplicates.
- Feedback lifecycle tests for correction, retraction, disagreement, none
  acceptable, and manual correction.
- State-machine transition tests rejecting illegal jumps.
- Persistence/restart tests around each outbox/dispatch boundary.
- Duplicate, timeout, stale, conflict, partial, verify-failed, and compensation
  integration tests.
- End-to-end mock tests for remove/move/split/merge, explicitly labeled
  `SYNTHETIC_TEST`.
- Sandbox NocPro tests for authoritative versioning and idempotency.
- Canary runbook tests for kill switch, alert escalation, and reconciliation.
- Negative tests proving UI/LLM/client fields cannot self-authorize mutation.

## 25. Failure behavior

| Failure | Behavior |
|---|---|
| Model unavailable or drifting | Deterministic/Pareto recommendation fallback |
| Similarity basis too weak | Hide recommendation memory and explain abstention |
| No safe candidate | No approval/apply action |
| Missing mutation capability | Review-only mode |
| Stale upstream version | Mark stale; regenerate review from new snapshot |
| Duplicate request | Reuse/reconcile same idempotency key |
| Timeout after send | Unknown state; block overlap; reconcile |
| ACK but delta mismatch | `VERIFY_FAILED`/`PARTIAL`; no success label |
| Outcome unobservable | `OUTCOME_UNKNOWN`; no positive training label |
| Unsafe compensation | Manual intervention |

## 26. Definition of done for this design

The closed-loop repository is complete only when:

- the review-only learning/data requirements are satisfied;
- PO decisions are stored with provenance, truth tier, exposure context,
  supersession, and similar-case fingerprints;
- KDE/retrieval/XGBoost pass temporal and lineage-separated evaluation;
- the authoritative NocPro mutation contract is documented and tested;
- permissions, approvals, expiry, version preconditions, idempotency, and
  conflict controls are enforced server-side;
- ACK, authoritative application, and operational outcome are reported as
  separate states;
- every applied change is reconciled to a new authoritative snapshot;
- partial/unknown/failure and compensation paths work across process restarts;
- audit artifacts reproduce who approved what, against which data/model/config,
  what upstream observed, and what outcome followed;
- canary gates pass per operation and domain;
- disabling the mutation adapter returns the complete system safely to
  review-only mode.
