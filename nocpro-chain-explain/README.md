# nocpro-chain-explain

Explanation, audit and validation for NocPro alarm chains.

Methodology is frozen in `docs/NocPro5_Alarm_Chain_Explanation_V2.3.1_FINAL_D1_CAMERA_READY.md`
plus 33 ADRs in `docs/adr/`. Where code and a frozen ADR disagree, the code is
wrong (see `docs/adr/README.md`).

## Status

Scope follows ADR-0029: MVP and P0-complete must stand on their own before P1.

| Component | Scope | State |
|---|---|---|
| Input Contract v1 (`contracts/v1`) | MVP | done |
| Direct Snapshot Adapter ingest (`libs/contracts`) | MVP | done |
| Provenance / eligibility / derivation grouping (`libs/provenance`) | MVP | done |
| Gray-box NocPro Metadata Adapter + System Fact box | MVP | done |
| Singleton first-class path (`\|C\|=1`) | MVP | done |
| `K_pair` channels: `E_*`, `S`, `T_burst`, `T_delay`, `Dep_hop` | MVP | done |
| `Fit_k` / `Fit_g` / MembershipSupport + role gate | MVP | done |
| Descriptor bitmap: IDENTITY + CONTRASTIVE, full metric set | MVP | done |
| Representativeness + `Margin_common` (role self-contained) | MVP | done |
| Auto chain title from top IDENTITY descriptor | MVP | done |
| Tier-1B chain analysis orchestration | MVP | done |
| Evolution: lifecycle, lineage, events, joined/left decomposition | MVP | done |
| Global persisted episode-DAG lineage + canonical merge aliases | infra/P1 | done |
| Tier-1A precompute + Tier-1 cache | MVP | done |
| Explanation Drift (Tier-1A basic) | P1-Core | done |
| **MVP complete** | | **8/8** |
| Basic structural audit: audit graph, deterministic cuts, conductance | P0 | done |
| Tier-2 async per-chain job boundary + versioned cache | P0 | done |
| Multi-evidence over-merge verdict | P1-Core | done |
| STRUCTURAL role (Tier-2), REDUNDANCY role (Tier-1B) | P0/§4B | done |
| CommonDependency: SHARED_ANCESTOR + SHARED_ACTIVE_PATH (`channels/common_dependency.py`) | P1-Core | done |
| Similar Chains: fingerprint + cosine baseline (`similar_chains/`) | P1-Core | done |
| Similar Chains production index (`history<t`, snapshot-versioned model) | P1-Core | done |
| Evidence Coverage Attribution (exact indexed, derivation-group level) | P1-optional | done; fail-closed above configured ceiling |
| Counterfactual Chain Review P0 + P1.1 (`REMOVE_MEMBER`, exact-Audit `SPLIT_CHAIN`, `MOVE_MEMBER`) | review extension | implemented; synthetic correctness verified, production calibration not established |
| **P1-Core (3+1) feature set implemented** | | **4/4** |
| Contrastive top-3: per-candidate `Margin_common` (§5, §11) | P0 | done |
| Hybrid indexed Tier-1B + pairwise oracle | P0 | done |
| Exact incremental predicate index + reconciliation triggers | P0 | done |
| Benchmark matrix + overlap measurement tooling | P0 | implemented; Tier-1 real run recorded |
| Production delta-default policy/threshold | P0 | `BLOCKED_BY_DATA_AVAILABILITY`; implementation ready, empirical threshold not established, mode disabled |
| P2 topology foundation: UNAVOIDABLE_DEPENDENCY annotation, PROPAGATION_HYPOTHESIS, DEPENDENCY_SCOPE_OVERLAP_SIGNAL | P2 | implemented; production capability fail-closed |
| Graph motif upgrade and remaining P2 extensions | P2 | not started; data/capability gated |
| FastAPI adapter: snapshot ingest, Tier-1B, pair WHY, Tier-2 polling | infra | done |
| React/Vite/TypeScript operator UI | infra | done |
| PostgreSQL persistence + Alembic migrations | infra | done |
| Kafka chunk/barrier ingest (`nocpro-mock` -> Explain) | infra | done |
| Docker Compose: PostgreSQL, Kafka, API, Web, replay producer | infra | done |
| Docker + Chromium operator-flow and recovery acceptance | infra | done |

