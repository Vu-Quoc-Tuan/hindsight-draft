# Hindsight Feature Capability Matrix

## 1. Purpose and reading rules

This document is the developer-facing inventory of analytical features, evidence,
derived artifacts, learning signals, UI projections, and LLM grounding currently
present in `nocpro-mock` and `nocpro-chain-explain`.

It deliberately distinguishes the following states:

- **Implemented**: code or a contract exists.
- **Active**: the current runtime path actually produces or consumes it.
- **Conditional**: active only when its required data/model/capability is available.
- **Persisted**: written to a durable store or versioned artifact.
- **UI**: exposed in the web application.
- **LLM-grounded**: included in the bounded structured facts sent to the narrative renderer.
- **Production-eligible**: evidence and governance gates allow operational use. This is not implied by implementation or tests.
- **Incomplete**: partially connected, semantically unsafe, missing migration/read-back, or otherwise not ready to be treated as complete.

`UNAVAILABLE` means the system cannot compute a claim from the supplied evidence.
It must never be silently converted to `NEUTRAL`, zero, `WEAK`, or a negative
finding. `NOT_APPLICABLE` means that the computation is not meaningful for the
current object, such as pair-based analysis for a singleton.

## 2. Master capability matrix

### A. Input, normalization, identity, quality, and provenance

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
|---|---|---|---|---|---|---|---|---|
| Snapshot identity | Primary versioned processing boundary: `snapshot_id + snapshot_version` | Source snapshot metadata | Mock producer, direct ingest, Kafka ingest | Tier-1A, workspace selection, every downstream artifact | PostgreSQL; snapshot APIs and header; not directly LLM-grounded | Snapshot must be complete and contract-valid | A chain ID is snapshot-scoped, not a global incident identity | **Active, persisted** |
| `TopologyRef` | Binds a snapshot to `profile_id`, `topology_version`, source version/hash | Ingested topology metadata | Mock topology builders and topology ingest | Navigation, topology hypotheses, version selection | Snapshot contract; topology APIs/UI; not LLM-grounded | Exact compatible profile/version required | A topology reference does not prove dependency or causality | **Active, conditional** |
| Raw alarm preservation | Retains every source column verbatim for reconstruction and audit | Original alarm row/payload | Alarm loader | Dataset explorer, adapters, new entity resolver, later analysis | Snapshot payload/PostgreSQL; some fields projected to API/UI; not sent wholesale to LLM | Always retained when ingestion succeeds | Stored data is not automatically an analytical feature | **Active, persisted** |
| Canonical alarm identity | Stable `alarm_id` within snapshot | Source alarm ID | Alarm loader/normalizer | Membership, pair evidence, Review, lineage | Persisted and exposed broadly | Must be non-empty and unique within snapshot | Alarm ID alone has no causal meaning | **Active** |
| Canonical time | Parsed `canonical_start_time` and `canonical_end_time` while preserving raw timestamps | Raw start/end/create time | Alarm loader | Temporal channels, timeline, duration, redundancy, evolution | Persisted; APIs/UI; currently not part of Advisor grounding | Parse success required; missing time remains unavailable | Earliest timestamp is an observed onset, not root cause | **Active, conditional** |
| Canonical entity fields | `device_code`, `node_reference`, component, site, remote node and related source fields | Raw alarm columns | Loader and active-field projection | Entity channels, mapping, descriptors, UI | Snapshot/index/API; selected fields visible | Empty/missing values yield unavailable channel results | Equal strings support co-location only | **Active** |
| Alarm taxonomy fields | Alarm name, type, family/category adapters, group and fault fallbacks | `alarm_name`, taxonomy, type/group/fault fields | Taxonomy adapters | Semantic `S`, historical evidence, T-delay, fingerprint | Model/artifact dependent; some labels shown | Authoritative compatible taxonomy required for family/category claims | A keyword or fallback category is not root-cause classification | **Conditional** |
| `quality_flags` | Machine-readable parse/missing/dirty-data facts | Loader diagnostics | Normalizer/indexer | Dataset/API diagnostics and evidence gating | Persisted and exposed by alarm APIs; not Advisor-grounded | Generated whenever input quality issue is observed | Quality flags describe input reliability, not incident severity | **Active** |
| `source_kind` | Separates `REAL_LIVE`, `REAL_EXPORT_REPLAY`, `SYNTHETIC_TEST`, and other origins | Snapshot/source metadata | Ingest | Provenance gates, ranker features, UI labels | Persisted; API/UI; not normally narrative content | Required by source-kind eligibility policies | Synthetic correctness is not production validation | **Active** |
| Provenance class/subtype | Distinguishes external operational, post-hoc, synthetic, asserted, and topology evidence | Source and generator metadata | Contract adapters | Explain/role/audit eligibility and UI attribution | Persisted in relevant records; exposed selectively | Must satisfy the consumer's provenance mask | Two fields from one source are not independent evidence | **Active** |
| Generation metadata | Records scenario, seed, generator version/rule and base fixture | Synthetic/mock generation | Scenario generators | Provenance validation and tests | Snapshot contract; limited UI | Required for generated evidence | Generated labels cannot be presented as observed production truth | **Active for generated data** |
| Versioned analysis configuration | Threshold values plus source category and config version | YAML/config API | Configuration loader | Every thresholded analysis | Config endpoint/UI and artifact metadata | Missing/incompatible config fails closed | Documented defaults remain hypotheses until calibrated | **Active; baseline requires calibration** |
| Evidence availability | Per-capability `AVAILABLE/UNAVAILABLE` state and reason | Data/model/topology readiness | Workspace and analysis adapters | API, WHY, Overview, topology and Review | API/UI; selected limitations may reach deterministic narratives | Capability-specific gate | Unavailable is not negative evidence | **Active** |
| Execution modes | `statistics_mode`, `audit_graph_mode`, `pair_materialization` | Chain size/config/runtime path | Tier-1B | API/UI diagnostics and performance governance | API/UI; not LLM-grounded | Large-chain bounds select indexed/lazy modes | A truncated visualization is not a truncated statistic or audit by definition | **Active** |

