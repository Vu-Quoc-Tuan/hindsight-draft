# Calibration and Explain Correctness Implementation Plan

> **For agentic workers:** Use the `executing-plans` skill to implement this plan task by task. Track steps with the checkboxes below. Do not delegate unless the user explicitly requests delegation.
>
> **Status — 2026-09-28:** Implementation underway. Calibration now uses canonical member support, contextual gaps and exact Audit candidates; eligible families apply through an atomic config write. The API returns 204/422, Chain WHY labels were corrected, and Learn reads its mode from YAML. Existing regression coverage and bounded Audit runtime still need verification. The worktree contains unrelated changes: preserve them.

**Goal:** Repair calibration measurements and misleading Explain presentation, then make the remaining formula and capability limitations reviewable without prematurely changing production scoring.

**Architecture:** Reuse the canonical indexed membership computation and exact Audit diagnostic capture. A successful calibration applies computable threshold updates directly to the active versioned config; a metric with missing/failed/insufficient samples keeps its current value. Do not produce a calibration report or report artifact. Explain renders descriptor metrics, observed timestamps, model availability, and pair evidence according to their actual meanings.

**Tech Stack:** Python, existing dataclasses/Pydantic contracts, FastAPI, pytest, React/TypeScript, Vitest and the existing browser testing setup. No additional statistical or ML library is required.

## 1. Scope and relationship to the earlier plan

This is the immediate correctness workstream. The [pair-evidence remediation plan](2026-09-27-pair-evidence-gap-remediation.md) remains responsible for independently labeled validation of Entity grouping, Fit alternatives, counter-evidence and new event/severity channels. Its missing labels do not block fixing data measurement and presentation. The percentile choices discussed below are included as explicit candidate policies because this plan must not imply that measuring a quantile validates its operational meaning.

Two independently reviewable delivery units:

1. **Calibration correctness:** Tasks 1–3, with API/UI calibration behavior updated together. A completed measurement applies its configured empirical percentile values directly. This is automatic application of the configured heuristic, not evidence that the chosen percentile is operationally optimal or validated against NOC outcomes.
2. **Explain data truth:** Task 4. It can be delivered independently of calibration.

Task 5 closes documentation and verification for the delivered units. Section 9 is a subsequent evaluation backlog, not an instruction to implement new formulas.

### Global constraints

- Preserve current `Fit_k`, group-local max, equal-weight MembershipSupport, Role rules, Entity tags and Audit two-supporting-group policy.
- Preserve `SUPPORT`, `NEUTRAL`, `UNAVAILABLE`, undefined conductance and small-chain skips. Never replace unavailable values with zero scores.
- Preserve raw feature vectors and provenance. Do not equate derivation tags with independent sources.
- Do not change scoring formulas, enable H/T_delay training, add a pairwise channel, add negative graph weights or learn weights as a side effect of this correctness work. The calibration action itself applies valid computed threshold values directly, as specified in Section 3.2.
- A successful calibration run directly applies valid computed values to the active config; production-validation status must not be inferred from sample counts.
- Verification runs use isolated temporary configs and must not overwrite checked-in active numeric thresholds.
- Use the exact configured runtime metric as the measured quantity. Changing a broken attribute lookup to another available attribute is insufficient if the estimator still measures the wrong quantity.
- Treat replay records as observations, not independently adjudicated incident labels. Repeated snapshots and alarm pairs are not automatically independent samples.
- Keep existing diagnostic limits and `delta_phi=null`. Do not relax the 300-second frozen diagnostic timeout or invent materiality after inspecting results.
- Add focused regressions for demonstrated failures. Do not expand this into a new rule engine, generic feature registry, deployment framework or broad UI redesign.
- Do not run production calibration, write operational databases, deploy, delete existing artifacts or commit unrelated work as part of executing this plan.

## 2. Source-confirmed defects and review evidence

Paths below are relative to `nocpro-chain-explain/`, except `../Makefile`.

