# Pair Evidence Gap Validation and Remediation Plan

> **Execution status (2026-09-27):** The repository owner authorized evidence-supported fixes. This work fixed two demonstrated Audit/diagnostic implementation defects and aligned source comments/docs. Changes that alter Fit/Role scoring, Entity grouping, add counter-evidence, or add event/severity features remain gated by the data and label requirements below.

> **Immediate correctness workstream (planned 2026-09-28):** See [Calibration and Explain Correctness](2026-09-28-calibration-explain-correctness.md) for confirmed calibration measurement defects, proposal-only calibration and Explain presentation repairs. Those repairs do not require new NOC labels. This document continues to govern scoring/grouping/new-channel validation; the linked plan does not mark those gates complete.

> **Topology status update (2026-09-28):** The former `DepUpstream*` pairwise providers and Tier-2 directed-topology hypotheses referenced in this review were removed from runtime after the checked real replay inputs returned `UNAVAILABLE`. This supersedes the preservation action below for those capabilities. See [Deferred Directed Topology](../DEFERRED_DIRECTED_TOPOLOGY.md) for the evidence, removed surface, and restoration gates. Other scoring, grouping, labeling, and governance gates in this plan remain open.

**Goal:** Determine which observed pair-evidence risks cause material Audit or membership errors, then fix only the gaps supported by operational data and pre-registered evaluation.

**Architecture:** Preserve the current channel evaluator, derivation grouping, and Audit graph as the versioned baseline. Evaluate each proposed change offline against pinned snapshots and label types with separate meanings; add a runtime feature only after its data source, evidence semantics, eligibility, and operational benefit have been verified.

**Tech Stack:** Python analysis worker, Contract v1 records, existing offline Audit diagnostic, JSON snapshots/manifests, pytest.

## Global Constraints

- This plan authorizes only the explicitly recorded defect fixes and documentation corrections. It does not authorize changing the Fit/Role formula, Audit support policy, channel grouping, API/schema, thresholds, or deploying new evidence capabilities without passing their data/label gates.
- Keep raw channel values and provenance visible; do not infer independence from distinct derivation tags.
- Keep `H`, `H_domain`, pairwise `K_pair`, upstream `M_pair` facts, and Counterfactual external-validation artifacts as separate evidence paths.
- Preserve `UNAVAILABLE`, `NEUTRAL`, and explicit contradiction as different meanings. Missing data never counts as negative evidence.
- Keep the positive Audit graph nonnegative. Any future counter-evidence must be carried as a separate, explicit Audit evidence line unless a separately reviewed design proves another treatment is valid.
- Do not claim alarm-to-alarm causality or propagation direction from shared directed topology context.
- Synthetic fixtures validate contracts and arithmetic only. They do not establish production data coverage or operational benefit.
- Keep the existing Audit diagnostic baseline and its frozen scope/materiality rules. Do not choose `delta_phi`, `Delta_min`, or a quality threshold after inspecting test results.
- Any further scoring, grouping, schema, or channel behavior change must pass its evidence gate and receive implementation authorization; a diagnostic sensitivity result alone is not production acceptance.

---

## 1. Review outcome from the current checkout

| Area | What source confirms | Current assessment | Planned action |
| --- | --- | --- | --- |
| Entity derivation groups | Five channels have distinct tags; `POST_HOC` is audit-eligible; Audit creates an edge when at least two available audit-eligible groups support | A real design risk exists: two correlated fields can satisfy the two-group rule. This is not proof that the rule has produced a false operational conclusion | Measure edge and candidate sensitivity on pinned data; do not merge channels by assumption |
| Directed topology providers | Historically, upstream ancestry required directed `LOGICAL_DEPENDENCY`; active paths were ordered inputs | Checked real replay inputs lacked those records; no algorithm defect was established | Removed from runtime and deferred pending the documented real-data gates |
| `H` and `H_domain` | `H` is included only in explicit Pair WHY; `H_domain` is a set-valued membership/candidate capability | No pairwise Role/Audit defect found. Checked real replay snapshots do not establish operational failure-domain coverage | Keep paths separate; validate real domain source mapping before any data-integration work |
| Pairwise counter-evidence | `ChannelValue` has only SUPPORT/NEUTRAL/UNAVAILABLE states; `negative_score` does not create a negative verdict. Tier-2 has an optional `cross_block_negative_evidence` boolean defaulting to false, with no internal producer found | Confirmed capability gap; whether it is a product defect depends on an authoritative, eligible source of pair contradiction | Define source and semantics first; then add an explicit, provenance-bearing contradiction path if justified |
| Shared change/maintenance event | Contract v1 has `operational_context`; the Mock can generate synthetic records; the pair evaluator has no consumer. The three checked 500-alarm replay presets have no operational-context records | Confirmed pairwise coverage gap in this checkout, but there is no real data with which to implement or evaluate it | Obtain/validate a real source and record mapping before writing a channel |
| Severity/alarm type | These fields are descriptor predicates. IDENTITY representativeness affects CORE classification and descriptor separation can generate Audit candidates. They are not compared by `S` | No pairwise compatibility feature exists, but current indirect use means this is not a “narrative only” omission. A new pair feature is not yet proven necessary | Test incremental value and interaction with descriptors before adding a channel |
| Existing review labels | `review-label-v1` labels Counterfactual candidate relevance, including approve/reject/truth-tier handling | These labels are not automatically labels for “pair related”, “same incident”, or “proposed split correct” | Define and validate label types before model comparison or feature promotion |

### 1.1 Entity overlap observed in the checked replay fixtures

An exploratory read of all unordered within-chain pairs in the three 500-alarm `REAL_EXPORT_REPLAY` presets found overlapping equality support:

| Preset | Pair subset where both fields were available | Both fields equal |
| --- | ---: | ---: |
| `real_alarm_ip_demo` | 1,008 pairs for device/site | 492 (48.8%) |
| `real_alarm_it_demo` | 4,410 pairs for device/site | 979 (22.2%) |
| `real_alarm_20260907_demo` | 709 pairs for reference/site | 513 (72.4%) |