### B. Alarm-to-topology mapping and the new Alarm Entity Resolution feature

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
|---|---|---|---|---|---|---|---|---|
| `AlarmResourceMapping` | Resolves one alarm to one canonical topology resource | Device/resource identifiers and verified alias table | Mock `ResourceMapper` | `Dep_hop`, P2 topology mapping, navigation | Snapshot topology mappings; API/UI indirectly; not Advisor-grounded | Only `EXACT` and `VERIFIED_ALIAS` resolve analytical topology | Prefix/fuzzy match is forbidden as verified mapping | **Active, fail-closed** |
| Mapping status | `EXACT`, `VERIFIED_ALIAS`, `UNMAPPED`, `AMBIGUOUS`; new resolver also defines `TEXT_MATCH_CANDIDATE` | Mapper result | Resource mapper/entity resolver | Dependency resolvers and topology UI | Snapshot/DB/API/UI | Analytical dependency resolvers accept only eligible statuses | Candidate text matches must not enter causal/dependency resolution | **Active; shared enum has two contexts** |
| Mapping method | Exact identity, verified alias table, structured-field match, raw-text exact token, or none | Resolution process | Mapper/entity resolver | Auditability and UI explanation | API/DB/UI | Method must agree with status | A structured source field is not automatically a verified alias | **Active; semantics need hardening for new resolver** |
| Mapping confidence | Optional mapping score/metadata | Mapper/resolver | Mapper/entity resolver | UI only in current new feature | API/DB/UI; not LLM-grounded | Requires calibration to be interpreted probabilistically | Current `0.95/0.72/0.40` values are heuristic constants, not calibrated probabilities | **Incomplete** |
| `OBSERVED_HOST` entity resolution | Identifies the resource on which an alarm was observed | Device IP/code/reference plus topology host index | `AlarmEntityResolver` | Topology Overlay and entity details | New DB model/API/member view/UI | Must resolve against the selected topology profile/version | Observation location is not affected component or root cause | **Implemented; current fallback can create false `EXACT` IDs** |
| `AFFECTED_COMPONENT_CANDIDATE` | Associates an alarm with a host-scoped module/component candidate | Structured `component/port` or raw alarm text plus module vocabulary | `AlarmEntityResolver` | Topology Overlay | New DB model/API/UI | Unique structured or text candidate; ambiguity must be preserved | Mentioned component is not necessarily the failed component | **Implemented, active in chain route** |
| Structured component match | Matches `component/port` against modules on the resolved host | Structured source field and topology module names | `AlarmEntityResolver` | Entity-resolution API/UI | Intended to persist and display | Exact canonical/verified alias semantics required | Current substring path can label partial matches `VERIFIED_ALIAS`; this is not safe | **Incomplete** |
| Raw-text topology vocabulary match | Host-scoped exact-token detection of known module names in alarm text | `alarm_name`, content, topology vocabulary | `AlarmEntityResolver` | Topology visualization only | API/UI and intended DB persistence | Unique token -> candidate; multiple distinct matches -> ambiguous | Must remain a hypothesis and must not unlock causal channels | **Active as UI candidate** |
| Candidate set | Preserves all possible resource IDs when mapping is ambiguous | Resolver matches | `AlarmEntityResolver` | UI diagnostics | API/DB/UI | Empty, unique, or multi-candidate state is explicit | Never select the first candidate by collection order | **Implemented** |
| Entity-resolution provenance | `entity_role`, `source_field`, `matched_text`, profile/version, resolver version | Resolver context | `AlarmEntityResolver` | Debugging, UI explanation, future cache invalidation | API/new DB table/UI | All version fields should bind result identity | Without snapshot/profile/version identity, cached mappings can be stale | **Implemented; persistence identity incomplete** |
| Entity-resolution persistence | Intended durable reuse of alarm entity resolutions | Resolution records | Topology repository | Chain detail route should read before recomputing | New SQLAlchemy table/repository | Requires migration, snapshot-safe key and read-through cache | Persisting without read-back does not avoid recomputation | **Incomplete: no Alembic migration; active route always recomputes** |
| Host-module vocabulary | Versioned map from instance/IP to module candidates | Materialized topology nodes and `MODULE_HAS_INSTANCE` edges | Topology repository | Entity resolver | Runtime DB query; not directly exposed | Profile/version compatible topology required | Loading all modules per chain request is a performance concern | **Active, uncached** |

### C. Pair evidence channels

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
|---|---|---|---|---|---|---|---|---|
| `E_reference` | Exact equality of `node_reference` | Canonical/raw node reference | Entity channel | Pair WHY, group statistics, membership/audit when eligible | Pair API/WHY UI; indirect aggregate only to narratives | Missing on either alarm -> `UNAVAILABLE` | Shared reference is co-reference evidence, not causality | **Active** |
| `E_device` | Exact equality of `device_code` | Device code | Entity channel | Same as above | Pair API/WHY UI | Missing on either side -> unavailable | Same device does not prove same fault | **Active** |
| `E_card` | Exact equality of `component` | Component/card field | Entity channel | Same as above | Pair API/WHY UI | Missing on either side -> unavailable | Field equality is only as reliable as source normalization | **Active** |
| `E_site` | Exact equality of `location_code` | Site field | Entity channel | Same as above | Pair API/WHY UI | Missing on either side -> unavailable | Co-site is not shared dependency | **Active** |
| `E_remote` | Exact equality of `remote_node`; relation evidence, not containment | Remote-node field | Remote entity channel | Pair WHY and eligible aggregation | Pair API/WHY UI | Missing on either side -> unavailable | It is not “same optical port” and not a direction claim | **Active** |
| `S` | Ordinal semantic relation: same name `1.0`, family `0.6`, category `0.3`, unrelated `0.0` | Alarm name and optional taxonomy | Semantic channel | Pair WHY, statistics, membership/audit if eligible | Pair API/WHY UI; descriptor/fingerprint indirectly | Missing name -> unavailable; family/category require taxonomy | No fuzzy text model; different names without taxonomy are computed neutral | **Active, taxonomy-conditional** |
| `T_burst` | Whether two alarms belong to the same contextual silent-gap burst | Canonical times and chain-level burst segmentation | Temporal channel | Pair WHY, statistics, membership/audit if eligible | Pair API/WHY/timeline | Missing/invalid context -> unavailable | Temporal proximity is not propagation or causality | **Active** |
| `T_delay` primitive | Directed local-mass compatibility under a supplied delay distribution | Ordered timestamps and delay distribution | Temporal channel | Pair WHY primitive/tests | Pair API when configured | No distribution/model -> unavailable | “A before B” is not “A caused B” | **Conditional** |
| Frozen temporal-delay evidence | Versioned histogram/KDE model selected from historical relation episodes | Historical taxonomy and cutoff-valid episodes | Temporal-delay model/channel | Pair WHY and ranker temporal context | Model artifacts, Pair WHY, Review features | Minimum episodes, compatible taxonomy/version and validated threshold required | Current production calibration is not established | **Implemented, production-blocked** |
| `Dep_hop` | `1/(1+distance)` over eligible physical topology adjacency | Exact alarm-resource mappings and physical graph | Dependency channel | Pair WHY, indexed statistics, membership/audit when eligible | Pair API/WHY; topology availability reaches ranker | Missing graph/mapping or distance above bound -> unavailable/neutral per contract | IP adjacency is structural and undirected, not dependency direction | **Active for eligible IP topology** |
| `DepUpstreamAncestor` | Compatibility through an explicit shared directed upstream ancestor | Directed eligible relations and exact mappings | Common-dependency provider | Pair WHY and indexed provider path | Pair API/WHY | Explicit directed dependency semantics required | IT navigation links must not be relabeled as dependency | **Conditional, fail-closed** |
| `DepUpstreamActivePath` | Compatibility through an explicit first-class active path | Active-path records and mappings | Active-path provider | Pair WHY | Pair API/WHY | Active path must be supplied; never inferred from adjacency | A shared path is not root-cause proof | **Conditional** |
| `Dep_embed` | Optional topology-embedding similarity | Versioned embedding model and exact mappings | Topology embedding channel | Explicit Pair WHY only when enabled | Pair API/WHY; not core role by default | Compatible approved model required | Embedding similarity is a hypothesis, not topology fact | **Optional/experimental** |
| `H` | Historical pair association under episode-deduplicated, cutoff-valid history | Historical model and taxonomy | Historical channel | Explicit Pair WHY only | Pair API/WHY when enabled | Model/taxonomy/cutoff required | Historical co-occurrence is not causal evidence and does not enter role/audit | **Conditional** |
| `H_domain` | Set-valued membership in a supplied failure-domain hyperedge | Failure-domain records and alarm-resource mappings | Failure-domain adapter | Member context and audit candidate generation | API/member/audit UI | Explicit domain membership required | It is not a pair score and must not be clique-projected | **Conditional** |
| Channel verdict | `SUPPORT`, `NEUTRAL`, or `UNAVAILABLE` derived from availability, score and threshold | Channel result | Base normalization | All group-level consumers | Pair API/WHY | Availability precedes thresholding | Zero support is not the same as missing evidence | **Active** |