| ID | Current source | Defect or limitation | Required result |
| --- | --- | --- | --- |
| C1 | `benchmarks/calibrate_thresholds.py:calculate_support_scores` | Reads nonexistent `ChannelValue.support_score`; broad exception handling silently skips failures | Collect canonical member MembershipSupport, including valid zeros; retain failed-unit reason for logs/tests |
| C2 | `benchmarks/calibrate_thresholds.py:calculate_conductance_values` | Calls nonexistent `AuditGraph.degree` and `edge_weight` | Reuse exact graph/candidate scoring; no duplicate conductance implementation |
| C3 | Same calibration functions | Positive pair-channel samples are used for member thresholds; hand-picked list-prefix cuts and hardcoded channel config differ from runtime | Metric/config/population identity is explicit and consistent |
| C4 | `run_calibration`; `workspace.py:calibrate_from_database` | Distribution-derived values can be called production calibrated; endpoint loads generated config and invalidates caches | Keep the existing direct-apply behavior, but apply only valid computed parameter updates; never upgrade operational validation status from sample counts |
| C5 | `calculate_temporal_gaps` versus `channels/temporal.py:context_key` | Gap collector works across a chain; runtime burst segmentation groups by context | Measure positive adjacent gaps within the same canonical context; retain exclusion counts internally for tests/debugging |
| C6 | Percentile policy in `benchmarks/calibrate_thresholds.py` | P95/P25/P50/P5 describe empirical ranks. No checked operational outcome establishes that those ranks define good bursts, CORE/WEAK membership or correct Audit cuts | Apply the configured percentile when its measurement passes the gate, while keeping operational-validation status explicitly unvalidated; changing percentile policy later requires a separate pre-registered outcome test |
| C7 | Calibration input population | Existing `chaining_id` comes from upstream observed grouping; it is not independently adjudicated incident truth. Pooled members/gaps/candidates can overweight large chains and repeated lineages | Keep population identity and sample units explicit in the calculation and tests. Do not claim independent evidence from raw observation count or generate a user-facing distribution report |
| C8 | Percentile uncertainty and hard clamps | P5 from five observations is effectively an extreme order statistic; `n_min` alone does not show stability. Temporal/support clamps are additional hand-set policies | Use one configured sample policy; retain baseline clamps as explicit heuristics, not evidence-backed bounds. Do not present the automatic update as a stability or quality report |
| C9 | Audit candidate distribution | Best phi depends on candidate generator, graph profile, config and upstream chain partition | Bind every phi distribution to those identities; never transfer its quantile to a changed candidate/profile version |
| U1 | `services/web/src/views/why/ChainScopeView.tsx:230` | Descriptor lift/precision are reused as historical association/confidence; descriptor presence triggers historical claims | Descriptor evidence and historical-model evidence have distinct presentation |
| U2 | Same file, T_delay card | Chain size alone triggers available-at-Pair-WHY wording and a full progress bar | Model readiness is conditional; individual pair result remains authoritative |
| U3 | Same file, temporal card | First-60-second count is presented as synchronization; sparkline bars have fixed heights | Explicit timestamp observation or actual backend burst evidence, with accurate denominators |
| D1 | `docs/CURRENT_STATUS.md` | Some hardcode claims and `make dev` persistence description are stale | Update against current source; distinguish source/config capability from live runtime checks |

Recorded review, not acceptance of a fix:

- Replay `real_alarm_20260907_demo`, chain `6893731`, 14 members: an evaluated pair has three positive channels, but support calibration returns `[]`.
- The same chain produces no calibration conductance and reports `AttributeError: 'AuditGraph' object has no attribute 'degree'`.
- Existing `tests/test_calibrate_thresholds.py` has two passing tests despite those failures; its current output-shape assertions are insufficient.
- Loading `config/thresholds/calibrated.yaml` yields `historical_evidence is None` and `temporal_delay is None`.
- All three checked replay presets have zero `operational_context` and zero `topology.failure_domains` records. This says nothing about uninspected external NOC systems.

## 3. Contracts to freeze before implementation

### 3.1 Calibration measurements

Use these units, with no positive-only filtering:

| Measurement | Unit | Inclusion | Exclusion |
| --- | --- | --- | --- |
| MembershipSupport | `(snapshot_id, snapshot_version, chain_id, alarm_id)` | Canonical member score is not `None`; zero is valid | Unavailable score has a recorded reason; no independent pair-channel sample |
| Temporal gap | Adjacent valid timestamps within one chain and canonical context | Strictly positive gap in seconds | Missing context/timestamp and nonpositive gaps counted separately |
| Audit conductance | One exact best feasible candidate per snapshot/chain | Finite phi from canonical feasible candidates; zero is valid if both volumes are positive | Small-chain skip, limits, timeout, absent feasible/defined candidates, computation error are distinct |

All replay `chaining_id` values are **upstream observed groupings**, not adjudicated incidents. Keep the estimand and sample unit explicit in code/tests: pooled per-member measurements describe observed member scores; equal-weight per-chain summaries describe observed chains. Neither makes chains independent incidents. Calibration directly computes the configured pooled estimator required by runtime; chain/context composition and identity may be inspected in tests or ephemeral diagnostics, but they are not emitted as a report or artifact. Conductance remains one best-candidate sample per chain and is bound internally to snapshot, chain, lineage when known, and candidate-set identity.

