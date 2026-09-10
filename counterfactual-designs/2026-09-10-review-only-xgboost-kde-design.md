# Review-only Counterfactual Learning: KDE + XGBoost Ranker

**Date:** 2026-09-10
**Status:** Proposed design; not implemented
**Operating mode:** Read-only recommendation and human review
**Repository scope:** `nocpro-mock` input/replay and `nocpro-chain-explain` analysis/API/UI
**Safety boundary:** This design never changes the authoritative NocPro chain partition.

## 1. Executive decision

The most suitable near-term model stack for the repository is:

1. a versioned temporal delay model using histogram/KDE per alarm-taxonomy
   relation; and
2. an XGBoost learning-to-rank model that reorders counterfactual candidates
   already generated and validated by the deterministic engine.

The system also needs a deterministic Review Case Store. When a Product Owner
(PO), NOC operator, or domain expert reviews a remove, move, split, or merge
proposal, the complete decision context is stored. Later reviews retrieve
similar prior cases and expose them as evidence. This store is useful before
there is enough data to train XGBoost.

PO feedback is valuable operational supervision, but it is not automatically
treated as causal or outcome-verified truth. It is stored first as
`PO_ASSERTED`; its truth tier can be upgraded only through consensus or a
verified operational outcome.

KDE, deterministic similar-case retrieval, and XGBoost have different jobs:

| Component | Question answered | May change a chain? |
|---|---|---:|
| Deterministic counterfactual engine | Is this edit valid, and what exact metrics change? | No |
| KDE/histogram delay model | Is this directed alarm delay typical for this relation? | No |
| Review-case retrieval | Which earlier reviewed situations look similar? | No |
| XGBoost ranker | Among eligible candidates, which should a reviewer inspect first? | No |
| Human reviewer | Accept, reject, defer, or provide a correction | No in this design |

## 2. Goals

- Preserve exact deterministic candidate generation, metric calculation, hard
  gates, and Pareto eligibility.
- Learn temporal regularity from historical episodes without future leakage.
- Learn candidate ordering from explicit human judgments and later verified
  outcomes.
- Reuse PO/domain experience through transparent, versioned similar-case
  retrieval even before a ranker is production-ready.
- Support `REMOVE`, `MOVE`, `SPLIT`, and `MERGE`; keep the schema extensible for
  later operations.
- Return enough evidence for a reviewer to understand why a proposal is high
  ranked and when the model abstained.
- Keep synthetic, replayed-real, and live-real evidence separate.

## 3. Non-goals

- No automatic mutation or dispatch to NocPro.
- No replacement of hard gates with a model probability.
- No treatment of unreviewed candidates as rejected candidates.
- No use of an LLM as a scorer, labeler, ground-truth source, or mutation
  authority.
- No claim that topology adjacency proves dependency or causality.
- No Siamese/DeepSets model in the first release. The label volume and label
  quality do not yet justify it.
- No immediate online retraining after each review. Models are frozen,
  evaluated, approved, and deployed by version.

## 4. Current repository baseline

The repository already has most of the deterministic shell required around the
two proposed models:

- canonical input models in `nocpro-chain-explain/contracts/v1/models.py`;
- replay and normalization in `nocpro-mock`;
- Tier-1 explanation and Tier-2 audit/review;
- deterministic counterfactual generation for remove/split/move/merge;
- exact affected-region metric recomputation, hard gates, edit cost, and Pareto
  output;
- a versioned Similar Chains fingerprint/cosine baseline;
- temporal-history infrastructure with cutoff and lineage fingerprints;
- a temporal delay implementation that supports histograms and Gaussian KDE;
- asynchronous review jobs, API responses, web UI, and coarse operator
  feedback persistence.

Important gaps remain:

- the delay model is not yet supplied with an authoritative, sufficiently long
  real sequential corpus and complete taxonomy mapping;
- the current feedback contract is centered on a selected recommendation and
  is too small for unbiased learning-to-rank;
- there is no first-class reviewed-case fingerprint for decisions such as
  “move this member to chain B” or “merge these two chains”;
- there is no frozen XGBoost training artifact or promotion gate;
- available topology exports are useful for navigation and structural context,
  but their edge direction is not yet verified as dependency direction.

