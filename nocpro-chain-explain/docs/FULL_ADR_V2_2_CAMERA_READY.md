# Full ADR Pack V2.2 — D1 Camera-Ready

V2.3.1 mathematical methodology remains frozen. This pass contains only editorial/fail-closed integration tightening; no new ADR numbers were introduced.

---

# ADR-0001: Keep `nocpro-mock` as a separate upstream simulator repository

- **Status:** Accepted — project integration decision
- **Date:** 2026-08-28
- **Scope:** Repository boundary / upstream simulation

## Context

The explanation system is downstream of NocPro and external operational inputs. During development, the real upstreams are unavailable, so a simulator is required. The simulator must be able to produce alarm snapshots, chain memberships, optional Gray-box metadata, synthetic inventory/topology, failure-domain membership, and optional maintenance/ticket context.

Placing the simulator inside `nocpro-chain-explain` would blur the production boundary and would make it easy for downstream code to depend on simulator internals.

## Decision

`nocpro-mock` SHALL remain a repository/process outside `nocpro-chain-explain`.

It MAY internally contain logical upstream modules such as `nocpro/`, `inventory/`, `context/`, `scenarios/`, `replay/`, and `producer/`, but the explanation system SHALL consume only the external Input Contract.

`nocpro-chain-explain` SHALL NOT import Python modules/classes from `nocpro-mock`.

## Rationale

The same dependency direction should hold in research and production: upstream systems publish state; the explanation system consumes state. This makes replacement of the mock by real NocPro/inventory sources straightforward and prevents circular test logic.

## Consequences

**Positive:** clean boundary, realistic integration, simulator is replaceable, provenance is explicit.

**Trade-offs:** cross-repository integration tests and contract compatibility checks are required.

## Alternatives considered

1. Put the mock inside the explanation repo — rejected because it weakens the upstream/downstream boundary.
2. Split NocPro, topology and context into three mock services — rejected for now because one simulator repository is sufficient.
3. Read CSV directly inside analysis code — allowed only as a test fixture path, not as the system boundary.

## Implementation implications

Recommended workspace:

```text
workspace/
├── nocpro-mock/
└── nocpro-chain-explain/
```

The mock must stamp logical source (`nocpro`, `inventory`, `context`) and `source_kind`.

## Invariants / required tests

- Downstream code must not import `nocpro_mock.*`.
- The same downstream logic must work with mock and future real upstream producers.
- Synthetic inputs must never be silently reclassified as real external validation.

## References

V2.3.1 sections 1–2 and 12.


---

# ADR-0002: Use one versioned Input Contract as the canonical integration schema

- **Status:** Accepted — implementation architecture
- **Date:** 2026-08-28
- **Scope:** Contracts / schema evolution

## Context

The system consumes several logical upstream inputs: alarms, chain partition, optional system metadata, topology/inventory, failure domains and operational context. If the mock and explanation repository invent separate schemas, semantic drift will occur.

The project is currently a two-repository project. Creating a third contracts repository adds unnecessary overhead for a one-person implementation.

## Decision

The canonical Input Contract SHALL live in `nocpro-chain-explain`, under a dedicated versioned contract directory such as:

```text
contracts/
└── v1/
    ├── snapshot.schema.json
    ├── alarm.schema.json
    ├── chain.schema.json
    ├── system_metadata.schema.json
    ├── topology.schema.json
    └── context.schema.json
```

`nocpro-mock` SHALL consume/export payloads conforming to these artifacts. CI SHALL verify contract compatibility.

The contract SHALL define at minimum: `Snapshot`, `Alarm`, `Chain`, `ChainMembership`, `SystemMetadata`, `TopologyNode`, `TopologyEdge`, `FailureDomain`, `AlarmResourceMapping`, and optional `OperationalContext`.

Every envelope SHALL carry `schema_version`, `event_id` or deterministic payload identity, `source`, `source_kind`, `produced_at`, and relevant snapshot/topology identifiers.

Data/Integration D1 adds contract fields/objects where applicable:
- `source_kind ∈ {REAL_LIVE, REAL_EXPORT_REPLAY, SYNTHETIC_TEST, BACKFILL}`;
- `ChainingUsageAssessment {source_id, source_version, chaining_config_version, executed_rule_set/attribute_set?, snapshot/run_context, usage}`;
- `usage ∈ {CONFIRMED_USED, CONFIRMED_NOT_USED, UNKNOWN}`;
- `quality_status ∈ {PASS, FAIL, UNKNOWN}` plus subtype-specific Quality inputs stamped by `config_version`;
- `system_pair_status ∈ {EVALUATED, NOT_EVALUATED, UNKNOWN}`;
- `coverage_scope ∈ {FULL_PAIR_SPACE, BOUNDED_COMPARISON, UNKNOWN}` for aggregate system characteristics;
- topology mapping metadata: `topology_layer`, `mapping_method`, `mapping_confidence`, `mapping_status`, `source_version`, `freshness`.

`BACKFILL` means bootstrap/training/backfill state; historical real exports replayed as observations use `REAL_EXPORT_REPLAY`, not `BACKFILL` merely because they are old.

## Rationale

One versioned schema is easier to govern than shared Python imports or a third repository. It keeps storage schema separate from integration schema and supports direct JSON and Kafka transports with identical semantics.

## Consequences

**Positive:** single semantic source of truth, reproducible parsing, simpler integration tests.

**Trade-offs:** schema evolution and compatibility tests become mandatory.

## Alternatives considered

1. A third `nocpro-contracts` repo — rejected for the current one-person scope.
2. Local Pydantic models independently defined in both repos — rejected due to drift.
3. Database tables as the wire contract — rejected because persistence and integration are different concerns.

## Implementation implications

Pydantic models MAY be generated from/validated against the versioned schema. TypeScript API types may also be generated from the same semantic definitions, but web types are not the integration authority.

## Invariants / required tests

- Unknown incompatible major versions are rejected.
- Additive compatible fields do not break existing consumers.
- Provenance class, provenance subtype, `source_kind`, usage assessment, `quality_status`, relation type, mapping status and snapshot identifiers are enum/format validated.
- Missing system pair metadata defaults to `UNKNOWN`, never silently to NEUTRAL/NOT_EVALUATED.
- `chaining_usage` is not stored as one global boolean/property for an entire topology/history store; it must be resolvable in chaining config/run context.
- Missing Quality needed for validation yields `quality_status=UNKNOWN`.
- The same fixture must parse identically through direct and Kafka adapters.

## References

V2.3.1 sections 2, 4, 4B and 12.


---

# ADR-0003: Keep Kafka as a proposed integration transport, not a prerequisite for the research core

- **Status:** Proposed — adopt only after the direct prototype path is working
- **Date:** 2026-08-28
- **Scope:** Messaging / integration

## Context

The target integration is naturally event-oriented and replayable, so Kafka is a plausible transport. However, the research contribution is the explanation methodology, not messaging infrastructure. Making Kafka the default path from week one creates plumbing work before the Evidence Engine is testable.

Cross-topic ordering and snapshot completeness also introduce non-trivial integration semantics.

## Decision

Kafka SHALL remain **Proposed** until the direct snapshot adapter and core Evidence/WHY path are working.

When adopted, Kafka SHALL be a transport adapter around the same versioned Input Contract. The Evidence Engine, Tier-1A/Tier-1B/Tier-2 logic and persistence semantics SHALL NOT depend on Kafka APIs.

Kafka MUST NOT be required to run unit tests, spec-sanity tests, or local algorithm experiments.

## Rationale

This preserves a realistic future integration path without allowing infrastructure to dominate the P0/P1 implementation schedule.

## Consequences

**Positive:** replay and decoupling remain available later; research logic stays transport-agnostic.

**Trade-offs:** direct and Kafka adapters must be kept behaviorally equivalent.