Per ADR-0029, MVP + P0-complete must stand as a usable project **before** P1.
The P1-Core feature set above is implemented, but the **P1 milestone is not
closed**: production-delta validation is externally blocked because consecutive
production snapshots do not exist. The incremental implementation is ready,
but its empirical policy threshold is not established and production remains
full-rebuild by default. The P2 topology foundation was explicitly opened by
ADR-0033 after the scope amendment. Its implementation is present and tested
on directed synthetic fixtures, while the current production topology remains
unable to provide the required directed semantics, so production results stay
`UNAVAILABLE`. Remaining P2 extensions are still `NOT_STARTED` and data/
capability gated.

### Alarm taxonomy source capability

The current production source does not operationally use `alarm_type_name`, so
its null values are expected rather than a data-quality defect. No canonical
`alarm_family` source exists and the system never infers one from `alarm_name`.
Similar Chains therefore labels the taxonomy block `UNAVAILABLE` with reason
`ALARM_TAXONOMY_NOT_USED_BY_SOURCE`, while continuing in degraded mode with
device type, IDENTITY descriptors, size bin and duration bin. A future real,
versioned taxonomy adapter can enable the block without changing cosine or the
fingerprint algorithm.

## Layout

```text
contracts/v1/     canonical Input Contract (ADR-0002); nocpro-mock consumes it read-only
libs/contracts/   ingest side of the Direct Snapshot Adapter (ADR-0030)
libs/provenance/  provenance classes, eligibility mask, effective derivation groups
services/analysis-worker/graybox/    Gray-box metadata adapter + singleton path
services/analysis-worker/channels/   K_pair normalized evidence channels
services/analysis-worker/groups/     Fit_g, MembershipSupport, role classification
services/analysis-worker/descriptor/ bitmap mining, metrics, contrastive, representativeness
services/analysis-worker/evolution/  lifecycle, lineage, events, explanation drift
services/analysis-worker/tier1a/     snapshot precompute + Tier-1 cache
services/analysis-worker/tier1b/     per-chain analysis orchestration
services/analysis-worker/audit/      audit graph, candidate cuts, conductance, over-merge
services/analysis-worker/channels/common_dependency.py  SHARED_ANCESTOR, SHARED_ACTIVE_PATH
services/analysis-worker/similar_chains/  fingerprint, TF-IDF, cosine similarity baseline
services/analysis-worker/tier2/topology_hypotheses/  fail-closed P2 topology foundation
services/analysis-worker/tier2/evidence_attribution.py  exact indexed Evidence Coverage Attribution
services/analysis-worker/tier2/counterfactual/  bounded exact review-only alternatives
services/api/nocpro_api/             FastAPI transport and in-process repository boundary
services/api/nocpro_api/ingest/      Kafka v1 wire parser + consumer/coordinator
services/api/nocpro_api/persistence/ PostgreSQL models and snapshot repository
services/web/                        React/Vite/TypeScript operator workspace
migrations/                          Alembic schema history
tests/spec_sanity/                   methodology firewall (ADR-0027)
```

Module dependencies run one way: `channels` -> `groups` -> `libs`. `groups`
never imports `channels`; it consumes a structural `ChannelVerdict` protocol
instead, which keeps the statistical layer independent of evidence production.

`services/analysis-worker` contains a hyphen, so it is not importable as a
package path. `tests/conftest.py` adds it to `sys.path`, which is why tests
import `from channels import ...` rather than a dotted service path.

## Tests

```bash
uv sync
.venv/bin/python -m pytest tests              # all
.venv/bin/python -m pytest tests/spec_sanity  # methodology firewall
.venv/bin/python -m pytest tests -m "not realdata"
TEST_DATABASE_URL=postgresql+asyncpg://nocpro:nocpro@localhost:5432/nocpro \
  .venv/bin/python -m pytest tests/test_postgres_snapshot_ingest.py
pnpm --dir services/web lint
pnpm --dir services/web build
pnpm --dir services/web e2e:install              # one-time Chromium install
./tests/e2e/run_acceptance.sh                 # isolated Docker + Chromium E2E
```

`tests/spec_sanity/` is not an ordinary suite: a failure means the code
contradicts a frozen methodological invariant. Fix the code, or revise the
spec/ADR first and deliberately.