### D. Derivation groups, statistics, membership, and role features

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
|---|---|---|---|---|---|---|---|---|
| Derivation group | Deduplicates multiple channels derived from the same underlying source before aggregation | Channel IDs, tags, provenance | Provenance/group builder | Membership, role, audit | API group fits and WHY UI | Homogeneous provenance and eligibility required | Distinct channels from one field do not get multiple votes | **Active** |
| Explain/role/audit eligibility mask | Independent permission for a group to appear in explanation, role, or audit | Provenance and source-kind policies | Derivation policy | Pair/role/audit paths | API diagnostics/UI | Disallowed evidence is excluded rather than weakened | Visibility does not imply role/audit eligibility | **Active** |
| Indexed sufficient statistics | Full-chain counts and postings without default dense pair materialization | Chain members and channel indexes | Indexed statistics pipeline | Tier-1B group fits and roles | Runtime/index state; API aggregates | Unsupported exact statistic -> unavailable | Indexing must preserve exact semantics, not approximate silently | **Active** |
| Group fit | Per-member/per-group fit computed over available evidence | Indexed/channel statistics | Group fit modules | Membership support, WHY group/member views | API/UI | Unavailable group stays unavailable | Fit is evidence compatibility, not probability | **Active** |
| Membership support | Aggregate support across computable role-eligible derivation groups | Group fits | Membership support | Role classification, counterfactual metrics | API/member UI; Advisor extracts the final role support | At least one computable eligible group | High support means in-chain evidence compatibility, not root cause | **Active** |
| Availability coverage | Computable role-eligible groups divided by possible role-eligible groups | Group fits | Role gate | Role classification and UI | API/member UI | Must meet `c_min` | Missing evidence must not be interpreted as weakness | **Active** |
| Computable-group count | Number of distinct role-eligible groups with computable evidence | Group fits | Role gate | Role classification | API/UI | Must meet configured minimum, normally 2 | Raw channel count is not the same as independent group count | **Active** |
| Representativeness | How well a member represents the chain's descriptor/semantic profile | Predicate index/descriptors | Tier-1B | CORE decision and UI | API/member UI; included in structured Advisor member facts but not rendered prominently | Missing representation blocks CORE | Representativeness is not causal importance | **Active** |
| `Margin_common` | Mean fit advantage for home chain versus each rival over groups computable in both | Target/rival group fits | Contrastive analysis | CORE/WEAK role and WHY | API/member/group UI | Fewer than `g_min` common groups -> insufficient evidence | Never compare a value with unavailable evidence | **Active** |
| Membership role | `CORE`, `PERIPHERAL`, `WEAK`, `INSUFFICIENT_DATA`; singleton handled separately | Support, coverage gate, representativeness, margins, thresholds | Role classifier | Chain/member UI, counterfactual metrics, Advisor facts | API/UI; role counts and weak/insufficient members are LLM-grounded | Full role gate plus class-specific thresholds | CORE is a membership role, not root cause; WEAK is not missing data | **Active** |
| Singleton verdict | Explicit not-applicable handling when pair evidence cannot exist | Chain size 1 | Gray-box singleton adapter | Tier-1B/API/UI | API/UI | Singleton chain | Must not fabricate support, connector or audit claims | **Active** |
| Structural role | `CONNECTOR`, `NON_CONNECTOR`, or `NOT_APPLICABLE` on the Audit Graph | Exact audit graph and supported blocks | Structural-role classifier | Audit UI and counterfactual structural effects | Tier-2 artifact/API/UI; not currently Advisor-grounded | Exact audit graph and articulation/bridge plus support to at least two blocks | CONNECTOR means structural bridge in evidence graph, not propagation source | **Conditional** |
| Redundancy role | `NEAR_DUPLICATE_CANDIDATE`, `UNIQUE`, `NOT_APPLICABLE` | Name, entity, time delta and descriptor coverage | Redundancy classifier | Member diagnostics and remove-candidate context | API/UI | Required fields and small time window | Candidate duplicate can still be CORE; operator review required | **Active** |
| Evidence attribution | Closed-form allocation of supported evidence across derivation groups | Group support statistics | Attribution evaluator | WHY/coverage UI and evaluation | API/UI | Eligible available groups only | Attribution is explanation accounting, not causal contribution | **Active** |
| Randomization evaluation | Deterministic seeded evidence-attribution sanity/evaluation | Attribution data and frozen RNG policy | Evaluation pipeline | Benchmarks/tests | Artifacts/tests, limited UI | Correct repetition/sample metadata required | Evaluation quality is not production calibration by itself | **Implemented** |