## 5. Current data inventory and what it can support

The following measurements are the audited repository snapshot used for this
design. They must be regenerated as a versioned data-profile artifact before
model training.

### 5.1 Alarm and chain exports

| Dataset | Rows | Chain IDs | Singleton chains | Largest chain | Important limitation |
|---|---:|---:|---:|---:|---|
| `alarm_data.csv` | 8,714 | 2,824 | 2,072 (73.37%) | 1,072 | Timestamp anomalies, including future dates and end-before-start records |
| `alarmIP.csv` | 212,636 | 87,206 | 64.84% | 1,018 | No dependable root/candidate review label |
| `alarmIT.csv` | 258,344 | 82,453 | 78.03% | 59,176 | `is_root_alarm` semantics/provenance unverified; `label_alarm` is nearly empty |

Additional observations:

- `alarm_data.csv` has `node_reference` on approximately 98.06% of rows, but
  high presence does not prove semantic correctness.
- In `alarmIT.csv`, non-empty `is_root_alarm` values were observed as 0, 1, and
  2; these values must not become training labels until their producer,
  meaning, and time validity are documented.
- A row is not an independent training example when many rows belong to the
  same snapshot, chain, episode, or lineage. Effective sample size is counted
  at the review group/episode level.

### 5.2 Topology exports

| Dataset | Current usable signal | Mapping observation | Missing semantic guarantee |
|---|---|---|---|
| IP topology | 201,977 device-port adjacency edges | 140,596/212,636 alarms exactly mapped (66.121%); 1,294/2,908 device codes represented | Direction, active path, dependency, failure domain |
| IT topology | 128,322 normalized nodes and 218,635 edges | 169,836/258,344 alarms uniquely resolved (65.74%) | Edge direction as operational dependency; ambiguous/unmapped resolution |

Topology-derived features must report mapping coverage and relation type. They
are unavailable when the required semantic contract is absent; they are not
silently imputed from names or prefixes.

### 5.3 What is feasible now

- Deterministic counterfactual review: feasible now.
- Review Case Store and transparent similarity baseline: feasible after the
  feedback contract is expanded.
- KDE/histogram experimentation: feasible on replay/history that passes
  timestamp, taxonomy, episode, and cutoff validation; production claims are
  not yet justified.
- XGBoost pipeline and offline experiments: feasible after candidate-level
  feedback collection begins.
- Production XGBoost ranking: blocked until independently reviewed groups cover
  all supported operations and pass temporal/lineage holdout gates.
- Siamese DeepSets: defer until a strong deterministic/XGBoost baseline exists
  and the review corpus is large and diverse enough to justify representation
  learning.

## 6. Canonical end-to-end input

### 6.1 Snapshot package

The analysis input remains the canonical `MockSnapshotPackage`/Input Contract
v1, not a model-specific CSV. It contains:

- snapshot identity, version, event time, source, `source_kind`, and quality;
- alarms and normalized event timestamps;
- chains and memberships;
- system metadata and versioned alarm taxonomy;
- optional topology, mappings, active paths, and failure domains;
- operational context;
- provenance manifest and input fingerprints.

Illustrative input:

```json
{
  "schema_version": "1.0",
  "snapshot": {
    "snapshot_id": "snap-20260910-0900",
    "snapshot_version": "42",
    "event_time": "2026-09-10T02:00:00Z",
    "source": "nocpro-export",
    "source_kind": "REAL_EXPORT_REPLAY",
    "quality_status": "PASS"
  },
  "alarms": [
    {
      "alarm_id": "a-101",
      "occurred_at": "2026-09-10T01:57:14Z",
      "taxonomy_type": "LINK_DOWN",
      "taxonomy_family": "CONNECTIVITY",
      "device_id": "device-17"
    }
  ],
  "chains": [{"chain_id": "chain-A"}, {"chain_id": "chain-B"}],
  "memberships": [
    {"chain_id": "chain-A", "alarm_id": "a-101"}
  ],
  "topology": {
    "relation_type": "PHYSICAL_ADJACENCY",
    "mapping_version": "map-12"
  },
  "provenance_manifest": {
    "taxonomy_version": "taxonomy-7",
    "input_fingerprint": "sha256:..."
  }
}
```

### 6.2 Historical model corpus