End-to-end tests shell out to the sibling `nocpro-mock` CLI, so the adapter is
exercised against real emitted packages rather than hand-written payloads. They
skip when the sibling repo or the 680 MB exports are absent.

`run_acceptance.sh` uses an isolated Compose project, host ports and PostgreSQL
volume, then cleans them up on exit. It proves the real replay path through
Kafka and PostgreSQL, browser WHY/role/descriptor/deep-dive behavior, and the
missing-chunk, consumer-restart, duplicate-snapshot and expired-lease recovery
cases. Docker failure tests require the explicit `NOCPRO_RUN_DOCKER_E2E=1`
opt-in and therefore cannot control Docker during an ordinary pytest run.

Counterfactual Review has an additional synthetic-only acceptance stage. It
publishes the explicit extra-member, over-merge and misassigned-member fixtures from `nocpro-mock`
through Kafka chunk/barrier, waits for Tier-1A READY, materializes exact Audit,
submits the separate Review job, verifies its PostgreSQL result envelope, then
opens the REVIEW tab in Chromium. These fixtures and
`config/thresholds/e2e-counterfactual.yaml` are labelled `SYNTHETIC_TEST`; they
cannot calibrate or enable a production recommendation policy.

## Behavior worth knowing

- Contract major version mismatches are rejected, not coerced.
- Missing `M_pair` resolves to `UNKNOWN`, never `NEUTRAL`. Under
  `BOUNDED_COMPARISON`, an absent pair means "not compared", not "unrelated".
- Raw NocPro values stay raw: score `2.0` is not clamped and the TimeWindow veto
  keeps `-999999999`. Neither enters a normalized `s_k`.
- Aggregate `pair_count` never synthesizes exact pair edges.
- A derivation group is homogeneous in provenance class and eligibility
  signature; `source_kind` and `chaining_usage` never change grouping because
  they constrain Validate only.
- `G_audit(i,j)` requires audit eligibility **and** availability, so an
  unavailable group never reaches the `w*_audit` denominator.
- Singleton chains are first class: pair/connector/over-merge return
  `NOT_APPLICABLE`, and a singleton is never `WEAK` for lack of pair evidence.
- Absent gray-box metadata means Black-box mode, which is graceful degradation
  rather than an error.
- Channels carry three states: SUPPORT, NEUTRAL (computed, below threshold) and
  UNAVAILABLE (⊥). `|D_k|=0` gives `Fit_k=⊥`, and a failed gate gives
  INSUFFICIENT DATA rather than WEAK.
- `T_delay` uses local probability mass, not a CDF: with modes at ~2s and ~100s a
  CDF would score a 50s delay 1.0 despite that region almost never occurring.
- `T_burst` segments inside a blocking context; a global silent-gap search would
  place a whole national stream in one burst.
- `Dep_hop` requires a resolved alarm→resource mapping; unmapped gives ⊥, and
  PHYSICAL/LOGICAL/SERVICE relation families are never mixed.
- Statistical truth and pair detail are separate. `Fit_k`/`Fit_g`/
  `MembershipSupport`/role read exact counts accumulated over the **full** pair
  space; `pair_detail_limit` bounds only the stored pair listing used for WHY
drill-down and visualization. A verdict is never a function of a display
  budget, and `tests/test_cap_isolation.py` pins that.
- Exact statistics are streaming, so memory is O(members x channels) rather than
  O(pairs). Above `EXACT_STATISTICS_MAX_MEMBERS` the result is flagged
  `statistics_exact=False` so the caller must pick an explicit
  supernode/sparsifier policy instead of degrading silently.
- IDENTITY and CONTRASTIVE are separate search objectives on one bitmap engine.
  A single global precision floor would discard "globally common, locally
  discriminative" rules, which are the answer to "why C1 rather than C2".
- `U_local` includes the target chain plus its top-k competitors. Excluding the
  target forces every local precision to 0.0; `test_local_universe_must_include_the_target`
  pins that.
- All descriptor metrics are reported together. FPR alone is misleading: 30
  inside plus 500 outside of 100k gives FPR 0.5% but precision 5.7%.
- `Representativeness` returns ⊥ when no descriptor was mined, because "unknown"
  is not "atypical".