These are descriptive counts from replay fixtures whose chain membership is not an independently adjudicated pair label. They show that co-support occurs and can cross the current two-group threshold; they do **not** show statistical dependence, false Audit edges, or incorrect incident decisions. Source does not prove that device/card/site are nested or that reference belongs to that scale. Keep `E_remote` separate because it is a relation.

### 1.2 Source facts to retain

- `services/analysis-worker/channels/entity.py`: `E_reference`, `E_device`, `E_card`, `E_site`, and `E_remote` have separate derivation tags.
- `libs/provenance/eligibility.py` and `libs/provenance/derivation.py`: baseline `POST_HOC` channels are audit-eligible; effective grouping also includes provenance and eligibility.
- `services/analysis-worker/audit/graph.py`: an edge requires at least two supporting audit-eligible groups; its weight is positive support sum divided by available audit-eligible groups.
- `services/analysis-worker/channels/evaluator.py`: `_evaluate_pair` supplies the normal channels; `H` is added only under `include_historical=True` in explicit Pair WHY.
- `services/analysis-worker/groups/fit.py` and `groups/fit_from_index.py`: `Fit_k = supporting / domain_size`; `Fit_g` is the unweighted maximum of computable channel fits within an effective group; `MembershipSupport` is the unweighted arithmetic mean across computable role-eligible groups. `domain_size` does not weight the inter-group mean and there is no small-sample uncertainty adjustment.
- Historical provider implementation: available in Git before the removal; do not restore without the gates in [Deferred Directed Topology](../DEFERRED_DIRECTED_TOPOLOGY.md).
- `services/analysis-worker/channels/failure_domain.py` and `services/analysis-worker/audit/candidates.py`: failure domains are set-valued membership/candidate inputs; they must not be expanded into pairwise clique votes.
- `contracts/v1/models.py` and `libs/contracts/loader.py`: operational-context records are typed and loaded, but no pair evaluator consumes them.
- `services/analysis-worker/descriptor/predicates.py`, `descriptor/representativeness.py`, `tier1b/chain_analysis.py`, and `tier2/audit_analysis.py`: severity/type descriptors can influence role/candidate paths indirectly.
- `services/analysis-worker/review_learning/labels.py` and `review_learning/materializer.py`: current review labels are candidate-ranking labels and exclude unreviewed candidates; they cannot stand in for pair or incident truth without an explicit mapping study.

## 2. Files and artifacts

| Path | Purpose in this plan |
| --- | --- |
| `docs/audit-diagnostics.md` | Active Audit coverage/LOGO/materiality diagnostic guide; reuse its baseline and manifest requirements |
| `services/analysis-worker/audit_diagnostics/` | Existing offline diagnostic; first use it as an analysis tool, without changing production Role/Audit paths |
| `config/presets/real_alarm_ip_demo.json`, `real_alarm_it_demo.json`, `real_alarm_20260907_demo.json` | Replay inputs already inspected; not operational ground truth |
| `services/analysis-worker/channels/entity.py`, `libs/provenance/derivation.py`, `services/analysis-worker/audit/graph.py` | Entity grouping and Audit behavior under review |
| `services/analysis-worker/channels/base.py`, `channels/evaluator.py`, `audit/verdict.py`, `tier2/audit_analysis.py`, `tier2/jobs.py` | Potential future explicit pair contradiction path and its Audit consumer |
| `contracts/v1/models.py`, `libs/contracts/loader.py`, `nocpro-mock/src/nocpro_mock/scenarios/context_generator.py`, `channels/failure_domain.py` | Existing context/domain data contract, synthetic source, and set-valued capability |
| `services/analysis-worker/descriptor/predicates.py`, `descriptor/representativeness.py`, `tier1b/chain_analysis.py`, `tier2/audit_analysis.py`, `channels/semantic.py` | Existing severity/type descriptor and semantic boundaries |
| `tests/test_audit.py`, `tests/test_fit_and_roles.py`, `tests/test_failure_domains.py`, `tests/test_descriptors.py`, `tests/test_graybox_pair_metadata.py`, `tests/test_contract_parsing.py`, `tests/test_tier2_audit.py` | Existing focused regression tests inspected for this review; directed-topology-only tests were removed with those runtime modules |

## 3. Work plan

### Task 1 — Freeze evaluation data and label meanings

**Files/artifacts:**

- Read: `docs/audit-diagnostics.md`, `config/audit_diagnostics/`, and the three replay presets above.
- Read: `services/analysis-worker/review_learning/labels.py`, `review_learning/contracts.py`, and `review_learning/materializer.py`.
- Create outside the source tree or in an approved evaluation-data location: a versioned evaluation manifest and a label dictionary. Do not store private operational labels in a public fixture.

#### Label-to-gate matrix and checked-repository status (2026-09-27)

| Evaluation question | Required label or source record | Gates it can support | Checked repository status |
| --- | --- | --- | --- |
| Are two alarms related? | Independently adjudicated unordered-pair related/unrelated label, with source and truth tier | Pairwise severity/type ablation; validation of pair counter-evidence false-veto rate | No checked-in pair-label dataset found. `review-label-v1` is candidate-ranking relevance, not pair truth. External NOC stores were not inspected. |
| Does an alarm belong to an incident? | Alarm-to-incident membership from an independently reviewed incident record | Fit membership behavior; Entity grouping consequences; event/failure-domain benefit | Replay `chaining_id` is observed input grouping, not an independent adjudication. No checked-in adjudicated membership set found. |
| Is a member role correct? | Per-alarm adjudicated role or a validated operational outcome tied to the role question | CORE/PERIPHERAL/WEAK impact of changing Fit aggregation | No checked-in role-label set found. Same-incident membership alone does not establish CORE or another role. |
| Was an Audit split/merge proposal useful or correct? | Reviewed proposal outcome with proposal identity, decision reason, reviewer source, and truth tier; independent incident/pair truth for correctness claims | Audit review utility; downstream effect of Entity or severity/type changes | No checked-in Audit proposal outcome set found. Accept/reject alone is reviewer outcome, not necessarily objective split truth. |
| Is there affirmative pair counter-evidence? | Authoritative assertion that the resources are independent for a specified failure mode and validity interval, plus adjudicated pairs to measure false vetoes | `K_pair` source gate and offline harm/benefit evaluation | No trusted producer or real records found in the checked repository. External source systems were not inspected. |
| Is operational context/failure-domain evidence usable? | Authoritative event/domain records, resource mapping, valid-time, provenance, quality, and correction history | Task 3 source readiness; later held-out feature evaluation | Contracts and synthetic generation exist; all three checked real replay fixtures have zero operational-context and zero failure-domain records. This does not establish source-wide absence. |

