# Evidence-Faithful Explain, Counterfactual, and Learning Design

**Date:** 2026-09-14  
**Status:** Approved for implementation  
**Scope:** Explain threshold optimization, counterfactual clarity comparison and reranking, review-learning provenance/training, and data-truth corrections in existing UI.

## Goal

Make the Explain -> Counterfactual -> Learn flow evidence-faithful. A proposed
threshold must be evaluated by the same analysis engine as the active
configuration; an explanation comparison must never promote an ineligible
proposal; and learning must distinguish real reviewed feedback from synthetic
fixtures. The existing UI layout, routes, and operator flow remain intact.

## Constraints

- The Tier-1B role engine and deterministic counterfactual gates remain the
  source of truth. Narrative and clarity code cannot create verdicts, causal
  claims, or recommendations.
- An unavailable channel is not a zero score and is not negative evidence.
- Preserve every evaluated counterfactual in immutable audit exposure. Only
  candidates that passed hard gates and are selected by the deterministic
  frontier may be ranked or called a proposal in clarity comparison.
- No live mutation of NocPro chains is introduced.
- Do not redesign the UI. Retain components, layout, modal routes, and control
  flow; change only source-backed copy, states, disabled actions, and displayed
  values.
- Synthetic fixtures remain available for tests and explicit demo mode, but are
  visibly labelled `SYNTHETIC_TEST`/`TEST_FIXTURE` and never masquerade as
  `PO_ASSERTED` feedback or a production model.

## Threshold optimization

### Candidate configurations

The optimizer evaluates a bounded, deterministic neighbourhood of the current
role configuration. Each candidate changes only configurable role parameters
and is validated through the same `Workspace.update_parameters` rules before
analysis. The selected candidate includes the current configuration and unique,
valid neighbours inside configured bounds; it does not use a hand-written role
simulation.

### Isolated analysis

Each trial runs `analyze_chain_configured` with an analysis configuration whose
role values are replaced for that trial. It does not mutate the workspace,
cache, jobs, or persisted configuration. The returned trial contains the exact
role counts and availability obtained from the real engine.

The optimization output remains descriptive, not a calibration claim. It may
select the most concise evidence-backed rendering among trials with equal or
better evidence quality. It must not claim causal relation, root cause, optical
failure, or an action unless the structured analysis/counterfactual result
contains that fact.

### Selection and application

Trials rank first by explicit evidence quality: fewer `INSUFFICIENT_DATA`, then
more computable role decisions, then a deterministic role-distribution tie
break. The presentation-quality score is a final tie-break only. This avoids
choosing a prettier sentence that loses evidence coverage.

Applying a selected threshold remains an explicit operator action. It updates
the existing workspace-wide configuration and clears existing caches exactly as
`Workspace.update_parameters` already does. The response states that scope and
returns `APPLIED` only after validation and mutation succeed. A validation
failure propagates as a client error; no success response is emitted.

## Explanation rendering and clarity comparison

### Deterministic explanation facts

The optimizer builds its before/after text solely from chain identity, observed
member count, exact role counts, availability reasons, and parameter values.
It uses conditional language for proposals and never infers a root cause.

The comparator accepts an optional structured evidence context. Specificity
credits observed entity/alarm/metric facts only when they appear in the supplied
fact set. Causality is `UNAVAILABLE` unless a supplied structured causal fact
permits it. Actionability is `UNAVAILABLE` unless a supplied allowed operation
or action fact permits it. Lexical wording may help evaluate concision only.

### Proposal eligibility

`compare_proposal_explanations` filters its input to candidates where:

- `hard_gate_result.status == "PASSED"`;
- `pareto_state` is `FRONTIER_SELECTED` or `FRONTIER_TRUNCATED`; and
- `evaluation_status` is not a rejected/contradicted/unavailable state.

If no candidate qualifies, the endpoint returns an empty comparison with an
explicit unavailable rationale. Ineligible candidates remain visible in the
ordinary audit result with their gate reason.

## Review learning

### Serving invariant

Exposure creation continues to capture all evaluated candidates. Reranking
operates only on exposures whose `hard_gate_status` is `PASSED` and whose
deterministic eligibility is `HARD_GATES_PASSED`; all other exposures retain
their original rank and an audit record of `INELIGIBLE_NOT_RERANKED`.

The public recommendation order may therefore change only inside the eligible
set. A model cannot promote a rejected, dominated, or unavailable candidate.

### Training sources

The normal API training endpoint is removed/disabled as a synthetic generator.
Training through the UI is unavailable until an authenticated, server-owned
PostgreSQL review corpus exists and `assess_data_readiness` reports sufficient
review readiness. The batch CLI remains the authority for training and accepts
an explicit `--source postgres`; synthetic source remains explicit for test and
demo scripts only.

The existing workspace must not auto-load a local draft artifact in ordinary
development. `make dev-demo` remains the only deliberate path for loading a
synthetic artifact with governance disabled.

Development seed cases are retained only if marked `TEST_FIXTURE` and their
case identifiers/disclaimer make that provenance visible. They do not stand in
for confirmed operator history.

### Feature correctness

The case fingerprint derives operation shape from canonical
`partition_delta.before` and `partition_delta.after`: it computes removals,
created/removed chains, moved members, and split partitions from membership
deltas. It never reads non-contract fields such as `removed_alarms` or
`split_partitions`.

## Existing UI data truth

`ReviewLearningPanel` keeps its current layout but removes invented default
metrics and disables the synthetic retrain control with a provenance/readiness
reason. It shows the server-reported source/truth distribution and status.

`ChainScopeView` keeps its layout but uses explicit API evidence availability
for historical, temporal, topology, and dependency states. Its burst summary
uses the active backend threshold rather than an independent 60-second window.
Historical lift/confidence appears only when the matching historical evidence
is available; descriptor quality is not relabelled as historical confidence.

## Verification

Automated regression coverage must prove:

1. a threshold trial returns the same role counts as a direct configured engine
   analysis and does not mutate workspace configuration;
2. invalid apply returns an error without `APPLIED`;
3. keyword-only causal text remains unavailable without causal facts;
4. rejected candidates are absent from clarity comparison and reranking;
5. valid candidates retain deterministic ordering when no model is loaded;
6. synthetic artifact/case provenance is visible and ordinary dev does not
   auto-load it;
7. canonical deltas produce correct remove/split/move feature values; and
8. the existing UI layout tests, frontend build, backend suite, mock suite, and
   Compose configuration remain healthy.