- Evolution follows membership, not raw chain IDs: `123 -> 984` with identical
  members is CONTINUE. Small chains use the explicit containment/Jaccard
  exception, since a 2-member chain can never reach `n_ij >= 3`.
- Every CONTINUE/GROW/SHRINK reports four decomposition lines, so +10 new and
  -10 cleared shows `delta_size=0` **and** turnover 20 rather than looking static.
- A component with >= 2 parents and >= 2 children stays RECOMBINATION and is
  never forced into a clean split or merge.
- Drift attributes cause explicitly: config-only change reports CONFIG_DRIFT
  ("analysis configuration changed"), never DATA_DRIFT. When both changed it is
  MIXED. Tier-1B/Tier-2 drift requires a cache on **both** snapshots, otherwise
  it reports unavailable rather than "no drift".
- Cache key is `(chain fingerprint, snapshot id, snapshot version, config version)`. The fingerprint
  comes from membership, so identity churn reuses cached work while a threshold
  change invalidates it.
- Tier-1A refuses an incomplete snapshot and computes IDENTITY descriptors only;
  CONTRASTIVE needs `U_local`, which is Tier-1B work.
- The audit graph never runs on the top-K visualization graph. An edge requires
  `>= 2 distinct audit-eligible derivation groups`, enforced where edges are
  actually built, not just at group selection (`test_audit_edge_requires_two_distinct_audit_eligible_groups`).
- `SYSTEM_FACT`/`BEHAVIORAL` channels can never contribute audit weight, even
  with a perfect score.
- Candidate cuts come only from Entity/Dependency/`H_domain`/Descriptor plus
  their union/difference. No second community-detection algorithm runs.
- Counterfactual Chain Review is proposal-only and never mutates the NocPro
  partition. P0 generates bounded deterministic `REMOVE_MEMBER` candidates
  from member triggers and reuses only exact Structural Audit cuts for
  `SPLIT_CHAIN`. P1.1 also generates bounded canonical `MOVE_MEMBER`
  transfers from all source Tier-1B `local_candidates`; MOVE v1 is
  source-local, so canonicalization does not make discovery independent of
  which chain is under Review. For two singleton chains, only the
  stable-greater chain may move into the stable-less chain; Review of the
  stable-less side does not load the peer artifact or emit the reverse move. A
  singleton/non-singleton pair is only represented as singleton-to-chain MOVE.
  A missing
  `Margin_common` is neither zero nor a veto. Candidate
  aggregates are recomputed exactly over affected chains, missing required
  metrics reject the candidate, and REMOVE/SPLIT/MOVE remain independent partial
  results. A missing `counterfactual.move.max_candidates` makes only MOVE
  unavailable. The shipped production config intentionally has no calibrated
  Counterfactual envelope, so production returns
  `COUNTERFACTUAL_CONFIG_INCOMPLETE` rather than using synthetic thresholds.
- `|C| < 10` is `SKIPPED_SMALL_CHAIN`, never `NO_LOW_CONDUCTANCE_CUT`: "too small
  to test" and "tested, found nothing" are different claims.
- Calibration falls back FULL bin -> COARSE bin -> GLOBAL weak baseline rather
  than reporting a threshold with false precision from a handful of samples.
- Over-merge is a 4-line multi-evidence verdict (structural/cross-evidence/
  descriptor/sensitivity). The narrative names the driving evidence and says
  "should review", never "NocPro is wrong".
- STRUCTURAL (CONNECTOR/NON_CONNECTOR) and REDUNDANCY
  (NEAR_DUPLICATE_CANDIDATE/UNIQUE) are independent of the MEMBERSHIP axis; a
  near-duplicate can still be CORE.
- CommonDependency uses one serialized `DEP_UPSTREAM` family with separate
  `DepUpstreamAncestor` and `DepUpstreamActivePath` providers. Both retain a
  `dependency_semantic` enum, while providers backed by the same source/model
  share one derivation tag and therefore cannot cast two audit votes merely
  because both semantic tiers were available. It distinguishes `SHARED_ANCESTOR <
  SHARED_ACTIVE_PATH < UNAVOIDABLE_DEPENDENCY` as a semantic-strength
  ordering, not a numeric constraint on `CD`: a narrow ancestor may score
  higher than a shared active-core-path. Each capability is strictly gated
  (no valid directed hierarchy => SHARED_ANCESTOR is `⊥`; no verified ordered
  active path => SHARED_ACTIVE_PATH is `⊥`); nothing falls back to graph
  adjacency to fabricate a missing capability.