Only the label policy/contract for Counterfactual candidate ranking is present in source; this inspection did not inventory external databases or private NOC adjudications. Therefore the supervised gates remain blocked until an authorized label source is inventoried. Continue with descriptive analyses only in the meantime.

The two materiality thresholds are also still open: `delta_phi` is `null` in the diagnostic config, and no numeric `Delta_min` has been pre-registered. `delta_phi` governs whether an Audit candidate change is operationally material; `Delta_min` governs minimum held-out benefit for a proposed feature or aggregator. Define each from its corresponding reviewer/operational action before examining held-out results; do not substitute one for the other.

- [ ] Freeze one baseline run per available snapshot with the existing diagnostic. Pin source bundle, dirty-worktree state, snapshot hash, chain/member fingerprint, effective-group registry, scope policy, candidate set, and materiality policy.
- [ ] Build a label inventory that separates: (a) pair judged related/unrelated, (b) alarms belonging to the same incident, and (c) a reviewed Audit/Counterfactual proposal accepted/rejected. Record the adjudication source and truth tier for each label.
- [ ] Exclude unreviewed, deferred, or insufficient-evidence cases from negative labels. Do not translate `review-label-v1` proposal relevance into pair labels.
- [ ] Split by time and incident/lineage, not by individual pair. Keep all pairs from one incident lineage in one split. Remove chain ID, post-review fields, labels, proposal status, and other downstream decision metadata from model inputs.
- [ ] Pre-register the minimum operational effect `Delta_min`, statistical uncertainty method, and any multiple-comparison handling before opening the held-out results. Use incident-cluster resampling for uncertainty; individual alarm pairs are not independent observations.

**Gate:** If there is no independently adjudicated pair/incident label set or no documented Audit review outcome, continue only with descriptive sensitivity reporting. Do not make accuracy, false-split, or false-merge claims.

**Deliverable:** A reproducible manifest plus a label-policy note naming which conclusions each label type can support.

### Task 2 — Determine whether Entity grouping materially changes Audit

**Files:**

- Inspect/use: `services/analysis-worker/audit_diagnostics/`, `services/analysis-worker/channels/entity.py`, `libs/provenance/derivation.py`, `services/analysis-worker/audit/graph.py`.
- Add tests only if a new diagnostic-only variant is needed: `tests/test_audit_diagnostics_logo.py`, `tests/test_audit_diagnostics_comparison.py`, and a focused Entity grouping test.
- Production files remain untouched until this task passes its evidence gate and a later implementation is authorized.

- [x] Report co-support for every Entity channel pair, with separate counts for applicable, available, neutral, and supporting states. Keep `E_reference`, `E_remote`, and device/card/site as distinct fields in the report. The exact state cross-tab covers every within-chain pair in all three checked 500-alarm replay fixtures; see the descriptive status below.
- [x] Trace the `device_code`/`component` contract and producer paths, then compare their equality partitions over all alarms in each checked preset with input hashes pinned. No authoritative field dictionary was found; the observed relationship is source-dependent and does not justify a global device/card merge.
- [x] Run the current exact pair profile and leave-one-effective-group-out for the 26-member IP and 14-member replay chains. For the 71-member IT chain, run exact graph-only LOGO from the frozen pair matrix after full candidate generation exceeded its 300-second limit. Report edge removals separately from retained weight changes and inspect the two-support boundary first.
- [ ] Complete frozen-candidate/winner/conductance comparison for the 71-member IT chain. The exact full diagnostic timed out before publishing a candidate report; the graph-only result below does not replace candidate scoring.
- [x] Compare the baseline with the diagnostic-only device/card/site grouping on the selected chains. This is a graph sensitivity scenario only; keep reference and remote separate unless a source/data lineage review establishes a reason to test a different grouping. Never activate an exploratory grouping through the baseline registry.
- [ ] For each grouping comparison, freeze candidates and scope; report material candidate-rank change, `delta_phi`, verdict flips, coverage and edge transitions. Use the already specified `delta_phi` materiality policy; if it remains `NOT_CONFIGURED`, report raw changes without calling them operationally material.
- [ ] On labeled holdout data, compare the current grouping and each pre-registered grouping against the relevant outcome label. Report pair/candidate precision and recall as applicable, calibration only for probability outputs, and Audit proposal outcomes only when proposal labels exist.

**Gate:** Change Entity grouping only if the source semantics justify the tested grouping, the pre-registered effect exceeds `Delta_min` on temporal/lineage holdout, and the relevant false-split/review outcome does not materially worsen. Otherwise preserve current tags and record the overlap as a known dependency risk.

**Deliverable:** A signed sensitivity report that concludes one of: `KEEP_BASELINE`, `ELIGIBLE_FOR_GROUPING_CHANGE`, or `INSUFFICIENT_OPERATIONAL_EVIDENCE`.

**Current descriptive status (2026-09-28):** The Entity state cross-tab covers all within-chain pairs in the three checked fixtures (6,185 pairs). Full frozen-candidate LOGO reports are available for the 26-member IP and 14-member replay chains. Exact graph-only LOGO is complete for the 71-member IT chain; its full candidate/conductance run exceeded the frozen 300-second limit. `delta_phi` is unconfigured, source-owner field semantics are absent, and no independent NOC pair/incident/role labels were found. Therefore the interim gate outcome is `INSUFFICIENT_OPERATIONAL_EVIDENCE`; no production grouping change is justified. The candidate/conductance comparison for the large IT chain remains incomplete.

