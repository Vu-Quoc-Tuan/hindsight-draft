# Version Synthetic Topology Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry an explicit topology source ID/version independently from generator provenance through mock scenarios, canonical serialization, Explain capabilities, API output and synthetic Kafka acceptance.

**Architecture:** Mock scenario parsing owns the strict conditional requirement and stamps every topology-derived record. The canonical transport remains structurally backward-compatible, while Explain performs a second capability-level source-identity gate and returns `TOPOLOGY_SOURCE_VERSION_MISSING` without discarding unrelated snapshot data. Existing Kafka chunk/barrier transport is unchanged because it transports canonical bytes.

**Tech Stack:** Python 3.12 dataclasses, PyYAML, pytest, FastAPI/Pydantic, PostgreSQL/Kafka Docker acceptance, React TypeScript projection.

## Global Constraints

- `generator_version` MUST NOT be used as `topology_source.source_version`.
- `topology_source` is required iff a scenario contains `topology`, `paths`, `failure_domain` or `failure_domains`.
- Missing/blank/non-string mock topology identity fails before publication.
- A foreign package missing topology source version keeps the snapshot usable and disables only affected topology-derived capabilities.
- Stable unavailable reason: `TOPOLOGY_SOURCE_VERSION_MISSING`.
- Synthetic output is implementation evidence, never production validation.
- Do not change Kafka envelope/chunk/barrier semantics or normalized audit/membership/validation.

---

### Task 1: Canonical topology record version fields

**Files:**
- Modify: `contracts/v1/models.py`
- Modify: `contracts/v1/validation.py`
- Modify: `tests/test_contract_parsing.py`
- Modify: `../nocpro-mock/tests/test_layer5_contract.py`

**Interfaces:**
- Produces: optional `source_version: str | None` on `ActivePath` and `FailureDomain`.
- Preserves: canonical package acceptance when a non-mock producer omits the version.

- [ ] Add failing serialization round-trip tests asserting `ActivePath` and `FailureDomain` retain `source_version` independently from `generation.generator_version`.
- [ ] Run the focused contract tests and confirm the constructors reject the new arguments.
- [ ] Add the optional fields beside `source_id`/`source_kind`; do not add a package-wide validation error for absence.
- [ ] Run both Explain and mock contract tests and commit.

```bash
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests/test_contract_parsing.py ../nocpro-mock/tests/test_layer5_contract.py -q
git commit -m "feat: carry topology source versions in canonical records"
```

### Task 2: Strict scenario topology-source metadata

**Files:**
- Modify: `../nocpro-mock/src/nocpro_mock/scenarios/schema.py`
- Modify: `../nocpro-mock/src/nocpro_mock/scenarios/topology_generators.py`
- Modify: `../nocpro-mock/docs/examples/synthetic/scenario_dependency_hierarchy.yaml`
- Modify: `../nocpro-mock/docs/examples/synthetic/scenario_active_path.yaml`
- Modify: `../nocpro-mock/docs/examples/synthetic/scenario_failure_domain.yaml`
- Modify: `../nocpro-mock/tests/test_layer4_scenarios.py`

**Interfaces:**
- Produces: `TopologySourceDefinition(source_id: str, source_version: str)` and `ScenarioDefinition.topology_source`.
- Consumes: the same metadata in all topology-derived generators.

- [ ] Add failing tests for: same generator/different source versions; different generator/same source version; topology present/missing version; paths present/missing metadata; no topology-derived block/no metadata.
- [ ] Confirm parsing fails only for topology-derived scenarios missing an exact non-blank string identity.
- [ ] Parse the shared `topology_source` block without coercing values with `str()` and expose it as an immutable typed property.
- [ ] Stamp topology nodes, edges, active paths and failure domains with the exact declared `source_id` and `source_version`; leave `GenerationMetadata.generator_version` untouched.
- [ ] Update the three shipped topology-derived YAML fixtures with distinct explicit versions.
- [ ] Run mock scenario tests and commit.

```bash
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests/test_layer4_scenarios.py -q
git commit -m "feat: require versioned synthetic topology sources"
```

### Task 3: Mock package manifest and transport preservation

**Files:**
- Modify: `../nocpro-mock/src/nocpro_mock/scenarios/snapshot_builder.py`
- Modify: `../nocpro-mock/tests/test_kafka_snapshot.py`
- Modify: `../nocpro-mock/tests/test_layer5_contract.py`

**Interfaces:**
- Produces: topology `SourceRecord` with exact source ID/version plus independent manifest `generator_version`.
- Preserves: byte-equivalent HTTP/direct and Kafka canonical payload content.

- [ ] Add failing package/serialization tests asserting all four trace fields survive `package_to_dict`, JSON compression/chunking and assembly.
- [ ] Extend the synthetic package builder entry point to accept topology records and their declared source identity; add one `SourceRecord` for that topology source.
- [ ] Keep Kafka envelope and producer chunking code unchanged; prove preservation through its canonical-byte round-trip test.
- [ ] Verify same topology version with different generator versions and different topology versions with the same generator version remain distinguishable.
- [ ] Run mock contract/Kafka tests and commit.

```bash
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests/test_kafka_snapshot.py tests/test_layer5_contract.py -q
git commit -m "feat: preserve topology provenance through mock transport"
```