For a review at time `t`, both retrieval and model features may use only events
strictly before `t`. A historical episode record needs at least:

```json
{
  "episode_id": "episode-882",
  "lineage_component_id": "lineage-55",
  "snapshot_id": "snap-41",
  "snapshot_version": "41",
  "event_time": "2026-09-09T08:10:00Z",
  "source_kind": "REAL_EXPORT_REPLAY",
  "alarm_ids": ["a-1", "a-2", "a-3"],
  "chain_ids": ["chain-old-A"],
  "taxonomy_version": "taxonomy-7",
  "quality_status": "PASS"
}
```

The corpus must preserve lineage so that repeated states of the same incident
are not counted as independent evidence.

## 7. Missing data required for a complete repository

### 7.1 Authoritative taxonomy and time-valid mappings

Required fields:

```text
taxonomy_id, taxonomy_version, alarm_code, type, family, category,
valid_from, valid_to, source_system, source_record_id, mapping_status
```

Why it is needed: KDE relation keys and semantic features are invalid if the
same alarm code changes meaning over time or an unresolved code is guessed.

### 7.2 Verified sequential snapshots and incident lineage

Required fields:

```text
snapshot_id, snapshot_version, captured_at, ingest_at, source_kind,
incident_id, episode_id, lineage_component_id, predecessor_snapshot_id,
quality_status, completeness_window
```

Why it is needed: KDE, drift, train/test separation, and outcome verification
all require temporal order. A single export cannot establish temporal
regularity.

### 7.3 Candidate exposure log

Every evaluated candidate, not only the top recommendation, must be stored:

```json
{
  "review_id": "review-991",
  "candidate_id": "cand-4",
  "candidate_rank_shown": 3,
  "shown_to_reviewer": true,
  "generated_by": "deterministic-v5",
  "eligibility": "HARD_GATES_PASSED",
  "model_score": 0.61,
  "model_version": "ranker-2026-10-01",
  "exposure_policy": "TOP_K_PLUS_AUDIT_SAMPLE"
}
```

Why it is needed: storing feedback only for recommendations creates selection
bias. The system must know what was generated, eligible, shown, and judged.

### 7.4 Rich human review labels