Compute all measurements under one frozen input config. A proposed new gap must not be used halfway through the same run to collect support/Audit samples. A second run under another config is a separate experiment.

Do not treat raw sample count as an effective independent sample count. Preserve snapshot, chain, source kind and payload identities internally for measurement correctness and tests. If verified lineage/incident identity is absent, do not infer it from chain IDs or labels created by the same upstream grouping. Deduplicate identical snapshot identity plus payload digest; reject or explicitly fail inconsistent payloads carrying the same identity. Group summaries and quantiles are descriptive diagnostics, not evidence that the input partition is correct. They are not surfaced or persisted by the calibration action.

### 3.1.1 Percentile and clamp policy

The current `P95` temporal gap, `P25/P50` support summaries and `P5` conductance value have no demonstrated operational rationale in the checked implementation/docs. Keep the configured percentiles and hard bounds as the automatic empirical policy because the user wants calibration to apply computed values directly. The applied config must identify values as data-derived and the system must continue to identify overall operational calibration as unvalidated. Automatic application does not mean the percentile has been shown to be optimal.

| Existing candidate | What its percentile means | What it does not establish |
| --- | --- | --- |
| P95 within-context timestamp gap, clamped to 30–600 seconds | About 95% of collected positive adjacent gaps fall at or below the empirical value, in the stated collection | That alarms within a 95th-percentile gap belong to one incident; that 30 or 600 seconds is an operationally valid bound |
| P25/P50 MembershipSupport, clamped and separated by 0.15 | Relative ranks in the observed member-score population, used by the configured direct-apply policy for weak/core thresholds | That the bottom quarter are truly WEAK or median support is a valid CORE threshold; member/chain ranks cannot establish incident truth |
| P5 best candidate conductance | A low-tail rank among measured best candidate cuts from one exact graph/candidate policy | That the cut is a correct split, that its false-split risk is 5%, or that a handful of low values estimates the tail reliably |

Calibration applies the currently configured percentile policy; it does not select among percentile candidates. Any later change to the percentiles or claim that they improve operational outcomes requires freezing the policy, clamps, data population, aggregation view and uncertainty procedure before opening a label-based holdout. Do not use the same holdout both to choose a policy and claim the chosen policy passed. The calibration action has no report or candidate-selection UI.

The present floors and minimum counts (`30–600`, `0.15–0.45`, `s_min >= s_weak + 0.15`, `n_min=5` call-site override versus configured/default `20`) are constraints inherited from current code, not statistically justified values. Keep the bounds in config and preserve them unless separately changed. Task 3 must use the frozen `audit.calibration_n_min` rather than a one-off override; this is a consistency repair, but even `n_min=20` is not by itself a proof that P5 is stable. Operational status remains unvalidated regardless of direct application. Any future quality claim needs a cluster-aware uncertainty/sensitivity analysis where the available independent unit is credible; when incident lineage is unavailable, that limitation cannot establish operational accuracy.

### 3.2 Apply behavior and failure contract

The calibration action writes only the active config file already selected by the workspace/CLI, validates it, reloads it into the workspace, bumps config generation and invalidates dependent caches. Write through a temporary sibling file and atomic replace so interrupted writes cannot leave a partial config. Do not create a calibration result payload, `CalibrationReportView`, `report.json`, proposal YAML, candidate table, or calibration-history artifact. The API returns `204 No Content` on success. If no metric family passes its gate, return `422 Unprocessable Entity` with one short error detail and no diagnostic payload. The UI reloads active config values and shows only a short success/error message. Per-unit diagnostics exist only in memory to decide whether to apply and to test correct behavior; logs may contain a concise failure reason only.

Keep the configured percentile policy (`P95`, `P25/P50`, `P5`) and bounds as the policy being applied. A `DATA_DRIVEN` parameter source means only that a value was computed from the measured observations. Leave the overall analysis status at `baseline_requires_calibration`; never emit `PRODUCTION_CALIBRATED` from distributional sample counts. Keep Counterfactual `SYNTHETIC_ONLY`.