**Entity state cross-tab across all observed within-chain pairs:**

| Replay preset | Alarms / chains | Within-chain pairs | Key observed co-support |
| --- | ---: | ---: | --- |
| `real_alarm_ip_demo` | 500 / 258 | 1,008 | `E_device` and `E_site` both SUPPORT on 492 pairs; `E_device` and `E_card` both SUPPORT on 166 jointly available pairs |
| `real_alarm_it_demo` | 500 / 226 | 4,463 | `E_device` and `E_card` have identical states on 4,084 pairs (91.5%); `E_site` SUPPORTs all 4,463 pairs |
| `real_alarm_20260907_demo` | 500 / 251 | 714 | `E_device` and `E_site` both SUPPORT on 271 pairs; `E_card` is UNAVAILABLE on all 714 pairs |

All pairs in each declared within-chain population are APPLICABLE under the pinned scope rule; field absence is counted as UNAVAILABLE. The full ten-channel-pair joint-state tables are in `/tmp/hindsight-entity-all-chain-cosupport-20260927.json`. These are replay `chaining_id` populations, not adjudicated incidents.

**Diagnostic-only grouping scenario:** `E_device`, `E_card`, and `E_site` were assigned one temporary shared derivation tag and the canonical Audit graph was rebuilt. No production registry or channel score changed.

| Replay chain | Members / pairs | Baseline → grouped edges | Removed | Retained weights changed | Frozen-candidate result |
| --- | ---: | ---: | ---: | ---: | --- |
| IP `6913556` | 26 / 325 | 270 → 270 | 0 | 264 | Winner unchanged; no verdict flip; raw `absolute_phi_drift=0.1198` |
| IT `6335571` | 71 / 2,485 | 2,058 → 2,055 | 3 | 1,782 | Not available; full exact diagnostic timed out before candidate report |
| `20260907_demo` `6893731` | 14 / 91 | 91 → 91 | 0 | 85 | Winner unchanged; no verdict flip; raw `absolute_phi_drift=0.0599` |
| `20260907_demo` `6893522` | 8 / 28 | 21 → 21 | 0 | 18 | Candidate comparison not run |
| `20260907_demo` `6893948` | 4 / 6 | 6 → 6 | 0 | 4 | Candidate comparison not run |

**Post-hoc narrower scenario (exploratory only):** After seeing the `E_device`/`E_card` state match in IT, those two tags alone were merged while `E_site` remained a separate group. It removed no edges on any of the five chains. It changed 205/270 retained edge weights in IP (frozen winner unchanged, no verdict flip, raw `absolute_phi_drift=0.0508`), 1,785/2,058 in IT, and no edge weights in the three `20260907_demo` chains because `E_card` was UNAVAILABLE there. Candidate comparison was unavailable for IT. Since this variant was formed after inspecting the same data, it is hypothesis-generation evidence only and cannot be used as a holdout acceptance result. It is included in `/tmp/hindsight-entity-co-support-20260927.json`.

For the IT 71-member chain, `device_code` and `component` each have seven non-missing values with a one-to-one mapping, so their equality channels induce the same partition: their pair states match on all 2,485 pairs. `location_code` has one value across the chain and `E_site` supports all pairs. The three removed edges each had SUPPORT from `E_device`, `E_card`, and `E_site`, while `S` and `T_burst` were NEUTRAL; merging the three Entity tags reduced those three distinct votes to one, below Audit's two-group floor. This confirms that the current group count can depend on duplicate pair partitions in this fixture. It does not tell us whether the three edges should be absent operationally. The detailed graph result is in `/tmp/hindsight-entity-co-support-20260927.json`.

**Source-field lineage check (all 500 alarms per fixture, 2026-09-27):** `E_device` reads `device_code`; `E_card` reads raw `component`. The contract preserves `component` in `raw` and declares no alias/identity relation between these fields. The Mock topology mapper may try `component or port`, but that fallback is not used by `E_card`. No authoritative upstream field dictionary was found in the inspected repository, so value equality and topology mapping are not proof of shared identity semantics.

| Preset | `device_code` present / unique | `component` present / unique | Rows with both | Device values mapping to >1 components | Components mapping to >1 devices | Comparable all-fixture pairs: concordant / discordant |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `real_alarm_ip_demo` | 500 / 141 | 407 / 176 | 407 | 34 | 29 | 1,026 / 1,114 of 82,621 |
| `real_alarm_it_demo` | 475 / 144 | 324 / 83 | 299 | 9 | 0 | 2,081 / 186 of 44,551 |
| `real_alarm_20260907_demo` | 500 / 59 | 0 / 0 | 0 | N/A | N/A | N/A |

“Comparable pairs” means unordered alarm pairs for which both fields are present on both alarms. Concordant means both equality tests return the same state (both equal or both different); discordant means one field says equal while the other says different. Counts are descriptive over all fixture alarms, not only pairs within the same `chaining_id`; they are not pair labels or evidence that either channel is correct. Device/component counts in the mapping columns are restricted to rows where both fields are present. The fixture hashes are: IP `e83421fa817c12240fed1283078a7037727c78e7f1fb08fe18ae5cb386daa8ea`; IT `d3d0e8681de06a37e903d566d7d58c80334957990cbf00380be7a5bf7f372fe3`; `20260907_demo` `0c74b5fc56797e7df2f5027ea4d5285ed6b17ebd94edc759aa53337f89f40602`.

**Full-report LOGO edge transitions for IP chain `6913556` and `20260907_demo` chain `6893731`:** Both reports were revalidated against their frozen manifests, source files, configs, and snapshot bytes; both are `COMPLETE` with 33/33 report invariants.