Minimum review record:

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
  "reason_text": "Move access alarm to the maintenance chain",
  "truth_tier": "PO_ASSERTED",
  "created_at": "2026-09-10T02:08:00Z",
  "supersedes_feedback_id": null,
  "status": "ACTIVE",
  "artifact_fingerprints": {
    "snapshot": "sha256:...",
    "candidate": "sha256:...",
    "features": "sha256:...",
    "config": "sha256:..."
  }
}
```

The UI/API must also accept:

- `REJECT`;
- `DEFER` or `INSUFFICIENT_EVIDENCE`;
- `NONE_ACCEPTABLE` for the whole candidate set;
- a manual corrected partition or corrected operation;
- retraction/supersession of an earlier review;
- a review on any evaluated candidate, not only the recommended candidate.

### 7.5 Post-decision outcome

Review-only operation can begin without this data, but production-quality
learning needs it:

```text
change_id, intended_candidate_id, authoritative_before_version,
authoritative_after_version, applied_at, verified_at, actual_partition_delta,
incident_recurrence_window, stability_result, sla_effect, reverted,
outcome_status, verifier_id, evidence_fingerprint
```

### 7.6 Upstream NocPro metadata

If available, collect versioned rule/config/attribute facts that explain the
original chaining decision. These remain typed as system facts and must not be
silently converted into independent causal evidence.

## 8. Ground-truth policy

### 8.1 Truth tiers

| Tier | Meaning | Training use |
|---|---|---|
| `PO_ASSERTED` | One PO decision based on domain experience | Eligible with configured weight after validation |
| `EXPERT_CONSENSUS` | Required reviewers agree under a documented policy | Higher weight |
| `APPLIED_CONFIRMED` | Authoritative system confirms the intended edit was applied | Confirms action, not benefit |
| `OUTCOME_VERIFIED` | Post-change observation passes the defined success window | Highest positive weight |
| `OUTCOME_CONTRADICTED` | Verified outcome conflicts with the recommendation | Strong negative evidence |

Truth tier and label are separate. For example, `REJECT + PO_ASSERTED` means a
PO rejected the candidate; it does not mean an objective outcome was observed.

### 8.2 Lifecycle

Feedback records are append-only. Corrections create a new record with
`supersedes_feedback_id`; the prior record becomes `SUPERSEDED`. Records may be
`ACTIVE`, `RETRACTED`, or `SUPERSEDED`. Training materialization reads only the
latest active record valid before the training cutoff.

### 8.3 Label conversion for ranking

- `OUTCOME_VERIFIED` approved candidate: relevance 3.
- Approved candidate with consensus or applied confirmation: relevance 2.
- Single asserted approval: relevance 1 or 2 according to the frozen label
  policy; it must not silently change between model versions.
- Explicit rejection or outcome contradiction: relevance 0.
- `DEFER`, `INSUFFICIENT_EVIDENCE`, and unreviewed: excluded from relevance
  labels; they may be used only for coverage/abstention analysis.
- `NONE_ACCEPTABLE` records a group-level failure and must not invent a best
  candidate.

Sample weights encode truth tier, reviewer authority within declared domain,
consensus, and duplication. Raw label values do not.

## 9. Model A: temporal histogram/KDE

### 9.1 Purpose

Estimate how typical a positive directed delay is for a semantic relation:

```text
relation_key = (level, source_taxonomy_token, target_taxonomy_token)
delay = target.occurred_at - source.occurred_at
```

`level` may be `TYPE`, `FAMILY`, or a documented fallback. Equal timestamps do
not establish direction. Negative delays are not swapped into positives unless
the ordering rule independently establishes direction.

### 9.2 Training observations

Build observations only from eligible historical episodes before an exclusive
cutoff:

```json
{
  "episode_id": "episode-882",
  "snapshot_id": "snap-41",
  "chain_id": "chain-old-A",
  "source_alarm_id": "a-1",
  "target_alarm_id": "a-2",
  "relation_key": ["FAMILY", "POWER", "CONNECTIVITY"],
  "delay_seconds": 47.0
}
```

Rules:

- use only validated event times and taxonomy mappings;
- deduplicate by episode and pair identity;
- balance contribution per episode so one huge chain cannot dominate;
- exclude the target lineage from its own retrieval/evaluation corpus;
- group train/validation by episode and time, never by random alarm row;
- persist cutoff, corpus fingerprint, lineage-prefix fingerprint, taxonomy
  versions, source-kind mix, and config.

### 9.3 Model selection and fallback

For each relation with enough independent episodes:

1. compare a histogram density with Gaussian KDE on grouped temporal holdout;
2. select bandwidth/bin configuration using frozen scoring criteria;
3. store the selected estimator and diagnostics;
4. back off from `TYPE` to `FAMILY` or global eligible relation when coverage
   is insufficient;
5. return `UNAVAILABLE` when no defensible fallback exists.

KDE output is a typicality/evidence feature, not a causal probability.

### 9.4 Output

```json
{
  "status": "AVAILABLE",
  "relation_key": ["FAMILY", "POWER", "CONNECTIVITY"],
  "delay_seconds": 47.0,
  "density": 0.013,
  "local_mass": 0.72,
  "percentile": 0.64,
  "fallback_level": null,
  "independent_episode_count": 184,
  "model_kind": "GAUSSIAN_KDE",
  "model_version": "delay-2026-10-01",
  "training_cutoff": "2026-10-01T00:00:00Z",
  "corpus_fingerprint": "sha256:..."
}
```

## 10. Review Case Store and similarity

### 10.1 Why this precedes Siamese DeepSets

A deterministic multi-block fingerprint is reproducible, debuggable, works
with few labels, and matches the repository's existing Similar Chains design.
A Siamese model becomes reasonable only after there are many independent,
diverse, high-quality reviewed cases and the deterministic baseline has a
measured recall ceiling.

### 10.2 Case object

A case freezes:

- before snapshot/chain context;
- the full candidate set and what the reviewer saw;
- the chosen/rejected/manual correction;
- exact before/after metrics and structural facts;
- KDE and topology availability at decision time;
- reviewer decision, reason, truth tier, and lifecycle;
- later outcome records;
- every schema/config/model/corpus fingerprint.

### 10.3 Fingerprint blocks

1. **Chain context:** domain/source, size and duration bins, family/device-type
   histograms, mapping ratio, source kind.
2. **Evidence shape:** weak-member ratio, minimum support, coverage,
   components, audit verdict, conductance, articulation count, unavailable
   channel count.
3. **Temporal shape:** burst count, dominant delay typicalities, atypical pair
   ratio, delay model version and coverage.
4. **Topology shape:** mapping coverage, declared relation type, eligible hop or
   proximity summaries; unavailable if semantics fail.
5. **Operation pattern:** abstract edit, not raw IDs, for example
   `MOVE_WEAK_NON_CONNECTOR_TO_HIGHER_FIT_LOCAL_CHAIN`,
   `REMOVE_WEAK_NON_CONNECTOR`, `SPLIT_LOW_CONDUCTANCE_BLOCKS`, or
   `MERGE_LOCALLY_SIMILAR_SUPPORTED_CHAINS`.

Raw alarm IDs, chain IDs, and direct device identifiers are lookup keys, not
similarity features.

### 10.4 Similarity algorithm

- Apply compatibility gates for schema, domain, operation family, source-kind
  policy, and valid model/cutoff semantics.
- Compute one normalized score per available block.
- Renormalize weights over blocks available in both cases; never fill a missing
  block with zero as if it were negative evidence.
- Combine deterministic weighted block similarity with the existing
  TF-IDF/cosine Similar Chains signal.
- Retrieve only cases created before the current review time.
- Exclude the same lineage by default; display previous same-lineage states in
  a separate section.
- Return `UNAVAILABLE` or abstain when common-block coverage is below the
  configured threshold.

### 10.5 Similar-case output

```json
{
  "status": "AVAILABLE",
  "retrieval_version": "review-case-sim-v1",
  "query_fingerprint": "sha256:...",
  "common_block_coverage": 0.86,
  "cases": [
    {
      "case_id": "case-71",
      "similarity": 0.89,
      "block_scores": {
        "chain_context": 0.91,
        "evidence_shape": 0.88,
        "temporal_shape": 0.84,
        "operation_pattern": 1.0
      },
      "decision": "APPROVE",
      "truth_tier": "PO_ASSERTED",
      "reason_codes": ["KNOWN_MAINTENANCE_PATTERN"],
      "reviewed_at": "2026-08-21T03:12:00Z"
    }
  ]
}
```

A retrieved case is evidence for the reviewer and an aggregate ranker feature;
one case never becomes a direct deterministic command.

## 11. Model B: XGBoost learning-to-rank

### 11.1 Unit of learning

Each row is one deterministic candidate. `qid` identifies the review group,
normally one frozen `review_id` for a snapshot, chain, target scope, and
candidate-generator version. Candidates from a group must remain together in
train, validation, and test partitions.

### 11.2 Eligible candidate pool

The ranker scores only candidates that:

- were generated by a versioned deterministic operation generator;
- have exact affected-region metrics;
- pass every mandatory invariant and hard gate;
- have a reproducible candidate fingerprint.

The deterministic/Pareto order remains the fallback. Whether the ranker scores
all hard-gate-passing candidates or only the Pareto frontier is a frozen config
choice and must be evaluated offline; it cannot vary per request invisibly.

### 11.3 Feature groups

- operation one-hot and abstract operation pattern;
- exact before metrics, after metrics, and signed deltas;
- edit cost and affected-region size;
- candidate source/generator version category;
- structural facts: component changes, articulation effects, conductance,
  weak-member movement, destination-fit margin;
- evidence availability and quality, not fabricated zeroes;
- source kind and data-quality flags;
- KDE aggregates: available-pair coverage, mean/quantile typicality, atypical
  pair fraction, fallback fraction;
- review-case aggregates: maximum approved similarity, top-k approved and
  rejected mean similarity, verified/asserted case counts, contradiction rate,
  same-operation coverage;
- topology summaries only when their declared semantics are eligible.

Do not train on raw alarm ID, chain ID, snapshot ID, reviewer ID, or direct
device code. These encourage memorization and identity leakage.

### 11.4 Training artifact

```json
{
  "model_family": "XGBRanker",
  "objective": "rank:ndcg",
  "model_version": "cf-ranker-2026-11-15",
  "feature_schema_version": "cf-features-v1",
  "label_policy_version": "review-label-v1",
  "training_cutoff": "2026-11-01T00:00:00Z",
  "group_count": 642,
  "operation_coverage": ["REMOVE", "MOVE", "SPLIT", "MERGE"],
  "corpus_fingerprint": "sha256:...",
  "hyperparameters": {},
  "validation_metrics": {},
  "source_kind_breakdown": {},
  "approved_by": "model-governance-record-id"
}
```

### 11.5 Inference output

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
  "top_feature_contributions": [
    {"feature": "delta_min_membership_support", "contribution": 0.41},
    {"feature": "max_similar_approved_case", "contribution": 0.23}
  ],
  "similar_cases": ["case-71", "case-44"]
}
```