## Alternatives considered

1. Kafka as mandatory/default path immediately — rejected due to scope risk.
2. HTTP only forever — not selected because replay/decoupling may be useful later.
3. Shared DB polling — rejected due to tight upstream coupling.

## Implementation implications

If Kafka is accepted later, define snapshot barrier/completeness semantics before analysis is triggered. Multi-topic layouts are not allowed to rely on cross-topic ordering.

## Invariants / required tests

- Core tests run with no Kafka broker.
- Kafka and direct adapters produce identical canonical snapshot state for the same fixture.
- Incomplete Kafka snapshots never trigger Tier-1A.
- Replayed duplicate events are idempotent.

## References

Implementation decision; V2.3.1 sections 1, 3 and 11 motivate snapshot/replay but do not mandate Kafka.


---

# ADR-0004: Use PostgreSQL as the proposed primary persistent store

- **Status:** Proposed — research implementation default, benchmark before production commitment
- **Date:** 2026-08-28
- **Scope:** Persistence

## Context

The platform needs persistent state for snapshots, alarms, chain memberships, descriptors, lineage, topology versions, explanation runs, provenance and configuration versions. The dominant data model is relational and versioned. Pair evidence must not be materialized globally.

## Decision

PostgreSQL SHALL be the default candidate for the research implementation.

Core structured fields SHOULD be relational; raw/flexible payloads MAY use `JSONB`. Redis, object storage, graph databases or analytical stores MAY be added only after a measured need appears.

Kafka, if used, is transport/replay and SHALL NOT replace application state.

## Rationale

PostgreSQL minimizes infrastructure while fitting snapshot/membership/versioning/provenance queries. Topology being a graph is not sufficient reason to make a graph database the primary store.

## Consequences

**Positive:** transactional integrity, mature indexing, one primary store.

**Trade-offs:** very large historical analytics or specialized graph traversal may later require complementary systems.

## Alternatives considered

1. Neo4j primary — rejected for MVP/P1.
2. ClickHouse primary — rejected because the application needs transactional relational state.
3. TimescaleDB first — deferred; alarm chaining is not primarily a metric time-series workload.

## Implementation implications

Do not design any table requiring O(N²) rows per snapshot. Pair details are lazy/cacheable. Schema migrations must preserve snapshot/config provenance.

## Invariants / required tests

- Membership rows cannot exist without corresponding snapshot/chain/alarm state.
- Ingestion is idempotent on natural identifiers.
- Every persisted explanation run identifies snapshot, engine/config version and source provenance.
- No all-pairs evidence table is created for global snapshots.

## References

V2.3.1 sections 3, 4, 7, 8 and 11.


---

# ADR-0005: Treat the snapshot as the primary processing boundary

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Processing model

## Context

NocPro re-groups the active alarm set approximately once per minute. Explanation and evolution therefore operate on snapshot state, not on an assumption of one permanent chain identity.

## Decision

Every analysis input SHALL be associated with `snapshot_id` and `snapshot_time`. Tier-1A SHALL run only on a complete canonical snapshot. Chain IDs are snapshot-scoped identifiers, not evolving incident identities.

## Rationale

This matches the production chaining process and makes evolution semantics explicit.

## Consequences

**Positive:** deterministic replay and correct evolution logic.

**Trade-offs:** snapshot completeness and versioning must be tracked carefully.

## Alternatives considered

1. Treat chain ID as globally stable — rejected.
2. Run analysis directly on a continuously mutating table — rejected for the baseline because it destroys reproducibility.

## Implementation implications

Snapshot state must include active alarms, partition/membership and any upstream metadata valid for that snapshot. Topology is linked by topology version/validity interval.

## Invariants / required tests

- Tier-1A never runs on an incomplete snapshot.
- Re-running `(snapshot, config_version)` is deterministic.
- Evolution compares canonical snapshot states, not raw chain IDs alone.

## References

V2.3.1 sections 1, 3 and 7.


---

# ADR-0006: Support Gray-box and Black-box modes with strict wording discipline

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Explanation semantics

## Context

The module may receive NocPro metadata in Gray-box mode, or only alarms/partition plus context in Black-box mode. Post-hoc evidence must not be misrepresented as the model's internal reason. External provenance also does not by itself prove independence from chaining.

## Decision

Gray-box MAY show system-provided facts separately from post-hoc analysis. Black-box claims SHALL use wording such as “post-hoc support” and SHALL NOT say the model grouped alarms because of topology, time or any other feature.

Connector/extender labels SHALL be displayed as reported metadata unless their operational semantics are independently documented. The UI SHALL NOT infer causal/structural meaning from the label name alone.

Black-box SHALL NOT use wording such as “independently validates NocPro” unless ADR-0010's source-kind + chaining-usage + quality gate is satisfied.

## Rationale

This prevents overclaiming and preserves graceful degradation when internals are unavailable.

## Consequences

**Positive:** defensible explanations under partial observability.

**Trade-offs:** wording templates and API claim types require explicit mode/provenance information.

## Alternatives considered

1. Treat metadata and post-hoc evidence as one score — rejected.
2. Infer Louvain/rule internals from outputs — rejected.

## Implementation implications

Every claim payload should include `mode`, provenance/source references and config version. Gray-box system facts should render in a separate section.

## Invariants / required tests

- Black-box templates contain no “model grouped because …” language.
- Connector/extender metadata is not translated into unsupported semantics.
- Removing Gray-box metadata does not break Black-box WHY endpoints.

## References

V2.3.1 sections 2, 9 and 12.


---

# ADR-0007: Enforce four provenance classes throughout data, algorithms and UI

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Provenance model

## Context

Evidence from system metadata, raw alarm analysis, learned grouping behavior and external operational sources has different epistemic meaning. Combining them without labels creates circular validation.

## Decision

The system SHALL enforce exactly these top-level provenance classes:

- `SYSTEM_FACT`
- `POST_HOC`
- `BEHAVIORAL`
- `EXTERNAL_OPERATIONAL`

Subtypes MAY refine them, such as `TOPOLOGY_EXTERNAL`, `TICKET`, `MAINTENANCE`, `OPERATOR_LABEL`, `FAULT_INJECTION`.

`source_kind` is a separate dimension with baseline values `REAL_LIVE`, `REAL_EXPORT_REPLAY`, `SYNTHETIC_TEST`, `BACKFILL`. `BACKFILL` means bootstrap/training/backfill state; old-but-real observations replayed for evaluation use `REAL_EXPORT_REPLAY`.

`chaining_usage` is another metadata dimension: `CONFIRMED_USED`, `CONFIRMED_NOT_USED`, `UNKNOWN`. It is not a fifth provenance class. `EXTERNAL_OPERATIONAL` does not imply `CONFIRMED_NOT_USED`.

`quality_status ∈ {PASS, FAIL, UNKNOWN}` is also not a provenance class; it is an eligibility result computed from subtype-specific Quality fields under a versioned config.

## Rationale

The four-way separation is the central anti-circularity rule of V2.3.1.

## Consequences

**Positive:** claims remain auditable and validation is not self-confirming.

**Trade-offs:** every evidence producer must stamp provenance correctly.

## Alternatives considered

1. A single “independent evidence” class — rejected because raw fields may be chaining features.
2. Treat history as external validation — rejected as circular.

## Implementation implications

Provenance must be present in schemas, evidence objects, persisted claims and UI drill-down.

## Invariants / required tests

- Raw alarm-derived equality/burst/semantic evidence is not labeled independent.
- Grouping history is BEHAVIORAL.
- System metadata is not used as external validation.
- EXTERNAL_OPERATIONAL with `chaining_usage=UNKNOWN` is not treated as independent validation.
- `SYNTHETIC_TEST` and `BACKFILL` cannot validate; `REAL_LIVE`/`REAL_EXPORT_REPLAY` only enter the next validation gates.