| Chain | Edges removed after group removal | Retained edges whose weights changed | Frozen-candidate comparison |
| --- | --- | --- | --- |
| IP `6913556` (26 members, 325 pairs) | `dependency_hop`: 45; `site`: 45 | `card`: 205; `dependency_hop`: 214; `device`: 264; `semantic`: 264; `site`: 219; `temporal_burst`: 264 | Fixed winner unchanged in all variants. Diagnostic `epsilon_phi=0.3` candidate verdict flipped for `card` and `semantic`; raw maximum `absolute_phi_drift=0.0608`. |
| `20260907_demo` `6893731` (14 members, 91 pairs) | None | `device`: 85; `reference`: 85; `semantic`: 85; `site`: 85; `temporal_burst`: 85 | Fixed winner unchanged and no candidate verdict flips; raw maximum `absolute_phi_drift=0.0599`. |

Changed-weight counts exclude edges removed by the two-support floor. In IP, the 45 boundary pairs had exactly two baseline supporting groups; removing either `dependency_hop` or `site` removed those 45 edges. “Candidate verdict flip” is the frozen-candidate threshold comparison inside the diagnostic, not a production chain verdict. `delta_phi` remains `null`, so none of these changes is classified as operationally material.

**Exact LOGO edge transitions for IT chain `6335571` (71 members, 2,485 pairs):** The full diagnostic manifest was revalidated against current source/config/snapshot hashes. Pair evaluation and canonical Audit graph construction completed exactly; all 10 group-removal variants passed their 3 graph invariants (30/30). Across the baseline graph's 1,004 pairs with exactly two supporting groups, removing `site` removes 1,004 edges; removing `semantic` removes 809; removing `temporal_burst` removes 195. Removing `device` or `card` removes no edge but changes 1,785 retained edge weights for either group. These rows are separate one-group-at-a-time variants; removed-edge counts across variants must not be added as unique pairs.

| Removed effective group | Edges removed at the two-group floor | Retained edges with changed weight | Removed group's state on the 1,004 boundary pairs |
| --- | ---: | ---: | --- |
| `site` | 1,004 | 781 | SUPPORT: 1,004 |
| `semantic` | 809 | 976 | SUPPORT: 809; NEUTRAL: 195 |
| `temporal_burst` | 195 | 1,590 | SUPPORT: 195; NEUTRAL: 809 |
| `device` | 0 | 1,785 | NEUTRAL: 1,004 |
| `card` | 0 | 1,785 | NEUTRAL: 1,004 |
| Other five groups (`dependency:topology-capability-unavailable`, `dependency_hop`, `reference`, `remote`, `temporal_delay`) | 0 each | 0 each | UNAVAILABLE: 1,004 each |

The graph-only artifact is `/tmp/hindsight-audit-logo-it-20260928.json`, tied to the frozen manifest digest in that file. It does not include candidate generation, candidate ranking, conductance, verdict comparison, or `delta_phi`. The full diagnostic run timed out before those outputs were produced; no candidate-level IT conclusion is recorded.

**Interim gate decision (2026-09-28): `INSUFFICIENT_OPERATIONAL_EVIDENCE`.** The replay runs establish that Audit graph edges and weights depend on the separate effective-group tags, including 1,004 two-support boundary pairs in the selected IT chain. They do not establish that those edges are false or that groups should be merged. The remaining blockers are source-owner semantics, correctly typed held-out NOC labels, a pre-registered `Delta_min`, an operational `delta_phi`, and the full IT candidate comparison. Keep the current grouping as the baseline until those gates can be evaluated.

**Finding and remediation hypothesis:** The dependence risk is demonstrated in replay data; an operationally wrong split is not. The selected IT chain has identical device/card equality partitions, but the whole IT fixture has nine device values associated with multiple component values; the IP fixture is many-to-many, and the third fixture has no `component`. A single global device/card grouping is therefore not justified by the current source semantics or replay data. Treat a source-reviewed family mapping only as a future hypothesis for an identified source/vendor scope, with `E_site`, `E_reference`, and `E_remote` kept separate unless separate evidence supports otherwise. Do not deduplicate groups dynamically from matching verdict vectors in the same replay used to invent the rule.

Before any implementation, obtain source-owner semantics for the exact vendor/source scope and confirm mapping stability on an independent time/lineage holdout. Only then pre-register a grouping variant for that scope; keep the broader device/card/site case as a sensitivity stress test, not a default promotion candidate. Freeze `Delta_min` and the operational basis for `delta_phi` before viewing holdout outcomes, then compare using the correctly typed pair/incident labels and Audit review outcomes. Roll out only if field lineage supports the grouping and held-out outcomes meet those thresholds. Otherwise retain separate tags and document the observed dependence risk. This remains a gated hypothesis, not an approved code change.

### Task 3 — Validate source coverage for shared context and failure domains

**Files:**

- Read: `contracts/v1/models.py` (`OperationalContext`, `FailureDomain`, and `Topology`), `libs/contracts/loader.py`, `nocpro-mock/src/nocpro_mock/scenarios/context_generator.py`, `services/analysis-worker/channels/failure_domain.py`, and `services/analysis-worker/audit/candidates.py`.
- Potential future implementation, only after source approval: `contracts/v1/models.py`, `libs/contracts/loader.py`, a focused channel module under `services/analysis-worker/channels/`, `channels/evaluator.py`, and their corresponding contract/channel tests.

**Initial checked-repository inventory (2026-09-27; fixture evidence only):**

| Replay preset | Alarms | Topology nodes | Edges | Mappings | Failure domains | Operational-context records |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `real_alarm_ip_demo` | 500 | 2,333 | 3,910 | 500 | 0 | 0 |
| `real_alarm_it_demo` | 500 | 463 | 740 | 349 | 0 | 0 |
| `real_alarm_20260907_demo` | 500 | 0 | 0 | 0 | 0 | 0 |

The contracts and loader support `OperationalContext` and set-valued `FailureDomain`; the Mock context generator is synthetic. `H_domain` is an existing set-valued membership/candidate capability, not pairwise evidence, and no checked real preset supplies its failure-domain records. The canonical pair evaluator does not consume `operational_context`. This inventory covers checked-in replay inputs only; external inventory/ITSM/network-management sources and their mappings have not been inspected.