The score is relative within the candidate group and must not be displayed as
“87% correct” unless a separate, validated calibration model actually supports
that interpretation.

## 12. Full review-only flow

```text
Canonical snapshot package
  -> provenance/quality/capability validation
  -> Tier-1 + Tier-2 deterministic evidence
  -> deterministic REMOVE/MOVE/SPLIT/MERGE candidates
  -> exact before/after metrics + hard gates
  -> KDE temporal features (or typed UNAVAILABLE)
  -> prior review-case retrieval (strictly before review time)
  -> XGBoost ranker if promoted and in-distribution
       otherwise deterministic/Pareto fallback
  -> reviewer sees ranked candidates and similar cases
  -> reviewer judges any candidate / none / manual correction
  -> append feedback and frozen case to database
  -> later batch materialization for retrieval/training
```

There is deliberately no mutation arrow after review.

## 13. API and storage contracts

### 13.1 Recommended logical tables

- `review_session`: identity, target, cutoff, candidate-set fingerprint,
  generator/config/model versions.
- `candidate_exposure`: every candidate, original/ranked position, shown flag,
  deterministic eligibility, immutable feature snapshot.
- `review_feedback`: append-only decision, reviewer role/scope, confidence,
  reasons, truth tier, lifecycle/supersession.
- `manual_correction`: normalized intended partition delta supplied by reviewer.
- `review_case`: immutable case bundle and fingerprint.
- `review_case_similarity_index`: versioned encoded blocks and corpus cutoff.
- `delay_model_artifact`: relation estimators, cutoff and corpus fingerprints.
- `ranker_model_artifact`: model bytes/reference, feature/label schema,
  evaluation, approval status.