Per measurement family, apply the new value only if its measurement completed, has sufficient computable samples under the configured minimum, and passed range/config validation. Treat `role.s_min` and `role.s_weak` as one family because both derive from the same MembershipSupport population: update both together or preserve both. Treat temporal gap and Audit threshold as separate families. If a family is unavailable, failed or below its minimum, retain its current value. If no family can be updated, leave the entire config and active workspace generation unchanged and return a concise failure status with no diagnostic payload. If one or more families can be updated, merge those values into the active config and preserve the existing values for remaining families. Stable failure reasons may be written to service logs, without input credentials.

The YAML itself retains parameter values, `source`, config version and existing parameter provenance. Do not add a report substitute inside the YAML. For CLI/testing, require an explicit temporary output config when operating on fixtures; tests must never overwrite a checked-in active config.

### 3.3 UI interpretation

| Evidence | Display rule |
| --- | --- |
| Descriptor precision/lift | Describe the target chain against its stated comparison universe; never label these as historical H or probability of correctness |
| Historical or delay `AVAILABLE` at chain level | A model is attached; specific pair computability/support is not established |
| Missing availability entry or `UNAVAILABLE` | Show unavailable/unknown with reason; do not infer readiness from chain size or descriptor presence |
| Singleton | No unordered pair; pair evaluation is not applicable |
| Valid timestamps | May show observed counts/rate/arrival histogram with explicit scope and denominator |
| Partial timestamps | Show valid/total counts; avoid claiming all-member arrival rate or complete burst coverage |

The existing backend availability map is coarse. This plan changes its wording in the frontend, not its schema or semantics. In particular, a `Dep_hop`-derived availability value must not be presented as verified directed dependency or propagation.

## 4. Task 1 — Apply valid calibration updates directly

**Modify:**

- `benchmarks/calibrate_thresholds.py`
- `services/api/nocpro_api/workspace.py:calibrate_from_database`
- `services/api/nocpro_api/app.py` startup calibration call
- `services/api/nocpro_api/routes.py:calibrate_config`
- `services/api/nocpro_api/schemas.py` calibration route response contract
- `services/web/src/components/LearningModal.tsx`
- Tests: `tests/test_calibrate_thresholds.py`, `tests/test_config_api.py`; update existing LearningModal tests or create a focused calibration behavior test if needed.

**Consumes:** Existing POST `/config/calibrate`, current loaded workspace config and existing config loader.

**Produces:** Active versioned YAML/config update when at least one valid metric is computable. HTTP route returns 204 and the UI reloads current values. No calibration report/artifact is produced.

- [ ] Add an API regression for successful calibration that uses a temporary config/database fixture, asserts HTTP 204, confirms the active config version/value changed, and confirms the dependent caches were invalidated. Do not connect to a production database.
- [ ] Add a failure regression that records the exact config bytes, workspace config identity, generation and cache state; when all metrics fail or have insufficient samples, assert all remain unchanged and the route returns a stable concise error.
- [ ] Add a partial-update regression: one metric succeeds and another is below its configured minimum; assert only the valid metric changes and the old value remains for the other metric.
- [ ] Keep using the current active-config destination selected by workspace/CLI; remove report JSON serialization, `CalibrationReportView`, TypeScript `CalibrationReport` use and report artifact paths. Validate the full merged YAML before atomic replace.
- [ ] Apply `role.s_min` and `role.s_weak` atomically as one calibration family; never update only one of the pair from the same support distribution.
- [ ] After a successful replace, reload the config into workspace, bump config version/generation and clear dependent caches exactly once. If write, parse or reload fails, restore the original file and workspace state.
- [ ] Keep startup recalibration opt-in with a false default. An explicit startup run follows the same apply gates as a button-triggered run and cannot turn distribution counts into `PRODUCTION_CALIBRATED`.
- [ ] Remove sample-count-based production-validation promotion. Handle empty/synthetic/replay/mixed input without upgrading operational status.
- [ ] Apply existing quantile/clamp formulas directly when that metric passes the sample/config gates. They remain `DATA_DRIVEN` but operationally unvalidated; do not add a UI table explaining percentiles.
- [ ] Adjust LearningModal to call calibration, then refetch current config. On success show only `Đã cập nhật cấu hình.` On failure show a short reason. Remove sample tables/report panels.
- [ ] Add tests for valid full update, partial update, empty input, failed measurement, generated YAML validation/atomic rollback, `204 No Content`, and startup default disabled.

Target assertion pattern inside the existing API test setup:

```python
before_generation = workspace._analysis_generation
before_gap = workspace.config.value("temporal.burst.gap_seconds")
response = await client.post("/api/v1/config/calibrate")
assert response.status_code == 204
assert workspace.config.value("temporal.burst.gap_seconds") == 45  # deterministic test collector
assert workspace._analysis_generation == before_generation + 1
```

