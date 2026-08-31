# Integrated Synthetic Temporal Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one deterministic six-snapshot synthetic sequence that exercises exact topology mapping and all currently implemented P2 topology semantics through Kafka without changing production `topoIP` capabilities.

**Architecture:** Add a combined synthetic topology builder to `nocpro-mock`, attach its immutable topology to each ordinary snapshot package, and materialize the sequence through the existing sequence CLI. Extend the existing Docker Kafka acceptance to publish the six packages and verify logical readiness, lineage, provenance, and on-demand Tier-2 behavior.

**Tech Stack:** Python 3.11, dataclasses, PyYAML, pytest, aiokafka, FastAPI, PostgreSQL, Docker Compose.

## Global Constraints

- Production `topoIP` remains undirected `IP_ADJACENCY`; no class-name orientation is introduced.
- Synthetic identifiers use `SYN-*` and every synthetic record uses `source_kind=SYNTHETIC_TEST`.
- `generator_version=mockgen-integrated-v1` and `topology.source_version=syn-topo-temporal-v1` remain independent.
- Each sequence member is one canonical `MockSnapshotPackage`; Kafka uses existing chunk plus completion-barrier transport.
- No synthetic output is validation-eligible.

---

### Task 1: Combined Synthetic Topology Builder

**Files:**
- Modify: `nocpro-mock/src/nocpro_mock/scenarios/topology_generators.py`
- Modify: `nocpro-mock/src/nocpro_mock/scenarios/__init__.py`
- Test: `nocpro-mock/tests/test_layer4_scenarios.py`

**Interfaces:**
- Consumes: `ScenarioDefinition`, `generator_version: str`, and `alarm_resource_ids: tuple[str, ...]`.
- Produces: `generate_integrated_topology(...) -> Topology` with deduplicated nodes, directed edges, explicit paths, hyperedges, and exact mappings.

- [ ] **Step 1: Write the failing combined-topology test**

```python
def test_integrated_topology_keeps_capabilities_and_exact_mapping(integrated):
    topology = generate_integrated_topology(
        integrated,
        generator_version="mockgen-integrated-v1",
        alarm_resource_ids=("SYN-DEVICE-01", "SYN-DEVICE-02"),
    )
    assert topology.edges and topology.active_paths and topology.failure_domains
    assert all(mapping.mapping_status is MappingStatus.EXACT for mapping in topology.mappings)
```

- [ ] **Step 2: Run test and verify the missing interface fails**

Run: `pytest tests/test_layer4_scenarios.py -q`
Expected: FAIL because `generate_integrated_topology` is not defined.

- [ ] **Step 3: Implement the builder**

Use the three existing generators, deduplicate nodes by `resource_id`, require every mapped alarm resource to exist in the generated nodes, and create `AlarmResourceMapping` records with `EXACT_IDENTITY`, confidence `1.0`, synthetic topology layer, and the declared topology source version.

- [ ] **Step 4: Run the focused tests**

Run: `pytest tests/test_layer4_scenarios.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nocpro-mock/src/nocpro_mock/scenarios nocpro-mock/tests/test_layer4_scenarios.py
git commit -m "feat: compose synthetic topology capabilities"
```

### Task 2: Six-Snapshot Integrated Fixture

**Files:**
- Create: `nocpro-mock/docs/examples/synthetic/temporal_topology/scenario.yaml`
- Create: `nocpro-mock/docs/examples/synthetic/temporal_topology/sequence.yaml`
- Create: `nocpro-mock/docs/examples/synthetic/temporal_topology/expected_assertions.yaml`
- Modify: `nocpro-mock/src/nocpro_mock/scenarios/sequence_fixtures.py`
- Modify: `nocpro-mock/src/nocpro_mock/cli.py`
- Test: `nocpro-mock/tests/test_layer4_sequences.py`

**Interfaces:**
- Consumes: `generate_integrated_topology`, `build_synthetic_snapshot`, and the existing sequence manifest format.
- Produces: six deterministic snapshot JSON files whose declared transitions are `CONTINUE`, `GROW`, `SPLIT`, `MERGE`, `SHRINK`.

- [ ] **Step 1: Write fixture contract tests**

```python
def test_temporal_topology_manifest_covers_required_events():
    manifest = load_sequence_manifest(TEMPORAL_TOPOLOGY_DIR / "sequence.yaml")
    assert [item.expected_event.value for item in manifest.expected_transitions] == [
        "CONTINUE", "GROW", "SPLIT", "MERGE", "SHRINK"
    ]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pytest tests/test_layer4_sequences.py -q`
Expected: FAIL because the integrated fixture is absent.

- [ ] **Step 3: Add the fixture and topology-aware materialization**

Define memberships as 2 members, 2 members, 4 members, two 2-member chains, one 4-member chain, then one 3-member chain. Load the scenario once, build the same versioned topology for every package, and attach exact mappings for every alarm present in that package.

- [ ] **Step 4: Materialize and validate all sequence packages**

Run: `python -m nocpro_mock.cli build-sequences`
Expected: reports six files for `synthetic_temporal_topology_v1` and all packages pass canonical validation.

- [ ] **Step 5: Run sequence and Kafka wire tests**

Run: `pytest tests/test_layer4_sequences.py tests/test_kafka_snapshot.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nocpro-mock/docs/examples/synthetic/temporal_topology nocpro-mock/src/nocpro_mock nocpro-mock/tests
git commit -m "feat: add integrated synthetic topology sequence"
```

### Task 3: Kafka/PostgreSQL/API Acceptance

**Files:**
- Modify: `nocpro-chain-explain/tests/e2e/test_synthetic_p2_kafka.py`

**Interfaces:**
- Consumes: the six materialized packages and existing Kafka publisher.
- Produces: Docker acceptance evidence for logical READY order, active-snapshot promotion, synthetic provenance, and on-demand Tier-2 availability.

- [ ] **Step 1: Add an integrated-sequence E2E test**

Publish each package through `publish_snapshot`, await `COMPLETE` plus Tier-1A/lineage/similarity `READY`, verify the latest logical READY snapshot is active, then open its chain and submit a deep-dive job.

- [ ] **Step 2: Assert provenance and capability separation**

Require `scenario_id=synthetic_temporal_topology_v1`, `generator_version=mockgen-integrated-v1`, `source_id=synthetic-topology`, `source_version=syn-topo-temporal-v1`, and confirm all topology hypotheses remain labeled synthetic and are not validation-eligible.

- [ ] **Step 3: Run focused non-Docker tests**

Run: `pytest tests/test_p2_dominator.py tests/test_p2_propagation.py tests/test_p2_scope_overlap.py tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 4: Run Docker acceptance**

Run: `NOCPRO_RUN_DOCKER_E2E=1 pytest tests/e2e/test_synthetic_p2_kafka.py -q`
Expected: PASS with Kafka, PostgreSQL, API, and analysis worker running.

- [ ] **Step 5: Commit**

```bash
git add nocpro-chain-explain/tests/e2e/test_synthetic_p2_kafka.py
git commit -m "test: accept integrated synthetic topology over kafka"
```
