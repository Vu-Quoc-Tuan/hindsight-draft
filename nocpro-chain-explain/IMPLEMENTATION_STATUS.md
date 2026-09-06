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
| Kafka chunk + `SNAPSHOT_COMPLETE` barrier, PostgreSQL ingest, Tier-1A | `READY` | `PASS` | `PASS` | `PASS` synthetic Docker stack and raw-export replay | `BLOCKED_BY_DATA_AVAILABILITY` for production delta validation | The 2026-09-04 acceptance run covered Kafka, PostgreSQL READY, duplicate/recovery paths, restart, and replay of the local raw export at `nocpro-mock/datasets/raw/alarm/alarm_data.csv`. |
| Tier-1B lazy indexed analysis and cache | `READY` | `PASS` | `PASS` | `PASS` synthetic Docker stack | `READY` for available primitive evidence only | Chain size 1072 is an anti-dense regression gate; Tier-1B may not use a dense pairwise fallback. |
| Pair WHY API/UI | `READY` | `PASS` | `PASS` | `PASS` Chromium/operator flow | Input-dependent | A Pair WHY result can be `UNAVAILABLE` without changing Tier-1B availability. |
| Historical `H` Pair WHY | `READY` | `PASS` | `PASS` model suite | `BLOCKED_BY_DATA_AVAILABILITY` | The raw-field adapter is a `DERIVED_REPLAY` utility, not authoritative taxonomy. Production requires a business-owned, versioned taxonomy and verified historical lineage corpus. |
| `T_delay` frozen model/training semantics | `READY` | `PASS` | `PASS` model suite | `BLOCKED_BY_DATA_AVAILABILITY` | The raw-field adapter and sequence slicer support test/replay only; production requires authoritative taxonomy, verified sequential snapshots, and calibrated configuration. |
| `T_delay` Pair WHY runtime/API/UI | `READY` | `PASS` | `PASS` model suite; generic Pair WHY UI is runtime-proven | `UNAVAILABLE` / `NOT_CALIBRATED` | The production-shaped baseline does not invent taxonomy or a calibrated threshold, so T_delay-specific service/API availability remains intentionally fail-closed. |
| `T_delay` full-chain indexed Role contribution | `UNAVAILABLE` | `PASS` fail-closed | N/A | N/A | `UNAVAILABLE` | `NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH`. Dense pairwise fallback is forbidden. |
| `T_delay` full-chain indexed Audit contribution | `UNAVAILABLE` | `PASS` fail-closed | N/A | N/A | `UNAVAILABLE` | `NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH`. Eligibility metadata does not manufacture an exact indexed statistic. |
| Structural Audit, attribution, deletion evaluation | `READY` under exact ceilings | `PASS` | `PASS` | `PASS` synthetic Docker stack for Audit/Review; raw 1072-member exact run completed | Input/config-dependent | A one-run local raw-export 1072-member Audit completed in 80.633 s with Audit/Attribution/deletion all exact. This is a measurement, not a P95/SLO. Ceiling exceedance is component `UNAVAILABLE`, not a fabricated approximation or a failed Tier-2 job. |
| Similar Chains | `READY` | `PASS` | `PASS` | `PASS` raw-export replay | Degraded / input-dependent | Raw `group_name` can be used only as an observed source field; it does not establish authoritative production taxonomy. |
| Evolution v1 persisted lineage projection | `READY` | `PASS` | `PASS` | `PASS` synthetic Docker stack | `BLOCKED_BY_DATA_AVAILABILITY` | The sequence slicer creates `DERIVED_REPLAY` windows from one export; production evolution requires verified sequential upstream snapshots. |
| Directed topology P2 semantics | `READY` only for compatible synthetic inputs | `PASS` | `PASS` | `PASS` synthetic Docker stack | `UNAVAILABLE` | IP is structural adjacency and IT is unverified source relation. Display hierarchy never supplies dependency direction, active paths, dominators, propagation, or failure domains. |
| Real topology navigation read model | `READY` | `PASS` | N/A | `PASS` local mock endpoint + Chromium tree preview | `READY` for source-record navigation only | `ALARM_ONLY` has no topology; IP is undirected adjacency; IT is `DIRECTED_SOURCE_RELATIONS`, not verified dependency. The bounded tree has free-text search and an exact source-key resolver; both are navigation only. Tree primary paths are technical projection only. The full Explain snapshot workflow remains separately input-dependent. |
| P2-eligible alarm-to-topology mapping | `PARTIAL_EXACT_ONLY` for IP; `UNAVAILABLE` for IT | `PASS` | N/A | N/A | `UNAVAILABLE` as a complete P2 prerequisite | The current `alarmIP`/`topoIP` audit resolves 140,596/212,636 rows (66.121%) by exact `device_code` identity, covering 1,294/2,908 distinct alarm device codes. `topoIT` source-field joins have substantial navigation coverage (measured separately below), but are not promoted to P2-eligible mappings without authoritative business semantics. |
| IP `Dep_hop` proximity evidence | `READY` for exact-mapped IP endpoints | `PASS` | N/A | `PASS` targeted Kafka/PostgreSQL/API smoke | `PARTIAL_EXACT_ONLY` | Real `alarmIP` replay carries a content-hashed topoIP provenance; a mapped adjacent pair returns `Dep_hop=SUPPORT`. This is undirected hop proximity over `IP_ADJACENCY`, never upstream/dependency direction. |
| IT source-relation contribution to Explain P2 | `UNAVAILABLE` | `PASS` fail-closed | N/A | N/A | `UNAVAILABLE` | `SOURCE_RELATION` / `UNVERIFIED` IT records must not enable dependency, ancestor, dominator, propagation, scope, or failure-domain semantics. |
| Synthetic operator-feedback fixture | `READY` | `PASS` | `PASS` | N/A | `NOT_CALIBRATED` | Typed accepted/rejected labels exercise empirical-evaluation input only. It is `SYNTHETIC_TEST` and explicitly cannot serve as production ground truth. |
| Counterfactual `REMOVE_MEMBER`, `SPLIT_CHAIN`, `MOVE_MEMBER`, connector annotation | `READY` | `PASS` | `PASS` | `PASS` Kafka/PostgreSQL/restart/Chromium | `NOT_CALIBRATED` | Proposal-only; feedback is persisted evaluation data and cannot mutate NocPro. Production recommendation policy requires operator corrections/calibration. |
| Counterfactual `MERGE_CHAINS` | `READY` | `PASS` | `PASS` | `PASS` Kafka/PostgreSQL/restart/Chromium | `NOT_CALIBRATED` | Exact cross-chain evidence and persisted Review reload have runtime acceptance. |
| Counterfactual `ADD_MEMBER` | `BLOCKED` | N/A | N/A | N/A | `BLOCKED` | `UNKNOWN_UPSTREAM_SEMANTICS`: first-class zero-membership alarms have not been verified upstream. A singleton-source transfer is canonical `MOVE_MEMBER`, never ADD. |
| NocPro Assistant registry/search/navigation + grounded LLM rendering | `READY` (ADR-0024 epistemic boundaries) | `PASS` OpenAI-compatible/Ollama codecs, provider fallback, API/UI contract | `PASS` native Ollama Cloud smoke (`gpt-oss:120b`, HTTP 200) | `PASS` full-stack deterministic fallback; live Ollama smoke tested separately | `READY` for deterministic read-only navigation; optional LLM is narrative-only | Every action is built deterministically, bound to an exact snapshot/version, and validated again by the client. The server-side LLM may render only the message from bounded facts; failure returns the deterministic draft. Real replay + Assistant Chromium passed under fallback, while the explicit native Ollama `/api/chat` codec passed a separate bounded live smoke. Pair WHY actions require two current same-chain members; assistant Review navigation can display only a persisted Review and never submits a job. |
| IT source-field topology joins | `READY` for structural navigation; excluded from P2 mapping | `PASS` | `PASS` | `PASS` resolver unit/HTTP contract + real IT Chromium navigation | `PARTIAL_SOURCE_FIELD_EXACT` for navigation; `UNAVAILABLE` for P2 promotion | The resolver opens only unambiguous source fields in the bounded relation tree and returns `p2_mapping_eligible=false`. The real files yield 169,836/258,344 uniquely resolved alarm rows (65.740%), 44,992 multi-resource conflicts, 441 rows touching an ambiguous alias, and 43,106 rows with no alias hit. These exact source-record joins are useful, but their direction and business meaning remain unverified. |