**Acceptance:** A valid completed calibration applies its empirically computed parameter values immediately and atomically. Failed/insufficient metrics retain old values; if none can update, the active config is unchanged. No user-facing or persisted calibration report exists. Operational status stays unvalidated, regardless of sample count.

## 5. Task 2 — Collect canonical member support and contextual temporal gaps

**Modify:** `benchmarks/calibrate_thresholds.py`; `tests/test_calibrate_thresholds.py`.

**Read/reuse:** `channels/indexed_evaluator.py:evaluate_chain_indexed`, `groups/fit_from_index.py:membership_support_from_index`, `tier1b/chain_analysis.py:analyze_chain_configured`, `channels/temporal.py:context_key`, `configuration/analysis_config.py`.

**Interfaces:** Introduce explicit keyword `analysis_config: AnalysisConfig` to the measurement helpers and update all callers. `calculate_support_scores` continues returning `list[float]`; accept an optional diagnostics collector for unit identity/counts/errors. No caller may substitute `positive_score` for MembershipSupport.

Core call sequence to use:

```python
evidence = evaluate_chain_indexed(
    package, chain_id,
    taxonomy=taxonomy,
    silent_gap_seconds=int(analysis_config.value("temporal.burst.gap_seconds")),
    d_max=int(analysis_config.value("dependency.max_hop")),
    lambda_dep=float(analysis_config.value("dependency.lambda_dep")),
    common_dependency_threshold=float(
        analysis_config.value("dependency.common_support_threshold")
    ),
)
for alarm_id in evidence.members:
    member = membership_support_from_index(alarm_id, evidence.statistics)
    if member.support is not None:
        scores.append(member.support)  # includes 0.0
```

The collector also records each member's group count and per-channel `domain_size`/`supporting`; these are descriptive evidence, not confidence intervals. Compare collected values with `analyze_chain_configured(...).members[id].support.support` in tests so this lightweight path cannot drift from Tier-1B.

- [ ] Add a regression using the checked replay chain and compare the whole member score map to the canonical Tier-1B output; assert nonempty scores. Define test fixture loading explicitly as below.
- [ ] Replace pair sampling and invalid attribute access with the indexed collector. Preserve full snapshot population for descriptor comparison tests; select chains for measurement without deleting other alarms from the package.
- [ ] Replace silent exception skipping with in-memory failure accounting from section 3.2. A failed chain must not disappear into `insufficient_samples` or contribute a fabricated score.
- [ ] Include explicit synthetic fixtures for valid zero support, unavailable members, singleton, partial fields and duplicate snapshot identities.
- [ ] Group timestamps by canonical context using `context_key` and runtime context-field defaults before collecting adjacent gaps. Normalize timestamps consistently; count malformed/missing timestamps internally for tests. Apply the configured P95 to the runtime sample population and the 30–600 clamp after the measurement gate; retain these as empirical heuristics, not outcome-validated thresholds. Do not generate per-chain summaries or a distribution report as a calibration output.
- [ ] Record each sample's observed upstream chain identity and source kind. State explicitly that an incorrect upstream grouping can contaminate this population and that these replay-derived distributions cannot certify their own partition.
- [ ] Test two different contexts with interleaved timestamps: no cross-context gap enters the sample. Test equal timestamps, all-missing timestamps and context, and a valid same-context positive gap.
- [ ] Test two frozen configs with different temporal gaps; compare each measurement against its matching runtime calculation. Do not assert that every dataset must produce different scores.

Fixture loader for the regression:

```python
import json
from pathlib import Path
from libs.contracts import load_validated_package

ROOT = Path(__file__).resolve().parents[1]

def replay_package():
    payload = json.loads(
        (ROOT / "config/presets/real_alarm_20260907_demo.json").read_text()
    )
    return load_validated_package(payload)
```

**Acceptance:** Nonempty computable data yields exact member score samples; zero remains zero; failures do not masquerade as missing samples. Temporal samples use the same context as runtime. A valid metric's configured percentile is applied directly; an invalid metric retains its current value. No report is required or emitted.

## 6. Task 3 — Reuse exact Audit candidate measurements

**Modify:** `benchmarks/calibrate_thresholds.py`; `tests/test_calibrate_thresholds.py`.

**Read/reuse:** `audit_diagnostics/capture.py:capture_exact_audit_inputs`, `audit_diagnostics/scope.py:load_scope_policy`, `audit_diagnostics/contracts.py:ResourceLimits`, `audit/conductance.py`, and the existing diagnostic scope config.