## References

V2.3.1 sections 0, 4 and 12.


---

# ADR-0008: Keep pair evidence, chain descriptors and chain rule annotations type-separated

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evidence type discipline

## Context

One raw field can generate pair evidence, chain descriptors and system annotations. If those objects are treated as interchangeable players, agreement and attribution double count the same information.

## Decision

The provenance DAG SHALL distinguish:

1. Normalized pair-evidence nodes in `K_pair` (`s+`,`s-` in [0,1]).
2. Pair-scope system metadata (`M_pair`): exact-pair raw score/veto/decision/status.
3. Chain-level descriptor nodes.
4. Chain/rule system annotations (`M_chain_rule`): rule, connector/extender, merge.
5. Aggregate chain system characteristics (`M_chain_characteristic`): characteristic/value/threshold/pair_count/coverage_scope.
6. NocPro Attribute configuration (`M_attribute_config`): type/content/algorithmType/filterName/weight.

Only normalized pair-evidence nodes may participate in pair-level Agreement/G*. `M_pair`, `M_chain_rule`, `M_chain_characteristic` and `M_attribute_config` remain `SYSTEM_FACT` and are displayed separately.

Raw NocPro scores/vetoes belong to `M_pair`, not `M_attribute_config`, and SHALL NOT be normalized into Evidence-channel `s_k`. Aggregate counts belong to `M_chain_characteristic` and SHALL NOT synthesize exact pair edges. NocPro `TimeWindow`, `HistorySimilarity`, `TopologySimilarity` SHALL NOT be collapsed into the module's `T_burst/T_delay`, `H`, or `Dep_*`.

## Rationale

The mathematical contract in V2.3.1 explicitly separates pair and chain semantics.

## Consequences

**Positive:** prevents representation artifacts and circular pair consensus.

**Trade-offs:** models and APIs need explicit evidence scope/type.

## Alternatives considered

1. Flatten all evidence into generic features — rejected.
2. Project aggregate chain characteristics into pair evidence — rejected unless the source resolves exact pairs.

## Implementation implications

Use typed enums/objects such as `PAIR_EVIDENCE`, `SYSTEM_PAIR_METADATA`, `CHAIN_DESCRIPTOR`, `CHAIN_RULE_ANNOTATION`, `CHAIN_CHARACTERISTIC`, `ATTRIBUTE_CONFIG`.

`M_pair` should carry `system_pair_status ∈ {EVALUATED, NOT_EVALUATED, UNKNOWN}` when available. Missing metadata defaults to `UNKNOWN`.

## Invariants / required tests

- A chain descriptor never changes pair Agreement.
- `M_chain_rule`, `M_chain_characteristic` and `M_attribute_config` never become pair players.
- Aggregate pair counts from NocPro do not create synthetic exact pair edges.
- Raw system score `2.0` or veto `-999999999` never enters normalized Fit/Agreement/G*/Attribution.
- Missing M_pair does not become NEUTRAL.
- System TimeWindow/History/Topology and module T/H/Dep remain distinct typed objects.

## References

V2.3.1 sections 4 and 4A.


---

# ADR-0009: Deduplicate multi-channel evidence by derivation group before cross-channel aggregation

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evidence aggregation

## Context

Several channels may derive from the same underlying field or evidence source. Counting them independently can inflate agreement, graph weight and attribution.

## Decision

Each pair-evidence channel SHALL carry a derivation tag. Channel support is thresholded first:

`b_k = 1[available_k and s_k+ >= theta_k]`.

Then support is deduplicated by derivation group:

`b_g = max_{k in g} b_k`.

When `b_g=1`, `s_g+` is the maximum supported channel score inside the group. `s_g-` is aggregated separately. There is no arbitrary group threshold `theta_g`.

Agreement, eligible G* weights and Evidence Coverage Attribution SHALL operate on derivation groups, not raw channels.

## Rationale

This preserves the semantics of “one underlying derivation = at most one vote”.

## Consequences

**Positive:** stable results under feature representation refactoring.

**Trade-offs:** every channel must define a derivation tag.

## Alternatives considered

1. Sum/mean channels directly — rejected.
2. Max score first then compare against one group threshold — rejected because channel thresholds can differ.

## Implementation implications

Keep channel threshold provenance in config. Group aggregation must not erase the channel-level decision trace.

## Invariants / required tests

- Adding three channels derived from `reference` changes group-level support by at most one group.
- The same derivation group cannot receive three attribution players.
- Channel-specific thresholds are applied before group aggregation.

## References

V2.3.1 sections 0, 4B and 8.4.


---

# ADR-0010: Apply source-kind gating before the Explain/Role/Audit/Validate eligibility mask

- **Status:** Accepted — frozen methodology plus synthetic-source implementation guard
- **Date:** 2026-08-28
- **Scope:** Eligibility / anti-circularity

## Context

V2.3.1 defines different eligibility for system, post-hoc, behavioral and external operational evidence. Development fixtures add another dimension: synthetic sources can have the same structural shape as real external topology/tickets but must not be counted as operational validation.

## Decision

Validation SHALL be evaluated in four fail-closed stages:

1. **Source-kind gate** — only `REAL_LIVE` and `REAL_EXPORT_REPLAY` may proceed toward validation. `SYNTHETIC_TEST` and `BACKFILL` => Validate NO.
2. **Chaining-usage / independence gate** — validation requires `chaining_usage=CONFIRMED_NOT_USED`. `UNKNOWN` and `CONFIRMED_USED` => Validate NO.
3. **Provenance/subtype gate** — the subtype must be validation-eligible.
4. **Quality gate** — validation requires `quality_status=PASS`; `FAIL`/`UNKNOWN` => Validate NO. Quality thresholds are subtype-specific and versioned.

`chaining_usage` constrains **Validate only**. Explain/Role/Audit continue to follow their provenance/type masks.

Default methodology:
- POST_HOC: Explain yes, Role yes, Audit yes, Validate no.
- EXTERNAL_OPERATIONAL/TOPOLOGY_EXTERNAL: Explain yes, Role yes, Audit yes, Validate yes **only when source_kind∈{REAL_LIVE,REAL_EXPORT_REPLAY}, chaining_usage=CONFIRMED_NOT_USED, subtype allows validation, and quality_status=PASS**.
- SYSTEM_FACT: displayed separately; Role/Audit/Validate no by default.
- BEHAVIORAL: Explain yes with label; Role/Audit/Validate no by default.
- Ticket/operator/maintenance/fault-injection: explain/validate according to subtype; no positive structural audit edge by default.

## Rationale

The combined source-kind + chaining-usage + Quality gates prevent synthetic self-validation, real-but-not-independent topology/history, and low/unknown-quality sources from validating NocPro.

## Consequences

**Positive:** preserves evaluation validity.

**Trade-offs:** eligibility is multi-dimensional rather than one enum lookup.

## Alternatives considered

1. Provenance-only eligibility — rejected because synthetic external-shaped data can leak into validation.
2. Filter synthetic results after scoring — rejected because the contamination has already occurred.

## Implementation implications

Implement one central eligibility service/library; do not duplicate ad-hoc checks in engines.

`chaining_usage` SHALL be resolved using source identity/version plus chaining configuration/run context (executed rule/attribute set when known). It SHALL NOT be a single coarse USED/NOT_USED property for an entire topology/history store. If complete executed config is unavailable, resolve `UNKNOWN`.

## Invariants / required tests