## NocPro Assistant boundary

ADR-0024 enforces strict epistemic boundaries on operator narrative generation.
The legacy AI Advisor compatibility endpoint first projects deterministic,
evidence-bound facts: verified member roles (`support`, `representativeness`),
descriptors, and evaluated Pareto recommendations. An optional server-side
provider may render only the narrative text through an explicit
`OPENAI_COMPATIBLE` or `OLLAMA` wire protocol. The native Ollama adapter uses a
non-streaming `/api/chat` response and ignores thinking/tool fields. Missing or
failed provider access returns the exact deterministic draft with a stable,
non-secret `provider_status`.

The NocPro Assistant extends this with a snapshot-bound Semantic Registry and
an allowlisted deterministic tool router. It can explain registered concepts,
search active chain IDs/titles, and return typed internal navigation actions.
The same optional provider may render the already-resolved message, but cannot
create or modify the response status, fact references, actions, or targets.
It cannot issue SQL, network, arbitrary URL, Deep Dive, Review, Apply, or
feedback actions. A stale snapshot identity returns `STALE_CONTEXT`; missing
resource-to-chain mapping returns
`RESOURCE_TO_CHAIN_MAPPING_UNAVAILABLE`, never a topology-derived guess.

LLM availability does not fill data or algorithm boundaries. It cannot make
production H available without authoritative taxonomy and verified historical
episodes; it cannot provide exact indexed full-chain `T_delay` statistics; and
it cannot establish topology dependency semantics, operator ground truth, or
production calibration.

