# nocpro-chain-explain

Explanation, audit and validation for NocPro alarm chains.

Methodology is frozen in `docs/NocPro5_Alarm_Chain_Explanation_V2.3.1_FINAL_D1_CAMERA_READY.md`
plus 32 ADRs in `docs/adr/`. Where code and a frozen ADR disagree, the code is
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
| Tier-1A precompute + Tier-1 cache | MVP | done |
| Explanation Drift (Tier-1A basic) | P1-Core | done |
| **MVP complete** | | **8/8** |
| Basic structural audit: audit graph, deterministic cuts, conductance | P0 | done |
| Multi-evidence over-merge verdict | P1-Core | done |
| STRUCTURAL role (CONNECTOR/NON_CONNECTOR), REDUNDANCY role | P0/§4B | done |
| CommonDependency: SHARED_ANCESTOR + SHARED_ACTIVE_PATH (`channels/common_dependency.py`) | P1-Core | done |
| Similar Chains: fingerprint + cosine baseline (`similar_chains/`) | P1-Core | done |
| **P1-Core (3+1) feature set implemented** | | **4/4** |
| Contrastive top-3 UI, benchmarks, incremental indexing | P0 | not started |
| UNAVOIDABLE_DEPENDENCY (dominator), graph motif upgrade | P2 | not started |
| HTTP API, web UI, persistence/migrations | infra | not started |

Per ADR-0029, MVP + P0-complete must stand as a usable project **before** P1.
The P1-Core feature set above is implemented, but the **P1 milestone is not
closed**: several P0 acceptance items (contrastive top-3 UI, benchmarks,
incremental indexing) are still outstanding. Next steps are closing those P0
items, then integration/full-real-data run/benchmark/evaluation/UI — not
further P1-optional or P2 work.

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
../nocpro-mock/.venv/bin/python -m pytest tests            # all
../nocpro-mock/.venv/bin/python -m pytest tests/spec_sanity  # methodology firewall
../nocpro-mock/.venv/bin/python -m pytest tests -m "not realdata"
```

`tests/spec_sanity/` is not an ordinary suite: a failure means the code
contradicts a frozen methodological invariant. Fix the code, or revise the
spec/ADR first and deliberately.

End-to-end tests shell out to the sibling `nocpro-mock` CLI, so the adapter is
exercised against real emitted packages rather than hand-written payloads. They
skip when the sibling repo or the 680 MB exports are absent.

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
- Cache key is `(chain fingerprint, snapshot, config version)`. The fingerprint
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
- CommonDependency (`Dep_upstream`) distinguishes `SHARED_ANCESTOR <
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