**Status:** `REPLAY_FIXTURE_INVENTORY_COMPLETE`; authoritative source records, source-owner semantics, and external mapping quality remain unverified.

- [ ] Obtain a sample of authoritative operational-context and failure-domain records, with source owner, event/domain identifiers, resource mapping, source version, valid-time semantics, provenance, quality state, and correction history.
- [ ] Profile coverage and mapping correctness on a pinned real snapshot: fraction of alarms with mapped resources, contexts/domains per alarm, stale/ambiguous mappings, event windows, and duplicate IDs. Keep unknown applicability distinct from missing records.
- [ ] For change/maintenance correlation, have the source owner define what constitutes the same event, how alarm time relates to event time, and whether the association is explanatory, predictive, or adjudicated. Do not infer a shared event from `MAINTENANCE` provenance alone.
- [ ] For Shared Risk Group/failure-domain data, confirm the domain represents a shared failure mode rather than administrative grouping. Keep the current hyperedge/set semantics; do not generate pair edges for all members.
- [ ] If real records remain absent or fail mapping/quality review, stop at a documented ingestion gap. Synthetic generator outputs may test parsing and boundaries only.

**Gate:** No production channel or candidate contribution until the owner approves the source semantics and provenance/eligibility treatment, real record coverage is reported, and an offline replay shows benefit on an appropriate held-out label.

**Deliverable:** A source-readiness report. If ready, a separately reviewable channel design for either (a) shared operational event pair evidence or (b) set-valued failure-domain evidence; do not merge those into one feature.

### Task 4 — Specify and evaluate explicit pair counter-evidence

**Files:**

- Read: `services/analysis-worker/channels/base.py`, `audit/verdict.py`, `tier2/audit_analysis.py`, `tier2/jobs.py`, `contracts/v1/models.py`, `services/analysis-worker/graybox/system_fact_box.py`, and `services/analysis-worker/tier2/counterfactual/models.py`.
- Potential future implementation: the source-specific pair producer, a typed negative-evidence representation, the Audit over-merge evidence aggregator, serialization/API tests if its contract changes, and focused tests in `tests/test_channels.py`, `tests/test_tier2_audit.py`, and a negative-evidence test module.

- [ ] Identify an authoritative source that can positively assert “these alarm resources are mutually independent for this failure mode / time interval”; absence of a relation, `NEUTRAL`, or `UNAVAILABLE` is not such an assertion.
- [ ] Write a versioned policy for scope, validity interval, source identity, resource mapping, evidence threshold, provenance class/subtype, and audit/review eligibility. Specify how stale or contradictory source records fail closed.
- [ ] Choose a typed representation that is distinct from `SUPPORT`, `NEUTRAL`, and `UNAVAILABLE`; do not treat the current numeric `negative_score` as a verdict without an explicit threshold and semantics.
- [ ] Keep the Audit graph’s nonnegative support weights unchanged. If an explicit contradiction is used, feed it as a separate cross-block evidence line for an already generated candidate cut; it must not create a positive edge or turn missing data into a veto.
- [ ] Keep `M_pair.system_semantic=VETO` as `SYSTEM_FACT` unless the system owner explicitly defines and approves a mapping from that upstream contract to the new contradiction policy. Do not auto-promote Counterfactual `ExternalValidationArtifact` values into pair channels; that artifact already has a distinct eligibility-gated review path.
- [ ] Test exact pair scope, time validity, missing source, conflicting records, provenance gates, serialization, false/unknown behavior, and evidence-line output. Include tests proving no negative graph weights and no contradiction from absent data.

**Gate:** Do not implement if there is no authoritative contradiction source or if operators cannot distinguish its meaning from “not enough positive evidence.” A hook that remains false is preferable to fabricated contradiction evidence.

**Deliverable:** Either a reviewed typed channel contract and test specification, or a documented `NO_TRUSTED_NEGATIVE_SOURCE` decision.

### Task 5 — Test severity/type compatibility as an optional feature

**Files:**

- Read: `services/analysis-worker/descriptor/predicates.py`, `descriptor/representativeness.py`, `tier1b/chain_analysis.py`, `tier2/audit_analysis.py`, and `channels/semantic.py`.
- If approved after evaluation: a separate channel implementation and evaluator wiring, with tests in `tests/test_channels.py`, `tests/test_descriptors.py`, and focused pair-channel tests.

- [ ] Define the question before defining the score: technical type compatibility, severity-pattern consistency, or both are separate hypotheses. Do not reduce either to exact severity equality by default.
- [ ] Freeze taxonomy/version and missing-value behavior. If the feature uses temporal order, call it ordered compatibility and do not describe it as a causal direction.
- [ ] Evaluate incremental value over the existing baseline, including the existing descriptor-mediated effects. Ablate the proposed channel without silently removing descriptor inputs; test whether it duplicates or counteracts representativeness/candidate behavior.
- [ ] Use the label and split protocol from Task 1. Report coverage, pair-level precision/recall, calibration when meaningful, and downstream Audit/member-role changes. Compare against pre-registered `Delta_min` on held-out incident lineage.

**Gate:** Add a pairwise severity/type feature only if it improves the specified held-out outcome beyond `Delta_min` without material degradation of existing CORE/Audit behavior. Otherwise retain the descriptor path and document that a separate compatibility channel was tested and not promoted.

**Deliverable:** A decision record `PROMOTE`, `REJECT`, or `INSUFFICIENT_LABELS`, with feature definition and evidence.

### Task 6 — Promotion, audit trail, and code-comment consistency

**Files:**

- Update, if an implementation is approved: `docs/METHODOLOGY.md`, `docs/FEATURE_CAPABILITY_MATRIX.md`, `docs/DATA_SOURCES.md`, `docs/CURRENT_STATUS.md`, and a focused ADR or decision record.
- [x] Correct stale descriptions in `services/analysis-worker/channels/entity.py` and `services/analysis-worker/audit/graph.py`; preserve the distinction between grouping keys and independent evidence.
- [x] Document the exact Fit aggregation in both implementations and active methodology/status docs; do not change it without labeled evaluation.

