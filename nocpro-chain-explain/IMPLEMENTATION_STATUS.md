# Implementation status

This is the closure status for the implementation currently in this worktree.
It separates **capability** from evidence that the capability was exercised;
`READY` never means production validity by itself.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `READY` | Implementation path exists and is intentionally available when its inputs/configuration are present. |
| `PASS` | The named automated test or synthetic fixture ran and passed. It is not a production claim. |
| `NOT_RUN` | The test/harness exists but was not executed in this environment. |
| `UNAVAILABLE` | Correct fail-closed result: required data, capability, configuration, or exact implementation path is absent. |
| `NOT_CALIBRATED` | No empirical production calibration establishes the relevant policy/threshold. |
| `BLOCKED_BY_DATA_AVAILABILITY` | External data required for production validation has not been supplied. |
| `BLOCKED` | A product operation is intentionally not run because an upstream semantic contract is unverified. |

## Capability and evidence matrix

| Capability | Implementation | Unit/regression | Synthetic | Docker/runtime | Production | Boundary / evidence needed |
| --- | --- | --- | --- | --- | --- | --- |
| Kafka chunk + `SNAPSHOT_COMPLETE` barrier, PostgreSQL ingest, Tier-1A | `READY` | `PASS` | `PASS` | `PASS` synthetic Docker stack | `BLOCKED_BY_DATA_AVAILABILITY` for production delta validation | The 2026-09-03 acceptance run covered Kafka, PostgreSQL READY and restart paths; raw production replay is skipped because `alarm_data.csv` is absent. |
| Tier-1B lazy indexed analysis and cache | `READY` | `PASS` | `PASS` | `PASS` synthetic Docker stack | `READY` for available primitive evidence only | Chain size 1072 is an anti-dense regression gate; Tier-1B may not use a dense pairwise fallback. |
| Pair WHY API/UI | `READY` | `PASS` | `PASS` | `NOT_RUN` | Input-dependent | A Pair WHY result can be `UNAVAILABLE` without changing Tier-1B availability. |
| Historical `H` Pair WHY | `READY` | `PASS` | `PASS` | `NOT_RUN` | `BLOCKED_BY_DATA_AVAILABILITY` | The raw-field adapter is a `DERIVED_REPLAY` utility, not authoritative taxonomy. Production requires a business-owned, versioned taxonomy and verified historical lineage corpus. |
| `T_delay` frozen model/training semantics | `READY` | `PASS` | `PASS` | `NOT_RUN` | `BLOCKED_BY_DATA_AVAILABILITY` | The raw-field adapter and sequence slicer support test/replay only; production requires authoritative taxonomy, verified sequential snapshots, and calibrated configuration. |
| `T_delay` Pair WHY runtime/API/UI | `READY` | `PASS` | `PASS` | `NOT_RUN` | `UNAVAILABLE` / `NOT_CALIBRATED` | No production taxonomy/model/calibration has been established. |
| `T_delay` full-chain indexed Role contribution | `UNAVAILABLE` | `PASS` fail-closed | N/A | N/A | `UNAVAILABLE` | `NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH`. Dense pairwise fallback is forbidden. |
| `T_delay` full-chain indexed Audit contribution | `UNAVAILABLE` | `PASS` fail-closed | N/A | N/A | `UNAVAILABLE` | `NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH`. Eligibility metadata does not manufacture an exact indexed statistic. |
| Structural Audit, attribution, deletion evaluation | `READY` under exact ceilings | `PASS` | `PASS` | `PASS` synthetic Docker stack for Audit/Review | Input/config-dependent | Ceiling exceedance is component `UNAVAILABLE`, not a fabricated approximation or a failed Tier-2 job. |
| Similar Chains | `READY` | `PASS` | `PASS` | `NOT_RUN` | Degraded / input-dependent | Raw `group_name` can be used only as an observed source field; it does not establish authoritative production taxonomy. |
| Evolution v1 persisted lineage projection | `READY` | `PASS` | `PASS` | `PASS` synthetic Docker stack | `BLOCKED_BY_DATA_AVAILABILITY` | The sequence slicer creates `DERIVED_REPLAY` windows from one export; production evolution requires verified sequential upstream snapshots. |
| Topology P2 semantics | `READY` only for compatible synthetic inputs | `PASS` | `PASS` | `PASS` synthetic Docker stack | `UNAVAILABLE` | IP is structural adjacency and IT is unverified source relation. Display hierarchy never supplies dependency direction, active paths, dominators, propagation, or failure domains. |
| Real topology navigation read model | `READY` | `PASS` | N/A | `PASS` local mock endpoint + Chromium tree preview | `READY` for source-record navigation only | `ALARM_ONLY` has no topology; IP is undirected adjacency; IT is `DIRECTED_SOURCE_RELATIONS`, not verified dependency. Tree primary paths are technical projection only. The full Explain snapshot workflow remains separately input-dependent. |
| Real IT/IP topology contribution to Explain P2 | `UNAVAILABLE` | `PASS` fail-closed | N/A | N/A | `UNAVAILABLE` | `SOURCE_RELATION` / `UNVERIFIED` IT records and IP adjacency must not enable dependency, ancestor, dominator, propagation, scope, or failure-domain semantics. |
| Synthetic operator-feedback fixture | `READY` | `PASS` | `PASS` | N/A | `NOT_CALIBRATED` | Typed accepted/rejected labels exercise empirical-evaluation input only. It is `SYNTHETIC_TEST` and explicitly cannot serve as production ground truth. |
| Counterfactual `REMOVE_MEMBER`, `SPLIT_CHAIN`, `MOVE_MEMBER`, connector annotation | `READY` | `PASS` | `PASS` | `PASS` synthetic Docker stack | `NOT_CALIBRATED` | Proposal-only; production recommendation policy requires operator corrections/calibration. |
| Counterfactual `MERGE_CHAINS` | `READY` | `PASS` | `PASS` | `PASS` synthetic Docker stack | `NOT_CALIBRATED` | Exact cross-chain evidence, persisted Review reload and Chromium Review acceptance passed; production policy remains uncalibrated. |
| Counterfactual `ADD_MEMBER` | `BLOCKED` | N/A | N/A | N/A | `BLOCKED` | `UNKNOWN_UPSTREAM_SEMANTICS`: first-class zero-membership alarms have not been verified upstream. A singleton-source transfer is canonical `MOVE_MEMBER`, never ADD. |