- `outcome_observation`: optional later result and truth-tier upgrades.

### 13.2 Review API request

```json
{
  "review_id": "review-991",
  "candidate_id": "cand-4",
  "decision": "APPROVE",
  "confidence": 0.85,
  "reason_codes": ["KNOWN_MAINTENANCE_PATTERN"],
  "reason_text": "...",
  "expected_snapshot_version": "42"
}
```

The server derives reviewer identity, role, and permitted domain from the
authenticated principal; clients cannot self-assert authority.

### 13.3 Public review response

```json
{
  "status": "REVIEW_REQUIRED",
  "snapshot_id": "snap-20260910-0900",
  "snapshot_version": "42",
  "chain_id": "chain-A",
  "ranking": {
    "status": "AVAILABLE",
    "model_version": "cf-ranker-2026-11-15",
    "fallback": false
  },
  "candidates": [
    {
      "candidate_id": "cand-4",
      "operation": "MOVE",
      "from_chain_id": "chain-A",
      "to_chain_id": "chain-B",
      "member_ids": ["a-101"],
      "hard_gate": "PASS",
      "pareto_eligible": true,
      "before_metrics": {},
      "after_metrics": {},
      "metric_deltas": {},
      "rank": 1,
      "rank_score": 1.734,
      "similar_cases": [],
      "limitations": []
    }
  ],
  "allowed_actions": [
    "APPROVE_AS_FEEDBACK",
    "REJECT",
    "DEFER",
    "NONE_ACCEPTABLE",
    "SUBMIT_MANUAL_CORRECTION"
  ],
  "mutation_dispatched": false
}
```

## 14. Leakage, bias, and poisoning controls