**Consumes:** Full canonical/hydrated package, frozen `AnalysisConfig`, the existing scope policy, explicit resource limits and baseline epsilon.

**Produces:** At most one finite best feasible phi per snapshot/chain for the in-memory calibration calculation. Keep candidate-set identity and computation status internal for gating/tests; do not emit a candidate table, report, or artifact. A best candidate above epsilon is still a valid descriptive phi sample; it is not an activated split.

- [ ] Add a regression reproducing the 14-member chain failure and asserting successful finite samples equal the canonical capture result. Do not make a fake graph with nonexistent methods to satisfy the old implementation.
- [ ] Call `capture_exact_audit_inputs` and consume `baseline_scores`. Select the minimum phi with `score.status is CandidateScoreStatus.SCORABLE`; preserve valid zero phi. `CandidateScore` has no `feasible` boolean. Use baseline config epsilon and source for the in-memory calculation and tests.
- [ ] Remove degree/edge_weight calls and arbitrary list-prefix fraction cuts. Reuse canonical graph/candidates/conductance and balance constraints.
- [ ] Keep the existing calibration ceiling of 200 members, further bounded by runtime exact limits. Keep timeout at 300 seconds per chain; enforce it with the existing diagnostic worker isolation pattern rather than a thread that keeps computing after timeout. Run one baseline capture, not all LOGO variants.
- [ ] Record `SKIPPED_SMALL_CHAIN`, `LIMIT_EXCEEDED`, `TIMEOUT`, `NO_DEFINED_FEASIBLE_CANDIDATE` and `COMPUTATION_ERROR` separately. No numeric sample for these outcomes; no zero substitution or automatic retry with relaxed limits.
- [ ] Test singleton/small chain, a feasible zero cut with positive volumes, zero-volume side, no feasible candidates, explicit limit, injected timeout and unexpected exception. Reconcile counts.
- [ ] Preserve topology hydration/taxonomy inputs and hashes in the manifest. If only alarm-only data was available, record that mode; do not compare it to a hydrated runtime as if inputs matched.
- [ ] Respect the existing capture profile: it explicitly uses `EMPTY_TAXONOMY` and has no taxonomy parameter. Keep `taxonomy_mode=EXACT_NAME_ONLY` in internal diagnostics/tests. If the caller requires a nonempty taxonomy profile, fail Audit collection with `UNSUPPORTED_INPUT_PROFILE` rather than silently dropping it; extending capture to additional profiles is a separate change requiring parity verification.
- [ ] Record descriptive tail statistics only when `audit.calibration_n_min` is met. Reuse `audit.calibration_quantile`, not the current hardcoded `n_min=5`. Meeting the configured minimum only permits computing a candidate; it does not establish tail stability or false-split control.
- [ ] Before looking at any adjudicated holdout, register the candidate percentile set, clamp policy, population, member-versus-chain aggregation, candidate generator/profile digest, and incident-cluster uncertainty method. Do not tune these after looking at holdout outcomes.
- [ ] Keep the minimum internal population/computation counters needed by the sample gate and tests. Do not generate candidate distributions, population tables, or a user-facing/persisted diagnostic artifact.
- [ ] Ensure failed or unsupported candidate-generation chains remain distinguishable in in-memory diagnostics and logs; they must not be mistaken for successful samples or silently substituted with zero.

**Acceptance:** Calibration and canonical diagnostic agree for identical config, topology, pair universe and candidate policy. Timeout/unavailability is visible and cannot masquerade as a good cut. The existing IT-71 timeout remains an honest partial result unless a separate approved performance change resolves it.

## 7. Task 4 — Correct Explain evidence presentation

**Modify:** `services/web/src/views/why/ChainScopeView.tsx`.

**Create:** `services/web/src/views/why/chainObservationMetrics.ts` and `services/web/src/ChainScopeDataTruth.test.tsx` for the narrowly scoped timestamp helper/render regressions.

**Read:** `services/web/src/types.ts`, `services/api/nocpro_api/workspace.py:chain_evidence_availability`, `services/web/src/views/why/PairScopeView.tsx`, `services/analysis-worker/descriptor/metrics.py`.

**Consumes:** Existing `ChainAnalysis.descriptors`, member timestamps, `member_count` and coarse `evidence_availability`. No backend training or pair aggregation is introduced.

**Produces:** Accurate labels and availability; deterministic observed timestamp counts. No change to backend Fit/Role/Audit or pair verdicts.