- `SYNTHETIC_TEST + TOPOLOGY_EXTERNAL` cannot produce a real validation verdict.
- `BACKFILL + EXTERNAL_OPERATIONAL` cannot produce a validation verdict.
- `REAL_EXPORT_REPLAY` may proceed to later gates but does not automatically validate.
- `EXTERNAL_OPERATIONAL + chaining_usage=UNKNOWN` cannot produce a validation verdict.
- `EXTERNAL_OPERATIONAL + chaining_usage=CONFIRMED_USED` cannot produce a validation verdict.
- `quality_status=UNKNOWN` or `FAIL` cannot produce a validation verdict.
- Changing `chaining_usage` must not change Explain/Role/Audit eligibility for the same evidence object.
- SYSTEM_FACT support does not strengthen `G*_audit`.
- BEHAVIORAL support does not change external Agreement.

## References

V2.3.1 sections 4B and 12; synthetic guard supports development without violating those rules.


---

# ADR-0011: Keep `K_pair` pairwise evidence separate from `H_domain` failure-domain hyperedges

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evidence representation

## Context

Failure domains such as SRLG/fiber/power/rack/site/service instance are set-valued operational structures, not naturally pairwise evidence channels.

## Decision

`K_pair` SHALL contain only atomic pairwise channels. `H_domain` SHALL remain a hyperedge/set representation with domain identity, type, members, source, quality and provenance.

`H_domain` SHALL NOT be clique-projected into `G*_explain` or `G*_audit`.

Failure-domain membership MAY propose a candidate block/cut, but the quality of that cut SHALL be evaluated on the pairwise `G*_audit` only.

## Rationale

This preserves the source semantics and prevents one shared domain from creating O(m²) artificial positive edges.

## Consequences

**Positive:** no representation inflation; failure-domain explanations stay human-readable.

**Trade-offs:** algorithms that need pairwise graphs must explicitly handle domain sets separately.

## Alternatives considered

1. Clique projection — rejected.
2. Ignore failure domains — rejected because they are valuable P1 context/explanation.

## Implementation implications

Provide explicit domain membership APIs and candidate-set generation functions rather than a generic `score(i,j)`.

## Invariants / required tests

- No `s(i,j)` is fabricated for `H_domain`.
- Adding a domain cannot directly increase `w*_audit`.
- Domain membership can generate a candidate cut without generating pair edges.

## References

V2.3.1 sections 0, 4, 4A and 6.


---

# ADR-0012: Use contextual burst segmentation and directed local-mass delay typicality

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Temporal evidence

## Context

Two temporal signals are needed: contextual burst membership and learned delay compatibility. Global burst segmentation is invalid for a nationwide continuous stream, and CDF centrality fails on multimodal delay distributions.

Data/Integration D1: NocPro's own `TimeWindow` Attribute is a SYSTEM_FACT with system semantics (including veto) and is not the same object as `T_burst` or `T_delay`.

## Decision

`T_burst` SHALL segment within a blocking context such as region/site/resource neighborhood/service domain, using configured silent-gap/change-point logic. It SHALL NOT segment the entire global alarm stream as one sequence.

`T_delay` SHALL use directed delay `Δt = t_B - t_A` for relation A→B. Typicality SHALL use normalized local probability mass:

`s+(Δt) = P_r(|T-Δt|<=h) / max_t P_r(|T-t|<=h)`.

CDF may be used only for tail extremeness, not typicality.

Histogram/KDE/fitted likelihood choice and bandwidth `h` SHALL be model-selected/validated on held-out data when enough data exists; otherwise a documented backoff/default is used and stamped in config.

## Rationale

These rules directly address the multimodal midpoint failure and directionality problem in the final spec.

## Consequences

**Positive:** semantically correct temporal evidence.

**Trade-offs:** temporal models need backoff and calibration data.

## Alternatives considered

1. Global silent-gap burst segmentation — rejected.
2. `2*min(F,1-F)` typicality — rejected for multimodal distributions.
3. Undirected absolute delay only — rejected when relation direction is known.

## Implementation implications

Backoff: type→family→category. Threshold/model source must be labeled domain/data-driven/behavioral as appropriate.

## Invariants / required tests

- Bimodal `{~2s,~100s}` gives low typicality near 50s.
- A system-provided `TimeWindow <600s` characteristic does not become `T_burst`/`T_delay` evidence.
- A→B learned delay does not automatically match B→A.
- Burst membership changes when the blocking context changes, not because unrelated national alarms fill the gap.

## References

V2.3.1 sections 4A and 13.


---

# ADR-0013: Use episode-deduplicated grouping history with positive evidence only for lift > 1

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Behavioral history

## Context

Repeated snapshots of one long storm can inflate co-grouping counts. Behavioral history also cannot validate the grouping engine because it is learned from the engine's own outputs.

Data/Integration D1: NocPro `HistorySimilarity` or aggregate historical-pair characteristics, when provided by Gray-box metadata, are SYSTEM_FACT and are not the module's behavioral `H`.

## Decision

History SHALL be episode-deduplicated per evolving incident. Positive history evidence is zero when support is below `s_min` or lift≤1.

For lift>1:

`strength_H = min(1, log(lift)/log(L_cap))`

and

`reliability(s)=1-exp(-s/lambda_H)`,

with versioned parameters/backoff.

History bootstrap SHALL use a strict temporal split: history window precedes the target snapshot being explained. The target snapshot SHALL NOT enter H before its explanation/evaluation result is produced.

## Rationale

This prevents storm inflation, accidental anti-association-as-support, and same-data leakage.

## Consequences

**Positive:** behavioral support has controlled semantics.

**Trade-offs:** history requires episode/lineage awareness and temporal evaluation splits.

## Alternatives considered

1. Raw co-occurrence count — rejected.
2. Learn H from the same target snapshot — rejected as leakage.
3. Use history as validation — rejected as circular.

## Implementation implications

`bootstrap_history.py` in the mock must mark data as backfill/test state and must not act as an online feed for the target snapshot.

## Invariants / required tests

- lift≤1 => `s_H+ = 0`.
- One repeated incident episode does not count as dozens of independent history samples.
- Target snapshot is absent from the history store used to explain itself.
- A NocPro-reported historical pair count is never copied directly into `H.support` or `H.lift`.

## References

V2.3.1 sections 4A, 12 and 13.


---

# ADR-0014: Use Tier-1A background, Tier-1B interactive-local and Tier-2 on-demand execution

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Execution tiers

## Context

The system must support large snapshots while keeping operator interaction fast. Global work, local chain explanation and deep analysis have different computational profiles.

## Decision

Use:
- Tier-1A: snapshot background precompute, design objective 10–30s per snapshot.
- Tier-1B: local/lazy chain analysis on open, design objective P95<5s.
- Tier-2: asynchronous per-chain deep dive, design objective 5–30s.

These numbers are design objectives pending benchmark, not guaranteed SLOs.

Tier-1B SHALL never wait for Tier-2.

## Rationale

The split resolves the global-background vs local-materialization tension in earlier designs.

## Consequences

**Positive:** responsive UI and bounded deep computation.

**Trade-offs:** cache/version coordination is required.

## Alternatives considered

1. Compute everything every snapshot — rejected.
2. Compute everything on click — rejected because global indexes/lineage are reusable.

## Implementation implications

Cache keys include chain fingerprint/snapshot/config version as appropriate.

## Invariants / required tests

- Tier-2 runs per chain, never whole snapshot.
- Tier-1B returns without a Tier-2 result.
- Drift tiers only compare artifacts that actually exist at both snapshots.

## References

V2.3.1 sections 3, 7, 8 and 11.


---

# ADR-0015: Prohibit unguarded O(N²) pair materialization at both snapshot and large-chain scale

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Scalability

## Context

A 100k-alarm snapshot has ~5e9 pairs. Even a single 20k-alarm chain has ~200M pairs. Merely banning global all-pairs is insufficient if Tier-1B or Tier-2 silently nests over all pairs of a huge chain.

## Decision

The system SHALL NOT materialize all alarm pairs for a global snapshot.