- Specificity is scope-dependent: `Descendants(u)` for SHARED_ANCESTOR,
  distinct traversing resources within the same path-observation universe for
  SHARED_ACTIVE_PATH. ECMP paths of one resource count once, and `N` is scoped
  to the path universe, never the whole topology inventory.
- Similar Chains baseline is cosine similarity over a TF-IDF(family) +
  TF-IDF(device_type) + descriptor + size/duration-bin fingerprint.
  `device_type_name` is used verbatim, never guessed from a device-code prefix.
- Alarm-family resolution is FAMILY (real taxonomy) -> TYPE_FALLBACK
  (`alarm_type_name`, explicitly labeled, not the T_delay/H backoff rule) ->
  no term. FAMILY/TYPE_FALLBACK values are namespaced so they can never
  collide in the vocabulary even with identical spelling.
- All fingerprints compared in one request must share one `FingerprintModel`
  (one `model_version`); scoring a fingerprint stamped under a different
  version raises `ModelVersionMismatch` rather than silently mixing vector
  spaces.
- Each `SimilarChainResult` reports `compared_blocks`, so a `similarity=1.0`
  between two chains scored on a reduced basis (e.g. two singletons with no
  taxonomy) can be shown as "basis: N/5 feature blocks", not an unqualified
  confidence number.
- The nearest "different incident" result excludes the same
  `lineage_component_id`; a separate "previous states of this chain" mode
  returns exactly those matches instead. Equal-similarity ties break
  deterministically by `chain_id`.
- WHY-4 contrastive is bounded to top-3 blocking candidates (§5, §11), not the
  whole `U_local`. Each member gets one `Margin_common` per candidate
  (`MemberAnalysis.margins`); `.margin` is kept as a backward-compatible alias
  for the closest candidate only.

### P2 topology foundation

ADR-0033 opens three independent Tier-2 topology semantics:

- `UNAVOIDABLE_DEPENDENCY`: an exact common strict-dominator annotation with a
  witness and provenance, without a normalized score, audit vote, membership
  contribution or validation vote.
- `PROPAGATION_HYPOTHESIS`: a directed, temporally ordered candidate DAG
  ranked by the fully versioned configured RWR contract. It is a hypothesis
  ranking, not causal proof or a root-cause claim; missing direction, mapping,
  timestamps or required configuration fails closed.
- `DEPENDENCY_SCOPE_OVERLAP_SIGNAL`: exact coverage, precision, Jaccard and
  missing/extra counts anchored to the selected dominator witness. Computation
  and detail-materialization ceilings are separate, and no partial resource
  list is emitted.

The current production export exposes undirected `IP_ADJACENCY` only. It has
partial exact `alarmIP`→`topoIP` identity coverage for bounded `Dep_hop`
proximity, but no complete mapping contract, verified directed topology/path,
or propagation configuration. Consequently the production API/UI reports the
directed P2 capabilities as
`UNAVAILABLE`; synthetic directed fixtures verify the implementation contract
but are not production validation. Graph motifs, `UNAVOIDABLE_DEPENDENCY` as a
normalized evidence channel, and other P2 extensions remain not started until
their documented data/capability gates are met.

Every topology-derived capability also requires an exact record-level source
identity. `source_id` and `source_version` identify the topology model, while
`scenario_id` and `generator_version` identify how a synthetic fixture was
generated; neither pair is a fallback for the other. A foreign payload missing
the topology source version keeps the snapshot and Tier-1A usable, but topology
channels and P2 return `TOPOLOGY_SOURCE_VERSION_MISSING`. The producer rejects
such synthetic scenarios before Kafka publication.

## API

The HTTP layer is an adapter over the existing analysis services; it does not
reimplement channel or audit semantics. Start it from this directory with:

```bash
PYTHONPATH=.:services/analysis-worker:services/api \
  .venv/bin/uvicorn nocpro_api.app:app \
  --app-dir services/api \
  --host 127.0.0.1 \
  --port 8000
```