- [ ] Record the feature/grouping ID and version, source/data version, field scope, derivation and provenance lineage, availability/neutral/contradiction semantics, threshold/null model if applicable, eligibility, label policy, backtest manifest, `Delta_min`, approvers, effective date, and rollback reference.
- [ ] Require a channel owner and a second reviewer from the NOC/domain group to sign off. Record organizational roles and approval evidence; do not treat an undocumented “expert” label as governance.
- [ ] Keep promotion human-reviewed and versioned. The current plan does not require a generic config engine, learned weights, automatic activation, or a new shadow-mode framework.
- [x] Align the Entity module comment with its actual field/tag mapping and the `build_audit_graph` docstring with the implementation’s two-supporting-group threshold.
- [x] Keep explicit limitations in active docs: topology pair scores represent shared directed context; `H` remains Pair WHY; `H_domain` remains set-valued; feature diagnostics do not prove channel completeness.

**Gate:** No channel or grouping change is “accepted” into the production baseline until source review, tests, offline backtest, domain approval, versioned docs/ADR, and an explicit implementation authorization are all present.

### Task 7 — Assess Fit aggregation and sample-size sensitivity

**Files:** `services/analysis-worker/groups/fit.py`, `groups/fit_from_index.py`, `tests/test_fit_and_roles.py`, `tests/test_indexed_equivalence.py`, and the label/evaluation manifest from Task 1.

- [x] Record the current semantics: max within each effective group, then unweighted mean across computable role-eligible groups. `domain_size` is only the denominator inside each channel Fit ratio.
- [ ] On labeled temporal/lineage holdout, measure whether small `domain_size` produces unstable per-member fits or materially changes role assignment. Keep pair/incident/proposal label meanings separate.
- [ ] If comparing shrinkage, confidence weighting, or another aggregator, pre-register its estimator, prior/uncertainty assumptions, `Delta_min`, and evaluation metrics. Compare it with the unchanged baseline; do not infer improvement from synthetic arithmetic tests.
- [ ] Report computable-group coverage and the distribution of per-channel `domain_size` alongside role changes. Do not call the current equal-weight formula statistically wrong solely because group sample sizes differ.

**Gate:** Retain the current formula unless an appropriate labeled holdout shows a pre-registered operational improvement without unacceptable regression. If suitable labels are absent, report `INSUFFICIENT_LABELS` and keep this as a sensitivity question, not a production defect.

## 4. Verification commands for a later implementation

Run from `nocpro-chain-explain/` after corresponding evidence-gated behavior changes:

```bash
PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/pytest -q \
  tests/test_audit.py tests/test_fit_and_roles.py \
  tests/test_graybox_pair_metadata.py tests/test_failure_domains.py \
  tests/test_descriptors.py tests/test_contract_parsing.py tests/test_tier2_audit.py
```

The initial source-review set passed **135 tests**. After the approved fixes and added regressions, the expanded focused set passed **257 tests** (see the execution record). Tests are not acceptance evidence for unimplemented channels.

For Entity grouping or edge-weight changes, also run the existing diagnostic suite and assert baseline equivalence before enabling any changed policy:

```bash
PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/pytest -q \
  tests/test_audit_diagnostics_contracts.py tests/test_audit_diagnostics_scope.py \
  tests/test_audit_diagnostics_coverage.py tests/test_audit_diagnostics_logo.py \
  tests/test_audit_diagnostics_comparison.py tests/test_audit_diagnostics_runner.py
```

## 5. Completion criteria and stop conditions

- [ ] The source review distinguishes actual runtime behavior from missing capability, data availability, and terminology mistakes.
- [ ] Each proposed change has a pinned baseline, correctly typed labels, temporal/lineage split, no known leakage, a pre-registered `Delta_min`, and an uncertainty report.
- [ ] Entity grouping remains unchanged unless material operational benefit is demonstrated and field/source semantics justify the proposed family.
- [ ] No negative verdict is produced from absence, unavailable input, or neutral score; no negative evidence is converted into a negative Audit edge weight.
- [ ] No operational-context channel is added without authoritative real event records and reviewed time/resource semantics.
- [ ] Severity/type is not added as a pairwise channel unless its incremental held-out value is demonstrated beyond the existing descriptor-mediated path.
- [ ] `H`, `H_domain`, `M_pair` veto facts, and Counterfactual validation artifacts retain separate contracts and provenance.
- [ ] Documentation, tests, and audit trail describe the implemented behavior and known limits accurately.

Stop and report `INSUFFICIENT_OPERATIONAL_EVIDENCE` if labels, source semantics, real records, or an agreed materiality criterion are missing. Do not fill those gaps with synthetic data, hand-picked examples, or post-hoc thresholds.

## 6. Execution record