For large chains, unguarded `O(|C|²)` materialization is also prohibited by default.

Required patterns:
- Pair WHY: compute on click.
- Equality/entity Fit: indexed/grouped counts.
- Temporal: sort/window or bounded neighborhood.
- Descriptor: bitmap/inverted counts.
- Attribution: inverted counts/sampling/supernode approximation for large chains.
- Audit: full only under configured chain-size threshold; otherwise supernode or guaranteed sparsification policy.

## Rationale

This turns the scalability statement into an enforceable implementation rule.

## Consequences

**Positive:** prevents catastrophic memory/time behavior.

**Trade-offs:** exactness may be replaced by controlled approximation on very large chains.

## Alternatives considered

1. “Per-chain all-pairs is fine” — rejected.
2. Top-K graph for all algorithms — rejected because audit correctness can be distorted.

## Implementation implications

A configurable guard threshold SHALL select exact vs bounded/aggregate execution. Benchmarks must include large-chain shapes, not only global N.

## Invariants / required tests

- No Tier-1B default code path executes nested loops over 20k members.
- Pair endpoints materialize only requested/bounded pairs.
- Attribution on a large chain proves it did not allocate C(n,2) state.

## References

V2.3.1 sections 8.4 and 11.


---

# ADR-0016: Keep statistical, visualization and audit graphs distinct

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Graph semantics

## Context

Top-K pruning is useful for UI but can fabricate bridges/weak cuts. Statistical counts and structural audit have different correctness requirements.

## Decision

Maintain three graph purposes:

- `STATISTICAL`: full indexed counts/statistics, not a display graph.
- `VISUALIZATION`: bounded/top-K for UI only.
- `AUDIT`: full eligible graph under a size threshold; otherwise supernode/sparsifier policy with explicit guarantees.

Structural verdicts SHALL NOT run on the visualization graph.

## Rationale

This prevents UI sparsification artifacts from becoming methodology claims.

## Consequences

**Positive:** structural audit remains defensible.

**Trade-offs:** multiple representations/caches may coexist.

## Alternatives considered

1. One graph for everything — rejected.
2. Always full graph — rejected for very large chains.

## Implementation implications

Graph objects/DTOs should carry purpose/type explicitly.

## Invariants / required tests

- Changing visualization top-K does not change audit verdict on the same canonical inputs.
- Audit never reads a `VISUALIZATION` graph instance.

## References

V2.3.1 sections 6 and 11.


---

# ADR-0017: Separate IDENTITY and CONTRASTIVE descriptor search objectives

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Descriptor mining

## Context

A globally common predicate can still strongly distinguish a chain from nearby competitors. One global precision floor would suppress useful contrastive rules.

## Decision

Implement two searches over the same bounded bitmap engine:

- IDENTITY: maximize coverage subject to `Precision_global >= p_min`.
- CONTRASTIVE: maximize coverage subject to `Precision_local >= p_local` on the fixed local competitor universe `U_local`.

Redundancy filtering applies within each descriptor type.

## Rationale

The two questions are semantically different: “what defines this chain?” vs “what distinguishes it from nearby chains?”.

## Consequences

**Positive:** explanations match the user question.

**Trade-offs:** two objective functions and metrics must be maintained.

## Alternatives considered

1. One descriptor ranking for all WHY questions — rejected.
2. Full gFIM in the interactive tier — rejected for latency.

## Implementation implications

Use bounded depth/beam/top-K predicates and bitmap-backed counts. `U_local` must be deterministic from the blocking index.

## Invariants / required tests

- A globally common but locally discriminative rule can appear as CONTRASTIVE.
- Redundant extents (e.g. Jaccard≥0.9) are filtered within each type.

## References

V2.3.1 section 5.


---

# ADR-0018: Audit the module's evidence graph, not inferred Louvain internals

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Structural audit

## Context

The module does not have guaranteed access to original Louvain edge weights, node movement or ΔQ. Pretending reconstructed evidence is the original chaining graph would overclaim.

## Decision

Structural audit SHALL operate on `G*_audit`, built only from audit-eligible derivation groups.

Claims SHALL describe robustness/separation of the evidence graph and SHALL NOT claim that NocPro/Louvain would necessarily split the chain.

## Rationale

This preserves the partial-observability contract.

## Consequences

**Positive:** no fake model introspection.

**Trade-offs:** audit is an independent post-hoc structural test, not a proof of model error.

## Alternatives considered

1. Reconstruct a presumed Louvain graph — rejected.
2. Rerun Louvain and call differences counterfactual proof — rejected.

## Implementation implications

If exact NocPro internals become available later, add an adapter without changing the current audit semantics.

## Invariants / required tests

- Audit outputs use “review candidate” wording.
- No endpoint exposes reconstructed edges as “original Louvain edges”.

## References

V2.3.1 sections 6, 8.1 and 10.


---

# ADR-0019: Generate structural candidate cuts deterministically and score them on `G*_audit`

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Over-merge analysis

## Context

Running a second community detector would make the audit hard to explain and add another model. V2.3.1 instead defines deterministic candidate generators.

## Decision

Candidate blocks SHALL come from:
- dominant entity values,
- thresholded dependency connected components,
- failure-domain membership sets,
- extents of top non-redundant IDENTITY descriptors,
plus defined union/difference combinations.

Failure-domain membership may propose a set but SHALL NOT be clique-projected.

For each valid balanced candidate S, compute conductance on `G*_audit`:

`Phi(S)=cut_weight/min(Vol(S),Vol(Sbar))`

with balance constraints.

`epsilon_Phi` SHALL use conditional calibration with fallback: detailed bin if enough samples → coarser size bin → global weak baseline with low-confidence label.

For small chains where the balance rule is impossible, the result is **SKIPPED/NOT_APPLICABLE**, not “stable”.

## Rationale

The candidate source remains auditable: the system can say which evidence family proposed the split and which audit graph scored it.

## Consequences

**Positive:** deterministic, explainable and reproducible.

**Trade-offs:** may miss a cut not represented by any candidate family.

## Alternatives considered

1. Run Louvain again — rejected.
2. Spectral cut by name without implementing normalized Laplacian/Fiedler/sweep — rejected.

## Implementation implications

Log candidate source and calibration fallback level. Over-merge is a multi-evidence verdict, not conductance alone.

## Invariants / required tests

- H_domain candidate generation creates no pair edges.
- Small chain policy returns SKIPPED.
- Candidate Φ is computed only on `G*_audit`.
- Fallback calibration is explicitly labeled.

## References

V2.3.1 sections 6 and 13.


---

# ADR-0020: Track evolving incidents with lineage rather than raw chain IDs

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evolution

## Context

A chain can receive a different snapshot-local ID even when its membership persists. Split/merge/recombination also require a graph of correspondence, not simple ID equality.

## Decision

Evolution SHALL:
1. Determine NEW/CLEARED alarms.
2. Restrict chain correspondence to `Active_both`.
3. Build bipartite lineage edges using intersection/containment rules with a small-chain exception.
4. Assign evolving-chain lineage components/branches.
5. Classify CONTINUE/GROW/SHRINK/SPLIT/MERGE/NEW/DISSOLVE/RECOMBINATION.
6. Decompose joined/left into new/reassigned/cleared/reassigned counts.

## Rationale

This measures actual production evolution rather than raw identifier churn.

## Consequences

**Positive:** correct turnover and branch semantics.

**Trade-offs:** lineage state must be persisted across snapshots.

## Alternatives considered

1. Compare chain IDs — rejected.
2. Use Jaccard alone without lifecycle decomposition — rejected.

## Implementation implications

Persist `lineage_component_id`, `branch_id`, `snapshot_chain_id` separately.

## Invariants / required tests

- Same membership with new raw chain ID can be CONTINUE.
- Δsize=0 with +10/-10 reports turnover 20.
- Small-chain matching follows the explicit exception.