### E. Descriptor mining, local rivals, and gray-box facts

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
|---|---|---|---|---|---|---|---|---|
| Predicate index | Bitset index of structured alarm predicates for bounded descriptor mining | Canonical/raw alarm fields | Predicate index | Identity/contrastive descriptors and audit separation | Runtime intermediate; not directly UI/LLM | Indexed fields and cardinality bounds | Bit positions are implementation detail, not evidence | **Active, backend-only** |
| IDENTITY descriptor | Compact predicate conjunction characterizing the target chain | Predicate index and mining thresholds | Descriptor miner | Auto-title, fingerprint, member representativeness, audit descriptor separation | API/UI; top labels are Advisor-grounded | Coverage/precision/depth/redundancy gates | A descriptor summarizes the chain; it does not explain cause | **Active** |
| CONTRASTIVE descriptor | Predicate conjunction distinguishing target chain from local rival universe | Target plus `U_local` | Descriptor miner | WHY contrastive view and margins | API/UI; top descriptors may enter Advisor facts | Local precision and common-evidence requirements | It is local, not a globally unique rule | **Active** |
| Blocking index | Finds plausible neighboring chains without scanning every chain globally | Structured attributes and indexes | Contrastive/blocking modules | `U_local`, margins and descriptor mining | Backend intermediate; selected rivals shown | Top-k bounded selection | Raw overlap score is retrieval priority, not probability | **Active** |
| Multi-dimensional rival discovery | Candidate score from attributes, topology adjacency, temporal proximity, and semantic/keyword relations | Current snapshot, topology, time and taxonomy | `contrastive.py` | Blocking candidate selection | API/WHY indirectly | Each dimension needs its input capability | Keyword “causal” patterns are discovery heuristics, not causal facts | **Active but semantically heuristic in parts** |
| Local rival universe `U_local` | Top-k competing chains used for contrastive mining | Ranked blocking candidates | Contrastive analysis | Descriptors and margins | API/WHY | Bounded by configured k | It is not all other chains | **Active** |
| Auto-title | Deterministic display title derived from descriptors/facts | Descriptor set | Tier-1B | Chain list/tree/header | API/UI; not directly LLM-grounded | Requires suitable descriptor | A title is a label, not a verdict | **Active** |
| Gray-box system facts | Preserves NocPro-provided rules, characteristics and annotations separately from inferred evidence | Upstream gray-box metadata | Gray-box adapter | Explain UI and diagnostics | Snapshot/API/UI | Depends on upstream metadata | System facts must not be converted into post-hoc evidence | **Active when supplied** |
| Black-box/gray-box mode | Controls wording and available explanation sources | Snapshot metadata | Gray-box adapters | UI and narrative discipline | API/UI | Source-dependent | Lack of internals must remain explicit | **Active** |

### F. Audit graph, cut testing, and over-merge assessment

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
| Statistical graph | Conceptual full evidence statistics; never UI-pruned | All eligible pair/group statistics | Tier-1B indexes | Fits and aggregates | Backend | Exact sufficient statistics required | Not the displayed graph | **Active** |
| Visualization graph | Bounded/top-k graph for readable UI only | Selected edges/nodes | Visualization serializers | Audit/structure UI | API/UI | Display limits explicit | Must never be used for structural audit | **Active** |
| `G*_audit` / Audit Graph | Exact evidence graph whose edge requires at least two distinct supporting audit-eligible derivation groups | Pair/group evidence | Audit graph builder | Conductance, structural roles, Review | Tier-2 artifact/API/UI | Exact graph up to configured size; otherwise explicit bounded mode/unavailable | Distinct derivation groups are not proof of independent sources; graph is not physical topology | **Conditional, active** |
| Audit edge weight | Equal-group normalized positive support over audit-eligible groups | Supporting and available audit groups | Audit graph builder | Conductance and visualization | API/UI | At least two supporting groups | Weight is not causal probability | **Active** |
| Candidate cut generation | Deterministic bounded candidate partitions from supported sources | Audit graph, descriptors, failure domains and candidate policies | Audit candidates | Conductance scoring | Tier-2 artifact/UI | Only enumerated candidates are tested | `NO_LOW_CONDUCTANCE_CUT` means none among tested candidates, not mathematical global optimality | **Active** |
| Conductance `Phi` | Weighted boundary cut divided by smaller side volume | Audit graph and candidate partition | Conductance module | Audit verdict and counterfactual metric | Artifact/API/UI | Both sides and volumes must be valid | Low Phi signals structural separation in evidence graph only | **Active** |
| Audit verdict | `CANDIDATE_SPLIT`, `NO_LOW_CONDUCTANCE_CUT`, `SKIPPED_SMALL_CHAIN`, `UNAVAILABLE` | Candidate scores and epsilon | Structural audit | Review, structure UI, counterfactual candidate generation | Persisted Review/deep-dive artifact; API/UI; not currently Advisor-grounded | Exact public status mapping required | No-cut is not proof the chain is correct; candidate split is not proof NocPro is wrong | **Active** |
| Structural separation line | A tested candidate has a balanced low-conductance cut | Audit result | Over-merge assessor | Strength and narrative | Artifact/UI | Audit candidate split required | Structural separation alone yields only weak review evidence | **Active** |
| Cross-evidence agreement line | Explicit negative/contradictory evidence agrees across the proposed blocks | Cross-block evidence | Over-merge assessor | Strength | Artifact/UI | Must be supplied, not inferred from absence | Missing cross evidence is not agreement | **Conditional** |
| Descriptor separation line | Each side has a distinct qualifying top identity pattern | Predicate index and block-specific mining | Over-merge assessor | Strength | Artifact/UI | Both sides need valid descriptors | Different descriptors do not prove independent incidents | **Conditional** |
| Sensitivity stability line | Same cut remains below scaled epsilon values | Audit graph and cut | Over-merge assessor | Strength | Artifact/UI | Computable conductance required | Stability is threshold robustness, not causal validation | **Conditional** |
| Over-merge strength | `NONE`, `WEAK`, `MODERATE`, `STRONG`, or `UNAVAILABLE` from the four evidence lines | Over-merge evidence count | Over-merge assessor | Audit/Review UI | Artifact/API/UI; currently not in Advisor structured facts | Candidate split prerequisite | It is evidence strength for review, not generic confidence or an automatic correction | **Active** |