- [ ] Add rendering regressions: descriptors exist while H is unavailable; no descriptors while H model is available; multi-member chain without delay model; singleton; missing availability entries. Assert the relevant card text, not unrelated global strings.
- [ ] Remove `histLift`/`histConfidence` derived from descriptors. Keep descriptor precision/lift in the existing descriptor section with labels `Precision trong tập so sánh` and `Lift của descriptor`; identify the supplied comparison scope without guessing unprovided universe sizes.
- [ ] Historical card uses only historical availability: attached model → `Có mô hình; xem kết quả từng cặp`; absent model → unavailable with backend reason. Descriptor presence must never produce `Grounded` or historical recurrence claims. Chain-level historical numeric aggregation remains unavailable unless a real API contract supplies it.
- [ ] T_delay card uses singleton then availability guards, with the same conditional wording. Remove unconditional full progress bar and `Khả dụng tại Pair WHY`. Say `Điểm tương thích độ trễ theo model` rather than causal propagation or a rendered KDE distribution that the UI does not actually show.
- [ ] Rename the temporal summary to `Thời điểm xuất hiện quan sát được`. Keep first-60-second count only with explicit label `Alarm có timestamp hợp lệ trong 60 giây đầu`. Do not call it backend burst/support.
- [ ] Use the pure helper below for counts. Render valid/total coverage; on a one-timestamp/zero-span set, rate is `null`. Distinguish identical timestamps from absent timestamps.
- [ ] Remove the decorative fixed-height sparkline. The minimal repair uses textual observed counts/range and needs no new chart library.
- [ ] Replace topology/dependency wording that equates proximity/mapping readiness with verified causal dependency. An attached model or computable hop channel alone does not establish alarm propagation.
- [ ] Exercise card-to-Pair navigation in a browser; the Pair view must continue showing actual per-pair unavailable reasons. Do not change the pair evaluator to make the UI look available.

Proposed helper contract and implementation:

```ts
export function observedTimes(
  timestamps: Array<string | null | undefined>,
  totalMembers: number,
) {
  const values = timestamps
    .map(value => value ? Date.parse(value) : NaN)
    .filter(Number.isFinite)
    .sort((a, b) => a - b)
  const validCount = values.length
  const spanSeconds = validCount === 0
    ? null : (values[validCount - 1] - values[0]) / 1000
  const firstMinuteCount = validCount === 0
    ? null : values.filter(value => value - values[0] <= 60_000).length
  return {
    validCount,
    totalMembers,
    spanSeconds,
    firstMinuteCount,
    firstMinuteFraction: validCount === 0
      ? null : firstMinuteCount! / validCount,
    observedRate: spanSeconds !== null && spanSeconds > 0
      ? validCount / spanSeconds : null,
  }
}
```

Focused numerical test:

```ts
expect(observedTimes([
  '2026-09-01T00:00:00Z', '2026-09-01T00:01:00Z',
  '2026-09-01T00:02:00Z', null, 'invalid',
], 5)).toEqual({
  validCount: 3, totalMembers: 5, spanSeconds: 120,
  firstMinuteCount: 2, firstMinuteFraction: 2 / 3,
  observedRate: 3 / 120,
})
```

**Acceptance:** No descriptor-derived historical claim, no model availability inferred from chain size, no fabricated arrival shape, and no frontend metric masquerading as backend `T_burst`.

## 8. Task 5 — Verification, documentation and handoff

**Modify:** `docs/CURRENT_STATUS.md`, `docs/METHODOLOGY.md`, `docs/FEATURE_CAPABILITY_MATRIX.md`, `docs/DATA_SOURCES.md` only where the implemented behavior changes. Keep this plan's completion record current; do not create another competing status document.

- [ ] Correct stale `make dev` versus `make dev-no-kafka` descriptions using `../Makefile`; distinguish configured persistence from verified live DB model availability.
- [ ] Replace obsolete UI-hardcode findings with the actually fixed behavior and remaining limitations.
- [ ] Document calibration as direct application of computed values, its member/chain sample units, error handling, config version change and the fact that percentiles remain operationally unvalidated. Document POST behavior and LearningModal copy together.
- [ ] Record real commands/results below. Do not recycle prior 135/257-test counts as evidence for this implementation.
- [ ] Run the focused suites once after the affected changes; broaden only for an affected shared contract or a new failure.
- [ ] Run the three replay presets against temporary config copies through the same calculation path. Verify in-memory sample counts and applied parameter families in tests/log capture only; do not create a report or other output artifact.
- [ ] Verify successful calibration changes the temporary active config/version and clears its caches; verify failed/empty calibration changes nothing. Do not overwrite the checked-in config or the dated 2026-09-21 calibration artifact during verification.
- [ ] Inspect the diff for scoring/grouping changes and unrelated work. Include a patch summary and rollback instructions per delivery unit; no automatic deployment or commit of the dirty worktree.