Every navigation target contains a non-empty `snapshot_id` and
`snapshot_version`; the React client rejects a target for any other active
snapshot. Pair WHY navigation additionally requires two distinct member IDs of
the target chain. Assistant-triggered Review navigation is display-only: it
loads a compatible persisted Review if one exists and returns `NOT_RUN` in the
panel if it does not. It never uses the normal operator path that may submit a
new Review job.

## Topology hierarchy and alias mapping boundary

`topology_hierarchy.py` supplies display ordering only for `STRUCTURAL_NAVIGATION`.
It is forbidden from supplying P2/RCA dependency direction, common ancestor,
dominator, active-path, propagation, scope-overlap, or failure-domain inputs.
Promotion into P2 requires a separate authoritative business semantics source,
verified alarm-resource mappings, and versioned provenance/configuration.

The one real topology exception is bounded `Dep_hop` proximity: exact-mapped
IP alarms can use versioned, undirected `IP_ADJACENCY` to report hop distance.
That distance does not promote the graph to directed dependency semantics.

`build_it_resource_mapper()` strictly excludes `topoIT` alias join columns from
acting as P2-eligible production alarm mappings; colliding aliases fail-closed
to `AMBIGUOUS`. Alias fields remain structural navigation helpers only. This
does not mean that the files have little overlap: a complete row-level audit of
the local `alarmIT.csv` and `topoIT` source tables found 169,836 uniquely
resolved rows out of 258,344 (65.740%). Another 44,992 rows produced more than
one resource candidate and therefore cannot be collapsed to one resource
without a separately frozen resolution rule; 43,106 rows had no exact alias
hit. The loader extracted 111,311 unambiguous aliases and 161 ambiguous aliases
over a normalized graph of 128,322 nodes and 218,635 source-relation edges.
The separate `GET /api/topology/resolve` read model exposes those exact,
unambiguous aliases only to open a bounded tree root. Its payload makes the
boundary explicit: IT returns `p2_mapping_eligible=false` and
`dependency_semantics=UNVERIFIED`; ambiguous aliases stay unavailable.

For IP, exact canonical `device_code` identity resolves 140,596 of 212,636
alarm rows (66.121%) and 1,294 of the 2,908 distinct alarm device codes. This
mapping can support bounded undirected `Dep_hop` proximity. It still does not
establish directed dependency, active path, dominator, propagation, or failure
domain semantics.

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

The indexed representation persists `fit=None` together with the explicit
unavailable reason `NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH`; clients must
not infer the reason from a null fit. This is an intentional capability
boundary, not a deferred dense fallback.

## Closure benchmark and acceptance harness