### G. Similar Chains, historical comparison, and evolution

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
| Alarm-taxonomy fingerprint block | Sparse TF-IDF terms from authoritative family or explicitly labeled fallbacks | Taxonomy and alarm fields | Fingerprint builder/model | Similar Chains | Versioned model/index/API/UI | Taxonomy availability and cutoff policy | Fallback level must remain visible | **Conditional** |
| Device-type fingerprint block | Sparse TF-IDF terms from real `device_type_name` | Alarm raw fields | Fingerprint builder/model | Similar Chains | Model/index/API/UI | Field availability | Never infer type from device-code prefix | **Active when populated** |
| Descriptor fingerprint block | Top qualifying IDENTITY descriptor labels | Identity descriptors | Fingerprint builder | Similar Chains | Model/index/API/UI | Descriptor availability | Missing block reduces comparison basis | **Conditional** |
| Size bin | Bounded categorical chain-member-count feature | Member count | Fingerprint builder | Similar Chains | Model/index/API/UI | Always present | Same size is weak similarity evidence alone | **Active** |
| Duration bin | Bounded duration feature with explicit unknown bin | Canonical duration | Fingerprint builder | Similar Chains | Model/index/API/UI | Missing duration -> `duration_bin_unknown` | Unknown must not collapse to instant duration | **Active** |
| Versioned fingerprint model | Freezes vocabulary, IDF weights, cutoff, taxonomy policy and bin config | Historical fingerprint corpus | Fingerprint model builder | Cosine scoring | Model/index metadata/API/UI | All compared fingerprints must use same model version | Vector dimensionality is dynamic, not fixed at 512 | **Active architecture; data-conditional** |
| Cosine similarity | Similarity between two fingerprints in one frozen vector space | Encoded fingerprints | Similar Chains scorer | Similar-case retrieval/UI | API/UI; ranker consumes separate review-case similarity features | Same model/version and sufficient active blocks | High cosine is historical resemblance, not identical root cause | **Conditional** |
| Feature-block coverage | Which of five fingerprint blocks actually participated | Fingerprint | Similar Chains | UI diagnostics | API/UI | Explicit missing blocks | A score on two blocks is not comparable in confidence to a score on five without disclosure | **Active** |
| Historical corpus cutoff | Uses history strictly before the query snapshot and excludes same lineage where configured | Snapshot time and lineage | Similar Chains index | Retrieval | Model metadata/API | Cutoff-valid persisted history required | Prevents future leakage | **Active policy, data-conditional** |
| Global episode lineage | Stable lineage component/branch across snapshot-scoped chains | Sequential snapshots and overlap rules | Evolution pipeline | Evolution, history exclusion and UI | PostgreSQL/artifact/API/UI | Requires sequential compatible snapshots | Chain ID reuse is not lineage | **Conditional** |
| Evolution edge | Parent-to-child event with overlap/containment facts | Consecutive lineage states | Evolution pipeline | Evolution view | Persisted/API/UI | Thresholds and source sequence required | Split/merge labels describe observed membership evolution, not causality | **Conditional** |
| Drift metadata | Distinguishes data, config and execution-tier explanation changes | Versioned snapshot/config/artifacts | Evolution/drift modules | Diagnostics and tests | Artifact/API selectively | Comparable versions required | A changed explanation need not mean changed incident | **Implemented** |

### H. Tier-2 topology hypotheses

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
| Directed universe | Exact non-mixed directed graph selected for P2 analysis | Explicit eligible directed topology relations | P2 mapping/universe builder | Dominator, propagation and scope | Tier-2 job artifact/API/UI | Relation semantics, mappings and provenance must all be eligible | Physical IP adjacency and IT navigation links cannot be promoted to directed dependency | **Fail-closed, usually unavailable on current real topology** |
| Dominator witness | Resource whose directed paths cover the observed mapped resources under the selected universe | Directed universe and mappings | Dominator analysis | Topology hypotheses and scope anchor | Job artifact/API/Topology UI | Complete exact P2 mappings and valid directed graph | A dominator is a structural hypothesis, not root cause | **Conditional** |
| Dominator coverage | Set/count of resources covered by the witness | Dominator result | P2 analysis | Topology UI and scope | API/UI | Available witness | Coverage is structural reachability under the graph semantics | **Conditional** |
| RWR propagation node score | Converged stationary mass for each alarm/resource in configured random walk with restart | Directed candidate graph and seeds | Propagation analysis | Topology hypotheses UI | Job artifact/API/UI; not Advisor-grounded | Directed eligible graph and convergence required | It is a model score, not observed propagation probability | **Conditional** |
| Propagation edge hypothesis | Accepted direct graph-following flow with score, transition probability and temporal delta | Directed graph, seed policy and times | Propagation analysis | Topology hypotheses UI | API/UI | Direct admissible edge and temporal requirements | Hypothesis wording is mandatory; no causal assertion | **Conditional** |
| Propagation diagnostics | Node/edge counts, iterations, final L1 distance, tolerance, restart and dangling policies | RWR execution | Propagation analysis | Debugging/UI | API/UI | Algorithm must converge or report unavailable | Diagnostics describe numerical execution, not operational confidence | **Implemented** |
| Dependency scope overlap | Coverage, precision, Jaccard, missing and extra resources between observed impact and witness scope | Directed witness scope and observed mappings | Scope analysis | Topology UI | Job artifact/API/UI | Witness and bounded materialization required | Overlap does not prove that the witness caused all alarms | **Conditional** |
| Topology navigation projection | Browsable relation tree with aliases and explicit semantic notice | Materialized topology DB | Topology repository/API | Topology Tree/Overlay | DB/API/UI | Active version/profile required | Navigation does not imply ownership, dependency, causality or direction | **Active** |
| Bounded topology subgraph | K-hop neighborhood around seed resources for visualization | Active topology DB and seed resolution | Topology repository | Topology Overlay | API/UI | Node/edge/hop bounds | A bounded response may omit topology outside its limits | **Active** |