## References

V2.3.1 section 7.


---

# ADR-0021: Separate explanation drift by execution tier and distinguish DATA_DRIFT from CONFIG_DRIFT

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Evolution / drift

## Context

Not every snapshot has Tier-1B/Tier-2 artifacts cached, and an explanation can change because thresholds/config changed rather than incident behavior.

## Decision

Implement:
- Tier-1A basic drift: membership/lifecycle/descriptor/coverage-discrimination changes.
- Tier-1B cached drift: roles/evidence composition only if both snapshots have corresponding 1B caches.
- Tier-2 deep drift: robustness/similar-incident differences only when both snapshots have Tier-2 results.

When config versions differ and the explanation changes because of analysis configuration, label `CONFIG_DRIFT`, not `DATA_DRIFT`.

## Rationale

This avoids fabricating historical roles/results and prevents config changes from being interpreted as incident behavior.

## Consequences

**Positive:** drift semantics are honest.

**Trade-offs:** some comparisons will be unavailable rather than forced.

## Alternatives considered

1. Recompute all historical Tier-1B/Tier-2 results automatically — rejected as default.
2. Ignore config version — rejected.

## Implementation implications

Every cached explanation artifact must include config version.

## Invariants / required tests

- Missing prior 1B cache yields unavailable 1B drift, not a recomputed hidden baseline.
- Changing only config can produce CONFIG_DRIFT with no DATA_DRIFT claim.

## References

V2.3.1 section 7.


---

# ADR-0022: Use normalized fingerprint + cosine similarity as the Similar Chains baseline

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Tier-2 similar incidents

## Context

Similar-incident retrieval should start with a deterministic baseline before graph motifs or more complex embeddings.

## Decision

Fingerprint each chain using:
- TF-IDF alarm family,
- TF-IDF device type,
- top IDENTITY descriptor predicates,
- size bin,
- duration bin.

Normalize and use cosine similarity as the baseline. Exclude the same evolving incident using `lineage_component_id`; provide a separate “previous states of this chain” mode.

## Rationale

Cosine is natural for the TF-IDF-heavy fingerprint and easy to benchmark.

## Consequences

**Positive:** simple, deterministic baseline.

**Trade-offs:** may miss structural similarities that motifs could later capture.

## Alternatives considered

1. Weighted Jaccard — benchmark alternative, not baseline.
2. Graph motif first — deferred.
3. Vector DB mandatory — rejected for initial scale.

## Implementation implications

Persist enough fingerprint metadata to reproduce scores.

## Invariants / required tests

- The nearest “different incident” result cannot be the same lineage component.
- Cosine result is deterministic for fixed fingerprint/config.

## References

V2.3.1 section 8.3.


---

# ADR-0023: Run Tier-2 asynchronously and only per chain

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Deep analysis execution

## Context

Structural robustness, similar incidents and attribution can exceed the interactive latency budget and are unnecessary for every chain.

## Decision

Tier-2 SHALL be invoked on demand per chain, asynchronously. Tier-1B remains available during execution. Results are cached by snapshot/chain fingerprint/config version.

## Rationale

This bounds cost and prevents deep analysis from blocking the UI.

## Consequences

**Positive:** responsive interaction.

**Trade-offs:** job state/progress handling is needed.

## Alternatives considered

1. Run Tier-2 on every snapshot — rejected.
2. Block the chain page until deep analysis finishes — rejected.

## Implementation implications

API may expose job IDs/SSE/polling; mechanism is implementation-specific.

## Invariants / required tests

- No Tier-2 job processes the entire snapshot by default.
- Tier-1B endpoint completes independently of Tier-2.

## References

V2.3.1 sections 3 and 8.


---

# ADR-0024: Use LLMs only for grounded narrative rendering, never as the reasoning source

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** LLM usage

## Context

The contribution is a structured, provenance-first explanation engine. Letting an LLM invent reasons would break reproducibility and traceability.

## Decision

LLMs MAY render natural-language narratives from structured claims/evidence at P2. They SHALL NOT create new evidence, change scores, infer root causes unsupported by structured analysis, or bypass provenance.

## Rationale

This preserves deterministic methodology and allows optional UX improvements.

## Consequences

**Positive:** narrative convenience without making the LLM an epistemic source.

**Trade-offs:** generated text must remain constrained/grounded.

## Alternatives considered

1. LLM as primary explainer — rejected.
2. LLM to infer missing topology/causality — rejected.

## Implementation implications

Narrative inputs should be structured claim objects. Rendered text should link back to those objects.

## Invariants / required tests

- Removing the LLM leaves all core explanation functionality intact.
- LLM output cannot create a new validation verdict.

## References

V2.3.1 sections 8.6 and 10.


---

# ADR-0025: Version all analysis configuration and record parameter provenance

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Configuration governance

## Context

The methodology contains many thresholds and scales. Hardcoding them across engines would make results irreproducible and would break CONFIG_DRIFT semantics.

## Decision

All analysis parameters SHALL live in versioned configuration, e.g. `config/thresholds/v1.yaml`.

Each parameter SHALL record value and source category where applicable:
- `SYSTEM_PROVIDED`
- `DATA_DRIVEN`
- `DOCUMENTED_DEFAULT`

Model-selection outcomes and threshold provenance SHALL be stampable into explanation provenance.

Every explanation/cache/run SHALL record `config_version`.

## Rationale

Versioned configuration is required for traceability, sensitivity analysis and correct drift labeling.

## Consequences

**Positive:** reproducibility and auditability.

**Trade-offs:** config migration/version management becomes part of the codebase.

## Alternatives considered

1. Constants inside engine code — rejected.
2. One unversioned runtime config — rejected.

## Implementation implications

Ship a concrete `v1.yaml` baseline before implementing multiple engines. Sensitivity analysis reads the same parameter registry.

## Invariants / required tests

- No methodology threshold exists only as an anonymous code literal.
- Re-running a snapshot with the same code/config is deterministic.
- Config changes are visible to drift logic.

## References

V2.3.1 sections 4A, 4B, 7, 11 and 13.


---

# ADR-0026: Mark mock-generated topology, context and labels as synthetic test sources

- **Status:** Accepted — project/test provenance decision
- **Date:** 2026-08-28
- **Scope:** Mock data / evaluation hygiene

## Context

The mock may generate topology or context from the alarm data to enable development before real inventory/tickets are available. Such data can look operationally realistic but is not independent evidence.

## Decision

Mock-generated topology/context SHALL use `source_kind=SYNTHETIC_TEST`.

Replayed exports originating from real systems SHALL use a distinct kind such as `REAL_EXPORT_REPLAY`; replay origin does not automatically mean the data is current/independent enough for operational validation.

It MAY carry a structural provenance subtype needed for code-path testing, but the source-kind gate in ADR-0010 SHALL exclude it from real operational validation metrics/verdicts.

Synthetic edge/domain generation SHALL be deterministic for a fixed fixture/config/seed and SHALL record a generation rule.

## Rationale

This allows testing dependency channels without falsely claiming external validation.

## Consequences

**Positive:** development can proceed before real topology exists.

**Trade-offs:** demo wording must clearly indicate synthetic input.

## Alternatives considered

1. Pretend generated topology is `TOPOLOGY_EXTERNAL` real evidence — rejected.
2. Random topology with no generation trace — rejected.

## Implementation implications

Mock topology generators should derive plausible entities from available fields but preserve explicit synthetic provenance.

## Invariants / required tests

- Synthetic topology cannot satisfy real validation eligibility.
- `REAL_EXPORT_REPLAY` is distinguishable from `REAL_LIVE` and still passes through chaining-usage/quality validation gates.
- Same fixture/config/seed produces the same generated topology.
- Generated edges/domains include generation-rule metadata.

## References