Load one canonical Input Contract v1 package with `POST /api/v1/snapshots`,
then use `/api/v1/chains`, `/api/v1/chains/{chain_id}`, pair WHY, and the
Tier-2 submit/poll endpoints under `/api/v1`. Snapshot replacement performs a
full exact precompute because `incremental_snapshot.mode` is deliberately
disabled until consecutive production snapshots are available.

Review uses its own lazy job boundary:

```text
POST /api/v1/chains/{chain_id}/review
GET  /api/v1/review-jobs/{job_id}
GET  /api/v1/chains/{chain_id}/review
```

The convenience GET returns only a result compatible with the current
snapshot, Tier-1B/Audit artifact fingerprints, engine and config. Job identity,
progress, terminal result and artifact fingerprints are persisted in
PostgreSQL; domain-level `UNAVAILABLE` is a successful job result, while an
unexpected infrastructure exception is `FAILED`.

Run the frontend in another terminal:

```bash
cd services/web
pnpm install
pnpm dev
```

Vite proxies `/api` to `127.0.0.1:8000`. Production Evolution remains
`UNAVAILABLE` until verified sequential production snapshots exist. A verified
`SYNTHETIC_TEST` sequence may render the persisted lineage artifact in
development/E2E, with provenance and `production_validation=NOT_ESTABLISHED`;
it never infers lineage from unrelated exports or enables production Evolution.

## Docker Kafka integration

The Docker path uses PostgreSQL as the durable source of truth and Kafka as the
transport from the sibling `nocpro-mock` producer. A snapshot is compressed,
split into `SNAPSHOT_CHUNK` events, and closed by a `SNAPSHOT_COMPLETE` barrier.
Explain marks it complete only after all unique chunks, per-chunk checksums,
the whole-snapshot checksum, and the canonical Input Contract pass validation.
Completion triggers Tier-1A exactly once through the persisted claim; Tier-1B
remains lazy and runs only when a chain is requested.

Chunk retention is an explicit deployment policy under
`ingest.chunk_retention.mode`. Production `config/thresholds/v1.yaml` uses
`KEEP`. `DELETE_AFTER_READY` is available for local/synthetic deployments: its
transaction deletes chunks only after canonical payload persistence, ingest
`COMPLETE`, and the Tier-1A transition to `READY`. There is no implicit
time-based retention for completed snapshots. Cleanup is idempotent and never
removes the canonical snapshot, lineage, similarity, Audit, or Review records.

After Tier-1A, recovery processes global lineage and Similar Chains strictly in
logical snapshot order: `READY -> LINEAGE_PENDING -> LINEAGE_READY ->
SIMILAR_READY`. The persisted episode DAG uses `(snapshot_id,
snapshot_chain_id)` nodes, deterministic component IDs, and canonical aliases
when previously separate episodes merge. Similarity remains `UNAVAILABLE` with
reason `LINEAGE_NOT_READY` until that pipeline completes; it never drops the
same-lineage filter as a fallback.

Tier-1A recovery uses logical snapshot order, not arrival order:

```text
ACTIVE  = latest READY by snapshot_time, completed_at, snapshot_id
PENDING = claimed oldest-first by snapshot_time, completed_at, snapshot_id
RUNNING = reclaimable only after lease_expires_at
FAILED  = terminal after 5 total Tier-1A attempts
```

`completed_at` is only a tie-break/fallback; a delayed replay with an older
`snapshot_time` cannot replace a newer active snapshot. Startup hydrates the
latest logical READY snapshot first, then a background worker resumes PENDING
and expired-lease jobs with `FOR UPDATE SKIP LOCKED`. A newer PENDING/RUNNING
snapshot never blocks the UI from serving the current READY snapshot.
Tier-1A failures preserve logical order and retry after 2, 4, 8, then 16
seconds. A fifth failed attempt becomes terminal `FAILED`; recovery then moves
to the next logical snapshot. The attempt ceiling and base delay are configured
by `TIER1A_MAX_ATTEMPTS` and `TIER1A_BACKOFF_BASE_SECONDS`.