### I. Counterfactual generation, evaluation, and recommendation

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
| `REMOVE_MEMBER` candidate | Tests removing one member from a partition | Current partition and candidate policy | Counterfactual candidates | Evaluator/Review | Review job/API/UI; recommendation facts may reach LLM | Hard gates and complete before/after evaluation | It is a proposed partition edit, not alarm suppression | **Active** |
| `SPLIT_CHAIN` candidate | Tests a deterministic bipartition, often based on an Audit candidate cut | Current chain and audit candidate | Counterfactual candidates | Evaluator/Review | Job/API/UI/LLM proposal facts | Valid non-empty partition and evidence binding | Split recommendation is not proof of two physical incidents | **Active** |
| `MOVE_MEMBER` candidate | Tests transferring members between existing chains | Source/target partitions and candidate discovery | Counterfactual candidates | Evaluator/Review | Job/API/UI/LLM proposal facts | Both chains and exact membership delta required | Movement is a what-if grouping edit | **Active** |
| `MERGE_CHAINS` candidate | Tests combining chains | Two eligible chains | Counterfactual candidates | Evaluator/Review | Job/API/UI/LLM proposal facts | Candidate selection and hard gates | Similarity alone must not force a merge | **Active** |
| Partition delta | Canonical before/after affected-chain membership sets | Candidate operation | Counterfactual model | Metric evaluator, explanation and fingerprinting | Job artifact/API/UI | No duplicates, empty invalid chains or lost members outside operation contract | The delta is simulated until an operator applies/records a decision | **Active** |
| `weak_member_count` | Count of members classified WEAK | Tier-1B roles | Counterfactual MetricVector | Pareto/evaluation/UI/ranker delta | Job/API/UI; deltas may be LLM-grounded | Role availability required | Fewer WEAK members is not sufficient alone to prefer a mutation | **Active** |
| `minimum_membership_support` | Minimum available support in affected partition | Member support | Metric evaluator | Same | Job/API/UI/LLM delta | At least one available support | Minimum can be sensitive to one member | **Active** |
| `evidence_union_coverage` | Coverage of eligible evidence across affected partition | Group evidence | Metric evaluator | Same | Job/API/UI/LLM delta | Eligible evidence required | Coverage quantity does not establish correctness | **Active** |
| `component_count` | Number of connected components in the applicable audit/evidence graph | Evaluated graph | Metric evaluator | Same | Job/API/UI/LLM delta | Graph must be available | Component count is graph-specific, not physical outage count | **Conditional** |
| `audit_conductance` | Best applicable audit-cut conductance | Audit evaluation | Metric evaluator | Same | Job/API/UI/LLM delta | Audit result available | Lower/higher is meaningful only with operation semantics and other metrics | **Conditional** |
| `audit_verdict_severity` | Numeric encoding of audit verdict strength/state for comparison | Audit result | Metric evaluator | Same | Job/API/UI/LLM delta | Audit available | Encoded severity is not calibrated probability | **Conditional** |
| `eligible_external_contradiction_count` | Count of eligible external contradictions against a proposed partition | External evidence | Metric evaluator | Hard gates/Pareto/UI | Job/API/UI | Eligible contradiction source required | Missing contradictions are not positive confirmation | **Conditional** |
| Metric availability | Per-metric `AVAILABLE`, `UNAVAILABLE`, `NOT_APPLICABLE` and reason | Metric computation | Counterfactual models | Hard gates, UI and explainer | Job/API/UI | Must be retained through before/after/delta | Unavailable values must not become zero improvement | **Active** |
| `EditCost` | Domain cost: operation count, membership reassignments and affected member count | Candidate partition delta | Candidate generator | Pareto and ranking context | Job/API/UI indirectly | Non-negative canonical counts | Ranker fields `members_moved/chains_created/chains_removed` are derived features, not this domain type | **Active** |
| Hard gates | Deterministic safety/validity requirements before recommendation | Candidate evaluation, evidence availability and contradictions | Counterfactual evaluator | Candidate exposure and Review | Job/API/UI | Any failed gate -> rejected/not rankable | ML score can never override a failed gate | **Active** |
| Pareto state | Selected, dominated, truncated or otherwise bounded candidate status | Eligible metric vectors and edit cost | Pareto selector | Recommendation set and ranker | Job/API/UI and ranker feature | Comparable available objectives required | Pareto membership is not operator approval | **Active** |
| Comparative explanation | Deterministic action, why-better, metric deltas, comparison points and explicit limits | Candidate before/after facts | Comparative explainer | Review UI and Advisor proposal facts | Persisted job/API/UI/LLM-grounded when recommendation exists | Candidate-specific observed/simulated facts required | Must not invent topology, causal, root-cause or fault-domain claims | **Active** |
| Review job lifecycle | Queued/running/terminal asynchronous exact Review evaluation | Chain and config fingerprint | Review job manager | API/UI/restart recovery | PostgreSQL/API/UI | Identity/version binding and terminal persistence required | A healthy process is not proof the job completed | **Active, persisted** |

### J. Review learning, operator feedback, Similar Cases, and XGBRanker

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
| Candidate exposure | Immutable record of what candidate and rank the operator actually saw | Review result, features, ranking audit | Review learning service | Feedback and training datasets | PostgreSQL/API/UI | Candidate/result fingerprints required | Unexposed candidates must not receive inferred labels | **Active** |
| Operator decision | Accept/reject/manual correction with reviewer context and reason | Authenticated/authorized operator action | Feedback API/service | Case memory and training eligibility | PostgreSQL/API/UI | Governance and identity binding required | Operator assertion is not automatically external ground truth | **Active in trusted workflow** |
| Feedback lifecycle | Active, superseded and retracted immutable event history | Decision updates | Review learning store | Training dataset materialization and audit | PostgreSQL/API/UI | Retractions and supersession must be honored | Deleted-looking UI state must not erase audit history | **Active** |
| Truth tier | Labels feedback provenance such as PO-asserted versus confirmed operational outcome | Feedback metadata | Review learning contracts | Training/readiness gates | PostgreSQL/API/UI | Tier-specific eligibility | `PO_ASSERTED` is not independently confirmed production truth | **Active** |
| Review case fingerprint | Versioned representation of candidate, context and outcome | Candidate exposure and feedback | Review learning | Similar reviewed cases | PostgreSQL/API/UI | Compatible schema/version required | Fingerprint match is reference evidence only | **Active** |
| Similar reviewed cases | Retrieves past reviewed candidates using available feature blocks | Review case store | Case similarity | Review UI and ranker features | API/UI; summary features enter ranker, not Advisor by default | Confirmed historical cases and comparable blocks required | Similar cases are not probability or automatic recommendation | **Conditional** |
| `cf-features-v1` | Frozen **43-feature** numeric schema for ranker input | Candidate deterministic, temporal, case, source and topology contexts | Review-learning feature materializer | XGBRanker training/inference | Feature payload/artifact/API learning UI | Availability indicators required for optional features | Zero plus `__available=0` means missing, not observed zero | **Implemented** |
| Operation one-hot features | Remove/split/move/merge indicators | Candidate operation | Feature materializer | Ranker | Persisted feature payload/UI importance | Exactly one normal operation family expected | Encodes operation class only | **Active when ranker path runs** |
| Metric delta features | Six before/after deltas plus availability indicators | Counterfactual evaluation | Feature materializer | Ranker | Feature payload/UI importance | Metric-specific availability | The seventh contradiction metric is not currently in the ranker delta list | **Active** |
| Baseline-before features | Weak count, min support and component count plus availability | Before metrics | Feature materializer | Ranker | Feature payload | Availability required | Partial baseline context must remain explicit | **Active** |
| Ranker edit-cost features | Members moved, chains created, chains removed | Partition delta/derived context | Feature materializer | Ranker | Feature payload | Canonical partition delta required | Different from domain `EditCost` fields | **Active** |
| Hard-gate/Pareto features | Passed/selected/truncated/dominated flags | Candidate governance state | Feature materializer | Ranker | Feature payload | Deterministic eligibility computed first | Model must not learn to revive rejected candidates | **Active** |
| Temporal ranker features | Delay score mean, atypical fraction, fallback fraction plus availability | Temporal counterfactual context | Feature materializer | Ranker | Feature payload/UI importance | Compatible temporal model required | Model-derived temporal typicality is not causality | **Conditional** |
| Similar-case ranker features | Approved ratio and maximum similarity plus availability | Historical reviewed cases | Feature materializer | Ranker | Feature payload/UI importance | Confirmed comparable cases required | Approval ratio is cohort history, not probability of correctness | **Conditional** |
| Source-kind ranker features | One-hot live/replay/synthetic provenance | Snapshot source kind | Feature materializer | Ranker/governance | Feature payload | Source kind required | Prevents hiding synthetic/live distribution differences; does not solve domain shift | **Active** |
| Topology-availability ranker feature | Whether eligible `Dep_hop` evidence is available | Deterministic context | Feature materializer | Ranker | Feature payload | Valid topology/mapping capability required | Availability is not topology support strength | **Active** |
| XGBRanker score | Learned ranking score for deterministically eligible candidates | 43-feature vector and approved artifact | Review learning ranker | Candidate reranking/UI | Artifact + ranking audit/API/UI | Production-approved loaded model, compatible schema and integrity checks required | Score is not calibrated probability | **Conditional; model may be unavailable** |
| Abstention | Refuses learned reranking when top margin/governance conditions fail | Ranker scores and threshold | Review learning service | Candidate ranking/UI | Ranking audit/API/UI | Threshold and model state required | Abstention must fall back to deterministic ordering, not guess | **Active** |
| Ranker artifact governance | Version, hash/signature, corpus fingerprint, metrics and approval status | Training run | Ranker artifact pipeline | Production loader and Learning UI | Files/PostgreSQL/API/UI | Integrity, schema, data and approval gates | A trainable artifact is not a production-approved artifact | **Implemented; current calibration remains non-production** |
| Ranker evaluation | NDCG, top-1 approved recall, mean regret and baseline comparison | Held-out grouped review data | Ranker evaluation | Learning UI/governance | Artifact/API/UI | Leakage-safe split and enough real labels required | Synthetic/DRAFT metrics do not validate production performance | **Conditional/blocked by labels** |