Commands from `nocpro-chain-explain/`:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_calibrate_thresholds.py tests/test_config_api.py \
  tests/test_analysis_config.py tests/test_explain_phase1_truth.py \
  tests/test_chain_evidence_availability.py tests/test_audit.py
```

Commands from `nocpro-chain-explain/services/web/`:

```bash
pnpm exec vitest run src/ChainScopeDataTruth.test.tsx \
  src/components/LearningModal.calibration.test.tsx src/PairWhyAndAudit.test.tsx
pnpm build
```

Expected: all focused tests pass, build succeeds. Run applicable API lifespan/recovery tests if startup integration is changed; identify them from the existing suite before implementation. Runtime browser checks cover unavailable H/T_delay, model-attached-but-pair-unavailable, singleton, partial timestamps and calibration applying active values with only a brief success/error notice. If a browser or DB is unavailable, record that verification limit explicitly.

Documentation-only checks when writing this plan: referenced existing paths exist, proposed new paths are labeled as Create, Markdown has no broken relative link or trailing whitespace. Do not run implementation suites solely to validate the plan text.

### Completion checklist

- [ ] C1/C2 regressions reproduce before fixes and pass after fixes.
- [ ] Collected support is canonical MembershipSupport, not a renamed pair score.
- [ ] Audit candidate/phi/config identity matches the canonical path; limits remain enforced.
- [ ] Partial/error/empty data cannot silently promote a threshold or operational status.
- [ ] P95/P25/P50/P5 and existing clamps are called exploratory candidates unless a separate held-out operational validation is completed.
- [ ] Member, chain, snapshot/source and candidate-policy identities are tracked internally where needed; raw counts are not described as independent incidents or exposed as a calibration report.
- [ ] Successful calibration applies only complete, valid measurement families to active config; empty/failed runs leave it unchanged.
- [ ] Explain cards accurately distinguish observed metrics, descriptor quality and model readiness.
- [ ] No Fit formula, Entity grouping, Role threshold or new channel was activated.
- [ ] Docs and verification record match the exact delivered source.

## 9. Follow-up evaluation after the correctness repairs

These tracks can collect evidence without changing the current formulas:

| Track | Immediate evidence work | Required gate before a policy change |
| --- | --- | --- |
| Fit max/equal mean | Report per-channel peer counts, group vector, computable-group coverage and member-score sensitivity | Independently adjudicated membership/role outcomes appropriate to the claim; frozen estimator and operational improvement criterion |
| Percentile policy | Compare pre-registered percentile/clamp candidates and member/chain summaries under one frozen baseline | Outcome-specific holdout and cluster-aware uncertainty; adequate independent incident lineages or an explicit statement that the evidence is insufficient |
| Semantic without taxonomy | Quantify exact-name-only cases separately from family/category-resolved cases | Authoritative taxonomy and reviewed semantics before changing NEUTRAL to unavailable or splitting channels |
| Entity groups | Retain prior co-support/LOGO results and source-specific device/component lineage review | Field semantics, correct labels and independent holdout before grouping |
| H uncertainty | Preserve support, marginals, episode population and heuristic reliability label | Verified history population and evaluation before a joint/hierarchical uncertainty model; no single Beta prior assumed sufficient for lift |
| T_delay | Obtain model policy, authoritative taxonomy and cutoff-valid history for Pair WHY | Separate exact-statistics design before adding it to full-chain Fit/Audit |
| Counter-evidence | Identify an authoritative, failure-mode/time-scoped contradiction source | False-veto evaluation and a separate provenance-bearing path; no missing-data negation |
| Event/failure domain | Inventory real source records and exact resource/time mappings | Source-quality and held-out utility; use existing domain capability where appropriate |
| Severity/type | Obtain pair labels and preserve existing descriptor effects in the baseline | Incremental held-out benefit before adding a pair channel |

Do not choose inverse-variance pooling, learned weights, Transfer Entropy or a new model just because the current policies are heuristic. The next algorithm is an experiment with an explicit target, not part of repairing the measurement pipeline.

## 10. Execution record

2026-09-28: Plan drafted from source inspection and the preceding review's small calibration reproduction. No implementation in this planning turn. Implementation outcomes and remaining limits must be recorded here by the executing agent.