- Fixed exact diagnostic capture to compare unordered pair keys canonically; a regression test covers a valid membership order that differs from pair-matrix key order.
- Fixed generated descriptor Audit candidates to restrict each candidate extent to the current chain member universe. Descriptor mining metrics remain based on their intended predicate universe.
- Corrected stale Audit graph/Entity/Fit comments, including the two-group edge condition, exact-only over-ceiling behavior, and the fact that entity derivation tags do not prove shared or independent measurements. Added an implementation-status note to ADR-0016 because its approximate-graph design is not present in current source.
- Fit behavior was confirmed in both implementations and is now explicit in docs. No Fit formula change, Entity grouping change, negative channel, event channel, or severity pair channel was made because the required independently adjudicated outcome/data gates are not met by the checked replay fixtures.
- Clarification for the `Fit_C` question: this repository does not expose a symbol literally named `Fit_C`; the corresponding chain-level scalar is `MembershipSupport(x,C)`. It is not a global max: `Fit_k` is the supported-peer fraction among that channel's available peers, `Fit_g` is the unweighted maximum of computable `Fit_k` values inside one effective derivation group, and `MembershipSupport` is the unweighted mean of computable role-eligible `Fit_g` values. The group vector is retained. Neither peer count nor uncertainty weights the cross-group mean. In the current registry, `E_reference`, `E_device`, `E_card`, `E_site`, and `E_remote` have distinct derivation tags, so `max` does not collapse these Entity channels into one vote; each computable role-eligible group may contribute its own equal-weight term. This confirms the implemented policy; without independent incident/role labels it does not establish that this policy is operationally wrong.
- The first IP diagnostic manifest was found stale because the `channels/evaluator.py` source hash had changed; it is superseded and must not be used for candidate conclusions. A fresh current-source exact run completed for `real_alarm_ip_demo`, chain `6913556` (26 members, 325 unordered pairs, 10 effective audit groups, 3 frozen candidates, 11 variants); all 33/33 invariants passed. Leave-one-group-out for `site` and `dependency_hop` each removed 45 edges at the two-supporting-group floor. Excluding `card` or `semantic` flipped the candidate verdict while preserving the winner. The production baseline verdict remained `NO_LOW_CONDUCTANCE_CUT`, and `delta_phi` is null. The fresh report is `/tmp/hindsight-pair-evidence-remediation-ip-20260927-current/f0ea7ee5-1614-4c64-ae49-739db2ac624f/report.json`.
- Exact `evaluate_entity_channels` state cross-tabs covered all within-chain pairs in the three checked 500-alarm fixtures: 1,008 IP, 4,463 IT, and 714 `20260907_demo` pairs. Across IT within-chain pairs, `E_device` and `E_card` states were identical on 4,084/4,463 pairs (91.5%); within the selected 71-member chain their underlying `device_code` and `component` values induce identical pair partitions, while `location_code` is constant. The full ten Entity channel-pair joint-state table is `/tmp/hindsight-entity-all-chain-cosupport-20260927.json`.
- A diagnostic-only `E_device`/`E_card`/`E_site` shared-tag graph scenario changed edge weights on 264/270 baseline edges in IP chain `6913556` and 85/91 in chain `6893731`, without removing an edge. Frozen candidate winners remained unchanged and verdicts did not flip; raw `absolute_phi_drift` was 0.1198 and 0.0599 respectively, with materiality still unconfigured. In IT chain `6335571`, the exact pair and graph-level scenario completed despite the full candidate diagnostic timing out: 3 of 2,058 baseline edges fell below the two-support group floor and 1,782 retained weights changed. The three removed pairs were supported by device, card, and site only, with `S` and `T_burst` neutral. Detailed exploratory results are in `/tmp/hindsight-entity-co-support-20260927.json`; they do not establish false-split correctness.
- A post-hoc device/card-only grouping scenario was also checked on the same five chains; it removed no edges and changed 1,785 IT and 205 IP weights, while the fixed-candidate winner stayed unchanged on IP/14-member runs. This narrower grouping was proposed after inspecting the co-support table, so it remains exploratory and requires independent holdout validation.
- A second exact descriptive LOGO run completed on `real_alarm_20260907_demo`, chain `6893731` (14 members, 91 unordered pairs, 10 effective audit groups, 4 frozen candidates, 11 variants); all 33/33 invariants passed. `E_reference`, `E_site`, and `S` each returned SUPPORT for all 91 pairs; `E_device` supported 26/91 and `T_burst` 28/91. This directly shows co-support across distinct derivation groups in this selected replay chain, but it is not proof those measurements are independent or that any resulting edge is false. Across all 10 LOGO variants the diagnostic winner was unchanged, there were no candidate verdict flips and no edges were removed; excluding `device`, `reference`, `semantic`, `site`, or `temporal_burst` changed some edge weights. The largest reported raw `absolute_phi_drift` was 0.0599 (excluding `device`), but `delta_phi` remains null, so materiality is unconfigured. The baseline Audit verdict was `NO_LOW_CONDUCTANCE_CUT`; the retained winner is only the best among the frozen diagnostic candidates, not an activated production cut. The report is at `/tmp/hindsight-pair-evidence-remediation-20260927-third-snapshot/c3c5ee4a-adb6-40bf-a911-497ef55a1f66/report.json` and is a local ephemeral artifact.
- A descriptive indexed `MembershipSupport` profile was produced for three selected chains in `real_alarm_20260907_demo`: chain `6893731` (14 members; five computable groups/member; support range 0.662–0.754, mean 0.719), `6893522` (8; five groups for two members and six for six; 0.314–0.714, mean 0.606), and `6893948` (4; six groups/member; 0.778 for all). All selected members classify as `PERIPHERAL` under the pinned `v1.yaml`; none has unavailable MembershipSupport. `T_delay` had no exact indexed sufficient-statistics path and topology channels had no usable topology domain in this preset. The chain selection is descriptive, the replay partition is not incident truth, and these counts do not establish that the equal-weight Fit formula or the resulting roles are correct or incorrect.
- A fresh exact diagnostic was prepared for `real_alarm_it_demo`, chain `6335571` (71 members, 2,485 unordered pairs, 11 variants). Its full candidate run exceeded the frozen 300-second worker limit and exited `3` without publishing a report. A graph-only follow-up revalidated the same manifest and pair universe, ran canonical LOGO for all 10 effective groups, and passed 30/30 graph invariants. Removing `site`, `semantic`, and `temporal_burst` removed 1,004, 809, and 195 edges respectively; removing `device` or `card` changed 1,785 retained edge weights and removed none. No IT candidate, winner, conductance, or verdict result is available. See `/tmp/hindsight-audit-logo-it-20260928.json`; this graph-only result does not replace the timed-out candidate diagnostic. Do not treat the timeout as a logic failure or relax the frozen resource policy based on this single run.
- The three replay presets remain descriptive inputs, not NOC ground truth; no operational materiality conclusion is made. The checked-repository context inventory found zero failure-domain and operational-context records in all three; external operational sources remain uninspected.
- Focused verification after these changes: the Audit/Fit/channel/diagnostic/indexed-equivalence suite passed **257 tests**. The result verifies contracts and code paths, not NOC operational benefit.