### K. Analytical findings, deterministic narratives, LLM grounding, and assistant behavior

| Feature / canonical ID | Exact meaning | Inputs | Producer | Active consumers | Persistence / API / UI / LLM | Eligibility and unavailable semantics | Interpretation boundary | Current state |
| Analytical finding kind | Typed `OBSERVED`, `DERIVED`, `HYPOTHESIS`, or `LIMITATION` finding | Chain facts and capability results | Cohesion/analysis narrative service | Chain Overview/WHY | API/UI; not automatically Advisor-grounded | Evidence list and availability state required | Kind must not be hidden in prose | **Active in Overview path** |
| Finding evidence list | Concrete facts supporting one finding | Observed/derived data | Narrative service | UI | API/UI | Only supplied facts | Evidence list should be auditable back to fields/artifacts | **Active** |
| Finding limitations | Explicit statement of what the finding cannot establish | Capability gates | Narrative service | UI | API/UI | Required for hypotheses/limitations | Limitation is analytical output, not boilerplate disclaimer | **Active** |
| Confidence basis | Textual basis for confidence/evidence strength | Available evidence/provenance | Narrative service | UI | API/UI | Must reference real evidence and calibration status | Must not fabricate numeric confidence | **Active** |
| Cohesion narrative | Deterministic structured explanation of why members appear together and what is unavailable | Tier-1B analysis and evidence availability | Cohesion advisor | Chain Overview/WHY | API/UI; separate from AI Advisor grounding | Facts and unavailable reasons required | Keyword/co-occurrence indicators are not verified topology or causal facts | **Active; semantic review still important** |
| Advisor structured member facts | Alarm ID, membership role, support and representativeness | Tier-1B member analysis | `ai_advisor._member_facts` | Deterministic Advisor draft | Passed to bounded LLM facts indirectly | Analysis must be available | Current projection omits alarm name, device and timestamp | **Active but narrow** |
| Advisor descriptor facts | Up to three identity/contrastive labels with coverage | Descriptor set | `ai_advisor._descriptor_facts` | Advisor | Directly LLM-grounded | Descriptor availability | Labels are descriptive, not causal | **Active** |
| Advisor recommendation facts | Recommended operation, deterministic comparative explanation and non-zero deltas | Persisted Review result | AI Advisor projection | Advisor | Directly LLM-grounded | Recommendation must exist and be interpretable | LLM may rewrite but not choose a new action | **Active** |
| Advisor unavailable facts | Review status/reason and recommendation status | Review artifact/read path | AI Advisor | Advisor | Directly LLM-grounded | Missing/failed Review | Unavailable must not be narrated as “no problem” or “optimal” | **Active** |
| Grounded LLM renderer | Rewrites a deterministic draft using only bounded facts and references | Draft, structured facts, fact refs | `grounded_llm.render_grounded` | AI Advisor/assistant surfaces | Provider request; output UI | Provider/config/validation gates; deterministic fallback on failure | LLM cannot create evidence, roles, scores, recommendations, causality, root cause, topology dependency or mutations | **Active with fallback** |
| Provider status | Records whether external provider or deterministic renderer produced the message | Runtime provider result | Grounded LLM adapter | UI badge/diagnostics | API/UI | Live response required for provider success | Config presence is not proof of provider success | **Active** |
| Grounded content validation | Rejects malformed/unbounded/provider output that violates response contract | Provider content | Grounded LLM adapter | Advisor/assistant | Runtime | Validation must pass | Validation reduces, but cannot replace correct fact projection | **Active** |
| Read-only assistant | Answers bounded UI/context questions and may navigate permitted views | User query and bounded application context | Assistant API | Assistant drawer | API/UI/LLM | Tool/action allowlist and grounding required | It must not mutate analysis or invent unavailable evidence | **Active** |
| Missing Advisor facts | Audit verdict, conductance, structural connector, topology hypotheses, entity resolution, chain start/end and core alarm details are not currently in Advisor structured facts | Existing artifacts | No active projection | None | Not LLM-grounded today | Would require explicit evidence-safe projection | Documentation must not claim the LLM receives these | **Known gap** |

### L. Web UI surfaces and their real feature inputs