V2.3.1 provenance/validation principles in sections 4B and 12.


---

# ADR-0027: Treat `spec_sanity` tests as executable methodology invariants

- **Status:** Accepted — governance decision
- **Date:** 2026-08-28
- **Scope:** Testing / methodology protection

## Context

The final spec contains invariants that are easy to violate accidentally, especially when code is written by multiple contributors or AI assistants. Markdown alone does not prevent regression.

## Decision

Create `tests/spec_sanity/` as a methodology firewall. These tests SHALL encode invariants that must remain true regardless of implementation refactoring.

The suite is distinct from ordinary unit/performance tests: failure means the implementation contradicts the frozen methodology.

## Rationale

Executable invariants make the design enforceable.

## Consequences

**Positive:** prevents silent methodological drift.

**Trade-offs:** tests must be maintained when the frozen spec intentionally changes.

## Alternatives considered

1. Rely only on code review/docs — rejected.
2. Put all checks in generic unit tests with no semantic grouping — rejected because methodology regressions become hard to recognize.

## Implementation implications

Minimum suite should include:
- SYSTEM_FACT not audit-eligible.
- BEHAVIORAL not validation-eligible.
- synthetic source not real-validation eligible.
- derivation-group dedup.
- descriptor/rule annotation not pair players.
- UNAVAILABLE != NEUTRAL.
- unavailable member not mislabeled WEAK.
- WEAK requires >=2 computable role groups.
- H_domain not clique-projected but may propose cut.
- visualization pruning does not change audit.
- multimodal midpoint temporal score low.
- directed delay not reversed.
- history lift<=1 gives zero positive.
- target snapshot not used to bootstrap its own history.
- small-chain over-merge is SKIPPED.
- CONFIG_DRIFT != DATA_DRIFT.
- attribution players are groups.
- large-chain attribution avoids C(n,2) materialization.
- external evidence with `chaining_usage=UNKNOWN` cannot validate.
- external evidence with `chaining_usage=CONFIRMED_USED` cannot validate.
- raw NocPro score/veto never enters normalized `s_k`.
- system `TimeWindow/HistorySimilarity/TopologySimilarity` remain distinct from module `T/H/Dep`.
- missing M_pair defaults to UNKNOWN/UNAVAILABLE, not NEUTRAL.
- unmapped alarm→topology gives `Dep_*=⊥`.
- undirected adjacency does not enable SHARED_ACTIVE_PATH/dominator.
- golden chain 2214039 may generate a two-block candidate but is not hard-coded as over-merge ground truth.
- `SYNTHETIC_TEST` and `BACKFILL` cannot validate.
- `REAL_EXPORT_REPLAY` does not validate unless all later gates pass.
- `quality_status=UNKNOWN/FAIL` cannot validate.
- `chaining_usage` is resolved in source-version + chaining-config/run context; a coarse store-level flag is insufficient.
- `chaining_usage` changes do not alter Explain/Role/Audit masks.
- raw system pair score/veto belongs to `M_pair`; attribute configuration fields belong to `M_attribute_config`.
- aggregate system pair-count characteristic belongs to `M_chain_characteristic` and does not create exact pair edges.
- singleton chain never becomes WEAK because pair evidence is unavailable.
- singleton Pair WHY / connector / over-merge returns NOT_APPLICABLE, not ERROR/stable.


## Invariants / required tests

- Every frozen invariant above has an automated test.
- Failing a spec-sanity test blocks merge unless the spec/ADR is intentionally revised first.

## References

V2.3.1 section 13 plus all methodology ADRs.


---

# ADR-0028: Freeze membership Fit, three-axis roles, and WEAK vs INSUFFICIENT DATA semantics

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Member explanation / role semantics

## Context

A low scalar score is not enough to call an alarm WEAK. Missing evidence must be distinguished from evidence that is available but neutral/non-supporting. The final spec defines pair/channel Fit, group Fit, MembershipSupport and a three-axis role model.

## Decision

For channel k:

`D_k(x,C) = {y in C\{x}: availability_k(x,y)=1}`

`Fit_k(x,C) = supported_available_neighbors / |D_k|`, with `|D_k|=0 => ⊥`.

Group Fit:

`Fit_g(x,C)=max(Fit_k)` across computable channels in the derivation group.

Role-eligible groups:

`G_role(x,C) = {g: role_eligible and Fit_g != ⊥}`.

MembershipSupport is the mean Fit_g over `G_role`.

The membership role gate SHALL require:
- `AvailabilityCoverage >= c_min`,
- at least **2 distinct computable ROLE_ELIGIBLE derivation groups**,
- unavailable (`⊥`) is not silently converted to NEUTRAL.

If the gate fails => `INSUFFICIENT_DATA`.

If the gate passes:
- CORE follows the frozen absolute floor + rank/representativeness/positive contrastive margin rules.
- WEAK follows bottom-band + non-positive margin rules.
- otherwise PERIPHERAL.

Structural role and redundancy role are separate axes:
- CONNECTOR/NON_CONNECTOR.
- NEAR_DUPLICATE_CANDIDATE/UNIQUE.

## Rationale

This prevents “few data => weak” and keeps membership, structure and redundancy semantically distinct.

## Consequences

**Positive:** interpretable member WHY and correct insufficient-data handling.

**Trade-offs:** UI/API must expose vector evidence and gate reasons, not only one score.

## Alternatives considered

1. One scalar role score — rejected.
2. Treat unavailable as zero support — rejected.
3. Use system facts/history to strengthen role by default — rejected by eligibility.

## Implementation implications

Store/return enough per-group Fit to explain the scalar. For |C|<8, use the small-chain policy from the spec instead of quantile ranking.

## Invariants / required tests

- Temporal available + all other role groups unavailable => INSUFFICIENT_DATA, not WEAK.
- Two computable neutral groups may satisfy the computability gate and can support a WEAK decision if the other conditions hold.
- SYSTEM_FACT and BEHAVIORAL groups do not enter default MembershipSupport.
- Membership/Structural/Redundancy labels can change independently.

## References

V2.3.1 section 4B and evaluation section 13.


---

# ADR-0029: Freeze implementation scope: MVP/P0 first, P1-Core minimum bar is 3+1

- **Status:** Accepted — frozen by V2.3.1 scope
- **Date:** 2026-08-28
- **Scope:** Project scope / schedule

## Context

The methodology contains more features than one person should implement in one term. Treating every Accepted ADR as a mandatory feature backlog would create schedule failure and push effort into infrastructure or optional extensions.

## Decision

Implementation SHALL follow the scope hierarchy in V2.3.1.

MVP and P0-complete must form a usable project before P1.

MVP SHALL explicitly include:
- Gray-box NocPro Metadata Adapter for rule/merge/connector-extender/Attribute config/aggregate characteristics and optional exact `M_pair`; simiDict/A_ij/ΔQ are not required.
- A first-class singleton path: `|C|=1` still supports chain overview/system facts/descriptors/evolution; pair/connector/over-merge operations return NOT_APPLICABLE and singleton is not labeled WEAK merely due to unavailable pair evidence.

P1-Core minimum bar is exactly the committed 3+1:
1. CommonDependency capability engine + Specificity anti-hub + H_domain explanation; SHARED_ANCESTOR/SHARED_ACTIVE_PATH are enabled only when the corresponding topology semantics exist, otherwise `UNAVAILABLE`.
2. Multi-evidence over-merge verdict.
3. Similar Chains baseline.
4. Tier-1A Explanation Drift.

P1-optional and P2 features are stretch/data-gated and SHALL NOT block project completion.

Accepted methodology ADRs constrain how a feature is implemented **if/when the feature exists**; they do not imply that all optional features must be completed.

## Rationale

This aligns architecture governance with the explicit one-person/one-term commitment.

## Consequences