The Kafka envelope is bounded before persistence: at most 1,024 chunks, 4 MiB
per decoded chunk, 256 MiB compressed in retained chunks, and 256 MiB
uncompressed per snapshot. RECEIVING assemblies expire after 24 hours and
their retained chunk bytes are deleted. All five ceilings are configurable
through the corresponding `KAFKA_*` environment variables in
`docker-compose.yml`.

Start the main stack:

```bash
docker compose up -d api web
curl http://localhost:8000/api/v1/health
```

The UI is then available at `http://localhost:3000`. To replay the real export
from `nocpro-mock` through Kafka:

```bash
MOCK_SNAPSHOT_ID=docker-replay-001 \
MOCK_SNAPSHOT_VERSION=1 \
docker compose --profile replay run --rm mock-producer
```

The producer and consumer use `snapshot_id` as the Kafka key. Identical chunk
replays are idempotent; a conflicting duplicate invalidates the snapshot. HTTP
snapshot ingest remains available for development and writes through the same
canonical PostgreSQL repository.

The isolated acceptance was completed on 2026-08-30 with a read-only Compose
override mounting the exact real exports from the sibling `nocpro-mock`
checkout. Snapshot `acceptance-real-20260830T024315Z` passed the full replay
path, both Chromium operator tests (`2/2`), all four Docker recovery tests
(`4/4`), and the 1,072-member Tier-1B request in `1.217181s`. The complete
acceptance run took `70.73s`, and the isolated containers, network and volume
were cleaned up successfully. The export mount is an environment precondition
for replay; a plain worktree run without that external mount cannot locate
`datasets/raw/alarm/alarm_data.csv`. This is local-run evidence, not a production
SLO or production-data validation.

The acceptance runner additionally publishes a deterministic versioned
synthetic directed topology through the same Kafka chunk/barrier and PostgreSQL
path. It verifies available dominator, configured propagation and exact scope
output with all four provenance fields, then publishes a foreign unversioned
variant and verifies Tier-1A remains READY while all affected P2 capabilities
fail closed. This uses `config/thresholds/e2e-p2.yaml`, which is explicitly
synthetic acceptance configuration; production continues to use
`config/thresholds/v1.yaml` and does not acquire uncalibrated P2 defaults.
On 2026-08-31 the full acceptance was rerun with the authoritative external
real-export directory mounted read-only into this worktree's mock producer.
Chromium operator/singleton flows passed (`2/2`), recovery and ingest failure
cases passed (`4/4`), and synthetic topology Kafka/P2 cases passed (`3/3`). The
1,072-member Tier-1B request completed in `0.826174s`. The runner cleaned its
isolated containers, network and PostgreSQL volume. The mount changes only the
location from which `nocpro-mock` reads the existing export; it does not replace
or synthesize production replay data.

On 2026-09-02 the isolated Counterfactual stage was run independently because
this feature worktree did not contain the external real-export mount needed by
the full replay stage. The synthetic Counterfactual fixtures passed the real
Mock → Kafka → PostgreSQL → Explain path (`1/1` combined Docker test), and the
Chromium REVIEW flow passed (`1/1`) with no console errors and no Apply control.
Review is proposal-only: operator feedback is persisted for evaluation and
cannot dispatch a NocPro mutation. The synthetic benchmark, five repetitions
per fixture, reported issue detection `1.0`,
exact repair `1.0`, clean false-recommendation rate `0.0`, clean abstention
`1.0`, mean ARI `1.0`, mean AMI approximately `1.0`, median end-to-end local
analysis latency `0.163s`, and maximum `0.259s`. These are small synthetic
correctness/latency measurements, not a production threshold or SLO. The
isolated containers, network and PostgreSQL volume were removed after the run.

The unresolved external gates are recorded explicitly:

```text
PRODUCTION_DELTA_VALIDATION = BLOCKED_BY_DATA_AVAILABILITY
implementation              = READY
empirical_threshold          = NOT_ESTABLISHED
incremental_snapshot.mode    = disabled
P2 topology foundation      = IMPLEMENTED / PRODUCTION_UNAVAILABLE
remaining P2 extensions     = NOT_STARTED / DATA_AND_CAPABILITY_GATED
counterfactual review P0    = IMPLEMENTED / SYNTHETIC_CORRECTNESS_VERIFIED
production review policy    = NOT_CALIBRATED / FAIL_CLOSED
```