| UI surface | Primary feature inputs | Backend/API source | What it is for | Important limits | Current state |
|---|---|---|---|---|---|
| Snapshot Overview | Snapshot catalog, counts, time coverage, source/profile status | Snapshot/catalog/config APIs | Select and understand snapshot scope | Snapshot statistics are not chain analysis | **Active** |
| Chains Explorer | Chain ID, title, member count, start/end/duration | `/chains` | Find/select/compare chains | List summary does not prove analytical quality | **Active** |
| Multi-chain Timeline | Chain temporal summaries | Chain list/snapshot data | Observe chain overlap in time | Temporal overlap is not causal connection | **Active** |
| Chain Overview | Chain facts, role counts, descriptors, analytical findings, cohesion narrative | Chain analysis + cohesion narrative | High-level incident interpretation | Must preserve finding kind and limitations | **Active** |
| Timeline & Evolution | Member times plus persisted lineage DAG | Chain/evolution APIs | Alarm ordering and lifecycle across snapshots | Earliest alarm is not root cause; lineage requires real sequential snapshots | **Active, data-conditional** |
| Topology Overlay | Materialized subgraph, entity resolutions and optional topology hypotheses | Topology subgraph + chain analysis + deep dive | Visualize observed hosts/modules and structural context | Navigation topology and text candidates are not dependency/causal proof | **Active; new entity resolver path incomplete** |
| WHY — chain scope | Evidence coverage, findings, descriptors, availability and cohesion narrative | Chain analysis/cohesion API | Explain chain-level grouping evidence | Must distinguish observed, derived, hypothesis and limitation | **Active** |
| WHY — group scope | Group fits, support and derivation metadata | Chain analysis | Explain evidence families | UI strength labels must not become probabilities | **Active** |
| WHY — member scope | Role gate, support, margins, representativeness, redundancy | Chain analysis | Explain one member's role | CORE/WEAK semantics depend on gate and contrastive evidence | **Active** |
| WHY — pair scope | Channel matrix, scores, thresholds, availability and details | Pair WHY API | Inspect exact pair evidence | H/T-delay/embedding are capability-gated | **Active** |
| Member Diagnostics | Member facts, membership/structural/redundancy axes | Chain + deep-dive analysis | Diagnose individual alarms | Structural role may be unavailable until Tier-2 | **Active** |
| Audit & Structure | Audit graph, cut candidates, conductance, structural roles, over-merge strength | Deep-dive/Audit artifact | Review structural separation | Audit graph is not physical topology | **Active, job-conditional** |
| Recommendations | Counterfactual candidates, metrics, hard gates, Pareto and comparative explanations | Review job API | Compare possible grouping edits | Only eligible Pareto recommendations may be action candidates | **Active** |
| Validation/sign-off | Candidate review, operator reason and feedback lifecycle | Review/feedback APIs | Record governed operator decision | Feedback tier and authorization matter | **Active in trusted workflow** |
| Similar Cases | Fingerprint/review-case similarity and prior outcomes | Similar-case APIs | Historical reference | Not probability or automatic approval | **Conditional** |
| Learning/Ranker modal | Artifact status, features, metrics, label counts, approval/abstention | Review-learning status/train APIs | Model governance and diagnostics | DRAFT/synthetic artifacts are not production models | **Active** |
| Configuration/calibration | Threshold values, provenance and calibration report | Config APIs | Inspect/update governed analysis configuration | Current baseline still requires production calibration | **Active** |
| AI Advisor | Deterministic draft, narrow structured facts, Review proposal facts, provider status | AI suggestion API | Readable bounded explanation | Current grounding does not include Audit/Topology/Entity Resolution facts | **Active with deterministic fallback** |
| Assistant drawer | Bounded application context and permitted navigation/query actions | Assistant API | Interactive read-only help | Must not be treated as analytical authority | **Active** |

## 3. What actually reaches the LLM today

The active AI Advisor projection is narrower than the full analysis state. The
bounded grounding currently contains:

- chain ID and analyzed member count;
- role counts;
- IDs of WEAK members;
- IDs of `INSUFFICIENT_DATA` members;
- up to three descriptor labels with coverage;
- persisted Review status/reason and recommendation status;
- recommended counterfactual operation and candidate ID;
- deterministic `summary_action`, `why_better`, comparison points, and non-zero metric deltas when present.

The following are **not currently projected into Advisor grounding** and must not
be documented as if the LLM receives them:

- chain start/end time;
- alarm name, device and timestamp for CORE members;
- entity-resolution results;
- topology subgraph or dependency paths;
- Audit verdict, conductance and over-merge strength;
- structural CONNECTOR facts;
- dominator, propagation or dependency-scope hypotheses;
- raw pair-channel matrix;
- Similar Chains results and detailed ranker features.

The LLM is a narrative renderer. It cannot promote a hypothesis into a finding,
choose a new recommendation, infer root cause, claim propagation direction, or
say NocPro grouped alarms incorrectly.

## 4. Current production-readiness caveats

1. Threshold configuration and calibration reports still indicate baseline or
   synthetic-only calibration rather than production validation.
2. Directed P2 topology hypotheses correctly fail closed when dependency
   semantics or exact mappings are absent. Current IP adjacency is undirected;
   current IT relations are primarily navigation/source relations.
3. Historical `H`, frozen `T_delay`, Similar Chains, evolution, Similar Cases and
   XGBRanker all require valid persisted history that obeys temporal cutoff and
   provenance rules.
4. The new Alarm Entity Resolution is wired from BE to FE, but the current
   implementation still has known completion issues: profile hardcoding, false
   synthesized `EXACT` host IDs, unsafe structured substring verification,
   missing Alembic migration, non-version-safe persistence identity, no active
   persistence read-through, and per-request full host-module vocabulary loading.
5. The current web checkout must pass TypeScript production build before this
   feature set can be considered merge-ready.

## 5. Canonical interpretation rules

- Same device/site/time/family means **compatible evidence**, not common cause.
- Earliest alarm means **observed first**, not root cause.
- `CORE` means central to the current chain's evidence profile, not causal root.
- `CONNECTOR` means articulation/bridge on the Audit Graph, not propagation source.
- `CANDIDATE_SPLIT` means review a tested low-conductance partition, not that the
  upstream grouping is wrong.
- `NO_LOW_CONDUCTANCE_CUT` means no qualifying cut among the tested candidates,
  not proof of global optimality.
- Topology navigation, physical adjacency, directed dependency and inferred
  incident graphs are different layers and must never be conflated.
- A raw-text entity match remains a candidate even if it is unique.
- A learned ranker score is neither a probability nor permission to bypass
  deterministic hard gates.
- Passing unit tests proves implemented behavior under tested fixtures; it does
  not establish operational data validity or production calibration.