- Enforce exclusive time cutoffs in code and artifact identity.
- Split evaluation by time, review group, and lineage; never random alarm rows.
- Keep all candidates from one review in one partition.
- Exclude future feedback, outcomes, taxonomy versions, and similarity cases.
- Log exposure position and policy; optionally show a bounded audit sample from
  lower-ranked candidates to measure position bias.
- Never convert “not shown” or “not reviewed” to negative.
- Cap duplicate/near-duplicate lineage influence.
- Require authenticated roles and domain scope; detect anomalous reviewer and
  reason-code patterns.
- Preserve disagreement instead of overwriting it.
- Quarantine retracted, contradictory, malformed, or out-of-policy labels.
- Retrain in batches and require evaluation/approval; no instant feedback loop.

## 15. Evaluation and promotion gates

### 15.1 KDE

- timestamp and taxonomy contract pass rate;
- independent episode/relation coverage;
- grouped temporal holdout log-likelihood or frozen density score;
- calibration of local-mass/percentile summaries;
- fallback and unavailable rates by domain/source kind;
- stability across successive cutoffs;
- no future or same-lineage leakage.

### 15.2 Review-case retrieval

- recall@k for prior cases reviewers mark as relevant;
- agreement between retrieved operation pattern and reviewed correction;
- common-block coverage and abstention rate;
- temporal/lineage holdout, not same-case reconstruction;
- slice results by operation, domain, source kind, and truth tier.

### 15.3 XGBoost ranker

- NDCG@k and top-1/top-3 approved-candidate recall;
- regret against the best explicitly reviewed candidate;
- `NONE_ACCEPTABLE` and abstention safety analysis;
- comparison against deterministic/Pareto order and simple linear/logistic
  baselines;
- operation/domain/time/source-kind slices with confidence intervals;
- label coverage for both positive and negative explicit judgments;
- learning curves based on independent review groups.

No fixed row count alone authorizes production. Promotion requires stable
out-of-time performance, coverage of each enabled operation, acceptable safety
slices, reproducible artifacts, and documented model approval. A pilot target
such as hundreds of independent reviewed groups is planning guidance, not an
automatic gate.

## 16. Failure and abstention behavior

| Condition | Required behavior |
|---|---|
| Missing/invalid taxonomy or time | KDE unavailable; do not guess relation |
| Too few independent episodes | Use declared fallback or unavailable |
| Ranker artifact/config mismatch | Deterministic order and diagnostic |
| Feature outside training contract | Ranker abstains |
| Similar cases share too few blocks | Retrieval unavailable |
| Stale snapshot/version | Reject review submission |
| No candidate passes hard gates | Return no safe candidate |
| Reviewer selects none | Persist `NONE_ACCEPTABLE`; do not invent positive label |
| Conflicting feedback | Preserve both, apply consensus policy, possibly exclude |

## 17. Delivery phases

1. **Data contract and profiling:** version taxonomy, episodes, candidate
   exposure, rich feedback, lineage, and outcome schemas.
2. **Review memory:** persist every evaluated candidate and reviewer decision;
   implement deterministic multi-block case retrieval.
3. **KDE offline:** materialize frozen delay models and expose typed temporal
   diagnostics without changing candidate ordering.
4. **Ranker shadow mode:** score but retain deterministic order; collect
   comparative metrics and drift.
5. **Review ranking mode:** reorder only eligible candidates when promotion
   gates pass; retain fallback and full diagnostics.
6. **Continuous batch governance:** time-cutoff retraining, evaluation,
   approval, deployment, monitoring, and rollback to prior model version.

## 18. Definition of done for this design

The review-only repository is complete only when:

- real input and provenance contracts are validated and reproducible;
- every candidate exposure and decision is stored without selection-label
  ambiguity;
- PO feedback is retrievable as versioned asserted evidence;
- similar-case results show block-level similarity and truth tier;
- KDE and ranker artifacts are frozen by cutoff, schema, config, and corpus;
- temporal/lineage holdout evaluation beats or safely complements the
  deterministic baseline;
- missing data produces typed abstention rather than fabricated scores;
- the API/UI always says `REVIEW_REQUIRED` and never dispatches a mutation;
- tests prove stale-version rejection, leakage prevention, artifact mismatch
  fallback, feedback supersession, and no-mutation behavior.