### Task 4: Explain capability-level topology identity gate

**Files:**
- Modify: `services/analysis-worker/tier2/topology_hypotheses/models.py`
- Modify: `services/analysis-worker/tier2/topology_hypotheses/dominator.py`
- Modify: `services/analysis-worker/tier2/topology_hypotheses/propagation.py`
- Modify: `services/analysis-worker/tier2/topology_hypotheses/analysis.py`
- Modify: `services/analysis-worker/channels/common_dependency.py`
- Modify: `services/analysis-worker/channels/dependency.py`
- Modify: `services/analysis-worker/channels/base.py` only for trace fields shared by evidence
- Modify: `tests/test_p2_dominator.py`
- Modify: `tests/test_p2_propagation.py`
- Modify: `tests/test_p2_scope_overlap.py`
- Modify: `tests/test_common_dependency.py`
- Modify: `tests/test_dependency_channel.py`

**Interfaces:**
- Produces: `TopologyHypothesisReason.TOPOLOGY_SOURCE_VERSION_MISSING` and exact source/generation provenance on results.
- Preserves: no-topology reasons, production undirected-adjacency reason precedence, and existing mapping/config/temporal gates.

- [ ] Add foreign-payload tests containing relevant topology with missing, blank, mixed or incomplete source identity. Assert snapshot parsing succeeds but affected topology outputs are unavailable with the stable reason.
- [ ] Add complete-version tests proving universes/providers isolate `(source_id, source_version, relation_type)` and never fall back to `snapshot.topology_version` or generator version.
- [ ] Add an internal source-inspection helper that classifies `ABSENT`, `MISSING_VERSION`, `INCONSISTENT` and `COMPLETE` without fabricating identity.
- [ ] Gate Tier-2 dominator first; propagation and scope must preserve independent config/witness semantics while returning the source-version reason when that is the missing topology prerequisite.
- [ ] Gate `Dep_hop`, shared ancestor and shared active path. Store `TOPOLOGY_SOURCE_VERSION_MISSING` in unavailable pair detail because pair evidence has no reason enum.
- [ ] Carry exact `source_id`, `source_version`, `scenario_id` and `generator_version` through available result models; reject mixed generation provenance for one universe.
- [ ] Run focused topology/channel tests and commit.

```bash
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests/test_p2_dominator.py tests/test_p2_propagation.py tests/test_p2_scope_overlap.py tests/test_common_dependency.py tests/test_dependency_channel.py -q
git commit -m "feat: fail closed on unversioned topology capabilities"
```

### Task 5: API and React provenance projection

**Files:**
- Modify: `services/api/nocpro_api/schemas.py`
- Modify: `services/api/nocpro_api/serializers.py`
- Modify: `services/web/src/types.ts`
- Modify: `services/web/src/TopologyHypotheses.tsx`
- Modify: `services/web/src/TopologyHypotheses.test.tsx`
- Modify: `tests/test_api.py`

**Interfaces:**
- Produces: explicit `scenario_id`, `generator_version`, `source_id`, `source_version` on pair and Tier-2 topology API views.

- [ ] Add failing API tests for available synthetic provenance and unavailable source-version reason.
- [ ] Add the four nullable fields to evidence and each Tier-2 result view; serialize them directly from immutable analysis results.
- [ ] Extend TypeScript discriminated result types and show source/version separately from scenario/generator in available cards.
- [ ] Add SSR tests ensuring generator and topology versions remain visually distinct and unavailable cards show `TOPOLOGY_SOURCE_VERSION_MISSING` without causal wording.
- [ ] Run API and web test/lint/build gates and commit.

```bash
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests/test_api.py -q
pnpm --dir services/web test
pnpm --dir services/web lint
pnpm --dir services/web build
git commit -m "feat: expose independent topology provenance"
```

### Task 6: Synthetic Kafka-to-P2 acceptance and documentation

**Files:**
- Create: `tests/e2e/test_synthetic_p2_kafka.py`
- Modify: `tests/e2e/run_acceptance.sh`
- Modify: `README.md`
- Modify: `../nocpro-mock/docs/docs/04-canonical-output-model.md`

**Interfaces:**
- Verifies: scenario → mock package → Kafka chunks/barrier → Explain PostgreSQL ingest → Tier-1A → Tier-2 available P2 output.

- [ ] Build one deterministic synthetic directed fixture with exact alarm-resource mappings, strict timestamps and complete versioned propagation/scope config.
- [ ] Publish through the existing chunk/barrier producer and wait for readiness; do not add a direct Explain file read or transport bypass.
- [ ] Assert available dominator/propagation/scope output and exact four-field provenance; add a foreign unversioned Kafka payload case that keeps Tier-1A usable and returns `TOPOLOGY_SOURCE_VERSION_MISSING` for P2.
- [ ] Run full Python/mock/web verification, Docker/Chromium acceptance and `git diff --check`.
- [ ] Document synthetic implementation evidence separately from production capability and commit.

```bash
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests -q
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest ../nocpro-mock/tests -q
pnpm --dir services/web lint
pnpm --dir services/web test
pnpm --dir services/web build
./tests/e2e/run_acceptance.sh
git diff --check
git commit -m "test: verify versioned synthetic topology end to end"
```