- `benchmarks/run_benchmark.py` measures the current real-export Tier-1 / Tier-2 exact matrix.
- `benchmarks/run_closure_benchmark.py` projects only persisted benchmark
  artifacts into the complete closure manifest. It intentionally records
  attribution/deletion, merge-cross-evidence, serialization, and persistence
  as `NOT_RUN` when no isolated timing exists; it never manufactures a number
  from a parent operation or a source-code constant. A measurement is accepted
  only with finite non-negative P50/P95 values, `P50 <= P95`, explicit positive
  repetitions, and an explicit P95-reliability flag; missing fields never
  default to a reliable P95 or 20 repetitions.
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
invent taxonomy; that baseline remains fail-closed. The Docker acceptance run
passed on 2026-09-04: migration/runtime failure tests (6), P2 Kafka tests (3),
Evolution Chromium (1), H/T_delay model tests (18), Counterfactual
Kafka/PostgreSQL/restart (1), Counterfactual Chromium (1), raw-export replay,
and generic Pair WHY Chromium/operator flow.
The raw-export replay path uses
`nocpro-mock/datasets/raw/alarm/alarm_data.csv` when that file is mounted into
the Docker producer. H/T_delay Pair WHY through the production-shaped
service/API remains `NOT_RUN`; the model suite does not establish that separate
capability.

## Production evidence still required

The following are external evidence acquisition items, not implementation
defaults:

- authoritative alarm TYPE/FAMILY/CATEGORY taxonomy;
- verified sequential production snapshots;
- operator-confirmed chain corrections for recommendation evaluation and policy calibration;
- completion and authoritative qualification of alarm-to-topology resource
  mappings (the local files already provide substantial partial exact joins);
- directed dependency/path semantics and, where needed, dominator/path truth;
- failure-domain ground truth.

The three available production exports are not treated as a sequential snapshot
series. No overlap threshold, topology direction, taxonomy, or production
recommendation threshold is inferred from them.

### Measured local raw-export Tier-1 / Tier-2 matrix

`benchmarks/run_benchmark.py` was run on 2026-09-04 against the local raw
export (`8,714` alarms, `2,824` chains). This is a local performance
characterisation, not a production SLO or empirical recommendation validation.

The current repeatable matrix uses 20 observations per Tier-1B/Tier-2
workload; its observed nearest-rank P95 is therefore marked reliable by the
benchmark harness. Requested sizes select the nearest available chain.

| Requested size | Actual chain size | Tier-1B cold-open P95 | Cache-hit P95 | Pair WHY P95 | Exact Tier-2 Audit P95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 58 | 42 | 0.0475 s | < 0.0001 s | 0.0001 s | 0.1808 s |
| 200 | 215 | 0.1234 s | < 0.0001 s | 0.0003 s | 2.1295 s |
| 500 | 256 | 0.1334 s | < 0.0001 s | 0.0003 s | 3.0592 s |
| 1072 | 1072 | 0.4546 s | 0.0001 s | 0.0012 s | 101.0488 s |

The full-snapshot Tier-1A background precompute measured P95 `1.0390 s`
(three repetitions; the report correctly labels that P95 as not statistically
reliable) and peak process allocation `2.83 MB` for its single memory sample.
The architectural 1072-member anti-dense test passed separately (`3 passed`).

Each exact Tier-2 timing includes the existing Structural Audit call path,
including exact indexed attribution and deletion evaluation. The 1,072-member
chain `6907125` returned `NO_LOW_CONDUCTANCE_CUT`; attribution and deterministic
deletion evaluation returned `AVAILABLE` / `EXACT` throughout the measured
path. This is a machine-local performance characterisation, not a production
SLO or a calibration result.

The persisted synthetic Review benchmark artifact
(`benchmarks/results/counterfactual-latest.json`) ran 20 repetitions per
operation: `REMOVE`, `SPLIT`, `MOVE`, and `MERGE` all retained exact repair
accuracy, ARI, and AMI of `1.0`; combined Review latency P50/P95 was
`0.2444 s` / `0.6711 s`. This is synthetic correctness/performance only. A separate local
Docker runtime benchmark restarted the API 20 times and then hydrated the
persisted MOVE Review on every restart: restart-to-health P50/P95 was `1.2203 s`
/ `1.2261 s`, and repository-backed Review hydration P50/P95 was `0.0472 s` /
`0.0710 s`. Those timings are acceptance-stack characterisation, not a
production SLO.