**Positive:** protects research contribution and schedule.

**Trade-offs:** some architecture hooks will exist before their optional feature is implemented.

## Alternatives considered

1. Implement all ADR-described features before demo — rejected.
2. Prioritize Kafka/UI polish over core evidence — rejected.

## Implementation implications

Backlog labels should map every issue to MVP, P0, P1-Core, P1-Optional or P2.

## Invariants / required tests

- A P0 demo does not fail because Kafka/LLM/full KEDB are absent.
- A P0/MVP demo is incomplete if it crashes/mislabels the common singleton path or if Gray-box metadata is only hard-coded rather than ingested through the adapter contract.
- P1 completion is judged against the 3+1 core bar.
- P1 is not considered incomplete merely because a dataset lacks active-path semantics; the engine must fail closed to UNAVAILABLE rather than fabricate output.
- Optional features cannot become hidden prerequisites for core endpoints.

## References

V2.3.1 section 14.


---

# ADR-0030: Use a Direct Snapshot Adapter as the accepted prototype reference path

- **Status:** Accepted — implementation sequencing decision
- **Date:** 2026-08-28
- **Scope:** Prototype transport

## Context

The research core needs a simple, deterministic way to ingest a complete snapshot before Kafka semantics are implemented. Direct JSON/file/HTTP ingestion can exercise the exact same canonical Input Contract without message-broker overhead.

## Decision

Implement a Direct Snapshot Adapter as the first supported prototype path.

It SHALL accept a complete versioned snapshot package containing the same logical records that later Kafka messages represent. It SHALL validate the Input Contract and produce the same canonical persisted/in-memory snapshot state as any future Kafka adapter.

The direct adapter is a first-class prototype path, not merely a throwaway unit-test hack.

## Rationale

This lets the team implement contracts, spec-sanity, evidence, roles and descriptors before messaging infrastructure.

## Consequences

**Positive:** very fast local iteration and deterministic fixtures.

**Trade-offs:** a later Kafka adapter must be checked for semantic equivalence.

## Alternatives considered

1. Kafka-first — rejected for implementation sequencing.
2. Direct path with a different schema — rejected because it would create two systems.

## Implementation implications

Support fixture replay modes (single snapshot / step sequence). HTTP vs file is an implementation choice; the semantic contract is identical.

## Invariants / required tests

- Same fixture via direct and Kafka paths yields identical canonical state.
- Direct adapter cannot bypass contract validation/provenance stamping.

## References

Implementation sequencing consistent with V2.3.1 snapshot model and ADR-0003.


---

# ADR-0031: Freeze Evidence Coverage Attribution as a group-level closed-form coverage allocation

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Tier-2 attribution

## Context

The final spec intentionally renamed the feature from generic Shapley language to Evidence Coverage Attribution. Channel-level players would over-credit repeated representations of the same derivation, while exact combinatorial Shapley is unnecessary and can violate latency constraints.

## Decision

Players SHALL be eligible derivation groups, not channels.

Define:

`v(S) = |{pairs p: exists g in S with b_g(p)=1}| / C(|C|,2)`.

For each group g:

`phi_g = (1/C(|C|,2)) * sum_{p supported by g} 1/g_p`

where `g_p` is the number of derivation groups supporting pair p.

This closed-form allocation is the baseline. It SHALL be named **Evidence Coverage Attribution**, not “exact Shapley”.

Default players are EXPLAIN_ELIGIBLE groups; BEHAVIORAL contribution is visually labeled; SYSTEM_FACT is excluded.

Large chains SHALL NOT materialize all C(n,2) pairs. Use inverted-index counts, sampling or supernode approximation according to the scalability guard.

## Rationale

The formula shares each covered pair equally among supporting derivation groups and is representation-invariant at the group level.

## Consequences

**Positive:** deterministic, explainable, consistent with derivation dedup.

**Trade-offs:** it measures evidence coverage contribution, not causal importance or connectivity value.

## Alternatives considered

1. Channel-level attribution — rejected.
2. Exact combinatorial Shapley — rejected as baseline.
3. Rename output “cohesion attribution” — rejected because the value function is coverage.

## Implementation implications

Evaluate with deletion curves and brute-force comparison on tiny synthetic cases where exhaustive subset computation is feasible.

## Invariants / required tests

- Duplicating channels inside one derivation group does not multiply attribution.
- Large-chain mode proves no full pair matrix was materialized.
- UI wording says “% evidence coverage”, not “causal importance/cohesion”.

## References

V2.3.1 section 8.4 and evaluation section 13.


---

# ADR-0032: Freeze dependency evidence semantics, anti-hub specificity and failure-domain role

- **Status:** Accepted — frozen by V2.3.1 P1-Core
- **Date:** 2026-08-28
- **Scope:** Topology / dependency evidence

## Context

Topology relations have different meanings. A shared ancestor is weaker than a shared active path, and a core ancestor of half the network should not create overwhelming evidence. Failure domains are also set-valued rather than ordinary pairwise channels.

## Decision

Dependency evidence SHALL preserve relation type and semantics.

`Dep_hop`: physical/logical/service distances are not mixed. Baseline score may use `1/(1+d)` with configured D_max. Alarm→resource mapping MUST succeed first; unmapped => `⊥`.

`Dep_upstream` / CommonDependency SHALL distinguish:
`SHARED_ANCESTOR < SHARED_ACTIVE_PATH < UNAVOIDABLE_DEPENDENCY`.

Capability gate:
- SHARED_ANCESTOR only when a valid directed hierarchy/dependency relation exists.
- SHARED_ACTIVE_PATH only when active-path semantics exist.
- UNAVOIDABLE_DEPENDENCY only when dominator/path semantics exist.
- Undirected device–port adjacency alone is insufficient for all three upstream/path claims.

Baseline CommonDependency:

`CD(i,j)=max_u Specificity(u)*exp(-(d(i,u)+d(j,u))/lambda_dep)`

with

`Specificity(u)=log(1+N/|Desc(u)|)/log(1+N)`,

so Specificity is bounded in [0,1] and penalizes high-degree/global ancestors.

`UNAVOIDABLE_DEPENDENCY` (dominator semantics) remains P2 unless data/topology quality supports it.

Failure domains remain `H_domain` hyperedges as defined in ADR-0011.

## Rationale

This prevents topology hubs and semantic mixing from producing misleading dependency support.

## Consequences

**Positive:** interpretable dependency evidence and better weak/over-merge analysis.

**Trade-offs:** requires topology versioning, alarm-resource mapping quality and relation-type discipline.

## Alternatives considered

1. Treat any shared ancestor as strong failure dependency — rejected.
2. Mix physical/logical/service hop distances — rejected.
3. Project failure domains into a clique — rejected.

## Implementation implications

Alarm-resource mapping must carry topology layer, method, confidence, status, source version/freshness. Mapping and capability fail closed. These fields feed subtype-specific Quality evaluation under ADR-0010; missing required mapping/freshness data yields `quality_status=UNKNOWN` for validation.

Real external topology can be validation-eligible only after source-kind + chaining-usage + quality gates. External provenance alone is not independence.

## Invariants / required tests

- Specificity is always within [0,1].
- A very broad core ancestor receives lower specificity than a narrow shared dependency.
- Shared ancestor and shared active path are distinguishable in output/provenance.
- Synthetic topology exercises the channel but cannot count as real validation.
- Unmapped alarm/resource => all affected Dep_* are UNAVAILABLE.
- Undirected adjacency cannot produce SHARED_ACTIVE_PATH/dominator.
- `chaining_usage=UNKNOWN` topology cannot validate NocPro.
- Mapping/source freshness uncertainty may allow Explain/Role/Audit according to their masks, but validation fails closed unless quality_status=PASS.

## References

V2.3.1 sections 4A, 4B, 6, 13 and 14.