## Topology hierarchy boundary

`topology_hierarchy.py` supplies display ordering only for `STRUCTURAL_NAVIGATION`.
It is forbidden from supplying P2/RCA dependency direction, common ancestor,
dominator, active-path, propagation, scope-overlap, or failure-domain inputs.
Promotion into P2 requires a separate authoritative business semantics source,
verified alarm-resource mappings, and versioned provenance/configuration.

## T_delay boundary

`T_delay` Pair WHY is a persisted, frozen, directed historical temporal
compatibility model. It is distinct from NocPro `TimeWindow`, which remains a
system fact. It is not causal wording and it is not external validation.

The Post-hoc provenance eligibility mask does not override the availability
requirement. Current full-chain Role and Audit have no semantics-preserving
indexed sufficient-statistics provider for `T_delay`; they must return
`UNAVAILABLE` with `NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH`. A dense
`O(n^2)` fallback is forbidden, including on the 1072-member regression
workload.

**Closure finding:** the current indexed internal representation records this
as `fit=None` and does not yet serialize a separate full-chain diagnostic
reason field. The status label above is therefore the required capability
classification, not a claim that a currently exposed full-chain API already
contains that string. This is documented drift to keep visible; no fallback or
new full-chain algorithm was added in this closure pass.

## Closure benchmark and acceptance harness

- `benchmarks/run_benchmark.py` measures the current real-export Tier-1 matrix.
- `benchmarks/run_closure_benchmark.py` writes the complete closure measurement
  manifest, including `H`, `T_delay`, Audit, attribution, all Review operations,
  persistence, and restart hydration. It intentionally records unexecuted
  measurements as `NOT_RUN` rather than inventing timings.
- `tests/spec_sanity/test_tier1_execution_boundary.py` pins the 1072-member
  anti-all-pairs invariant.
- `tests/e2e/check_closure_acceptance.sh` validates the full acceptance inputs
  without invoking Docker. `tests/e2e/run_acceptance.sh` is the separate,
  explicit command that starts the stack.

The complete Docker acceptance sequence is:

```text
temporal_delay_patterns_v1
counterfactual_merge
synthetic_temporal_topology_v1
  -> Kafka chunk/barrier -> PostgreSQL READY -> Tier-1A -> Tier-1B
  -> persisted artifacts -> API restart -> Chromium/Playwright
```

`run_acceptance.sh` runs the explicit T_delay synthetic model/Pair WHY suite
with its authoritative test adapter alongside the Kafka/PostgreSQL stages.
It deliberately does **not** make the container's production-shaped baseline
invent taxonomy; that baseline remains fail-closed. The synthetic Docker
acceptance run passed on 2026-09-03: migration/runtime failure tests (6), P2
Kafka tests (3), Evolution Chromium (1), H/T_delay model tests (18),
Counterfactual Kafka/PostgreSQL/restart (1), and Counterfactual Chromium (1).
The raw-export replay stage was explicitly skipped because
`nocpro-mock/datasets/raw/alarm_data.csv` is unavailable. H/T_delay Pair WHY
through the production-shaped service/API remains `NOT_RUN`; the model suite
does not establish that separate capability.

## Production evidence still required

The following are external evidence acquisition items, not implementation
defaults:

- authoritative alarm TYPE/FAMILY/CATEGORY taxonomy;
- verified sequential production snapshots;
- operator-confirmed chain corrections for recommendation evaluation and policy calibration;
- exact alarm-to-topology resource mapping;
- directed dependency/path semantics and, where needed, dominator/path truth;
- failure-domain ground truth.

The three available production exports are not treated as a sequential snapshot
series. No overlap threshold, topology direction, taxonomy, or production
recommendation threshold is inferred from them.
