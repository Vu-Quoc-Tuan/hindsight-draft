# Real topology dataset modes and tree projection implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose accurate alarm-only, IP-adjacency, and IT-directed-source-relation data modes, with a bounded topology tree navigator that changes no Explain dependency semantics.

**Architecture:** `nocpro-mock` owns canonical profile selection and CSV normalization. It exposes bounded tree projections over normalized nodes and typed relations. React consumes the projection API; it never reads raw CSV or upgrades source relations to dependencies.

**Tech Stack:** Python stdlib CSV/HTTP server, existing nocpro-mock replay/contract code, React/TypeScript/Vite, pytest, Vitest.

## Global Constraints

- `ALARM_ONLY` = `datasets/raw/alarm/alarm_data.csv`, topology unavailable.
- `IP_NETWORK` = `alarm/alarmIP.csv` + `topo/topoIP.csv`, undirected `ADJACENT_TO`.
- `IT_SERVICES` = `alarm/alarmIT.csv` + `topo/topoIT/`, directed `SOURCE_RELATION` only.
- Never infer alarm-resource mapping, taxonomy, dependency, causal direction, or production P2 availability.
- The IT source is a directed relation graph, not assumed a DAG.
- The projection has deterministic technical primary paths, references for multi-parent nodes, and a path-local cycle guard.
- Preserve unrelated uncommitted mock/UI work.

---

### Task 1: Dataset profile catalog and IT CSV normalizer

**Files:**
- Create: `nocpro-mock/src/nocpro_mock/loaders/topology_it_csv.py`
- Create: `nocpro-mock/tests/test_topology_it_csv.py`
- Modify: `nocpro-mock/src/nocpro_mock/ui/server.py`
- Modify: `nocpro-mock/tests/test_ui.py`

**Interfaces:**
- `resolve_dataset_profile(profile_id: str) -> DatasetProfile`
- `ITTopologyLoader.iter_nodes() -> Iterator[TopologyRelationNode]`
- `ITTopologyLoader.iter_edges() -> Iterator[TopologyRelationEdge]`

- [ ] **Step 1: Add failing profile/schema tests**

```python
def test_it_profile_uses_matching_inputs() -> None:
    profile = resolve_dataset_profile("IT_SERVICES")
    assert profile.alarm_csv.endswith("datasets/raw/alarm/alarmIT.csv")
    assert profile.topology_kind == "DIRECTED_SOURCE_RELATIONS"

def test_it_loader_emits_typed_source_relations(tmp_path: Path) -> None:
    loader = ITTopologyLoader(write_minimal_topoit(tmp_path))
    assert ("SERVICE_HAS_MODULE", "SOURCE_RELATION") in {
        (edge.relation_type, edge.direction_kind) for edge in loader.iter_edges()
    }
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest nocpro-mock/tests/test_topology_it_csv.py nocpro-mock/tests/test_ui.py -q`

Expected: import failures until the profile catalog and loader exist.

- [ ] **Step 3: Implement model, strict schema validation, and loader**

```python
@dataclass(frozen=True)
class TopologyRelationEdge:
    source_id: str
    target_id: str
    relation_type: str
    direction_kind: Literal["NONE", "SOURCE_RELATION"]
    dependency_semantics: Literal["UNVERIFIED"]
    source_table: str
    source_version: str
```

Produce `SERVICE_HAS_MODULE`, `MODULE_HAS_INSTANCE`,
`MODULE_LINKS_DATABASE`, `DATABASE_LINKS_SERVICE`,
`DATABASE_LINKS_INSTANCE`, and `INSTANCE_LINKS_STORAGE` edges. Namespace IDs
as `it:<type>:<raw-id>`. Validate source headers; diagnose missing columns and
skip incomplete rows without guessing identifiers.

- [ ] **Step 4: Wire the profile selector**

```python
DATASET_PROFILES = {
    "ALARM_ONLY": DatasetProfile(..., topology_kind="UNAVAILABLE"),
    "IP_NETWORK": DatasetProfile(..., topology_kind="UNDIRECTED_ADJACENCY"),
    "IT_SERVICES": DatasetProfile(..., topology_kind="DIRECTED_SOURCE_RELATIONS"),
}
```

Use a profile as an atomic alarm/topology pair. Reject unknown profiles and
retain old explicit paths only for test/developer replay.

- [ ] **Step 5: Verify and commit**

Run: `pytest nocpro-mock/tests/test_topology_it_csv.py nocpro-mock/tests/test_ui.py -q`

Expected: PASS.

Commit:
```bash
git add nocpro-mock/src/nocpro_mock/loaders/topology_it_csv.py nocpro-mock/src/nocpro_mock/ui/server.py nocpro-mock/tests/test_topology_it_csv.py nocpro-mock/tests/test_ui.py
git commit -m "feat: add real topology dataset profiles"
```

### Task 2: Bounded topology projection API

**Files:**
- Create: `nocpro-mock/src/nocpro_mock/ui/topology_projection.py`
- Create: `nocpro-mock/tests/test_topology_projection.py`
- Modify: `nocpro-mock/src/nocpro_mock/ui/server.py`

**Interfaces:**
- `project_relation_tree(nodes, edges, *, root_id, max_depth=3, max_children=50) -> TopologyTreeProjection`
- `GET /api/topology/projection?profile_id=<id>&root_id=<id>&depth=<n>&child_limit=<n>`

- [ ] **Step 1: Add failing projector tests**

```python
def test_projection_stops_service_module_database_service_cycle() -> None:
    view = project_relation_tree(nodes, cyclic_edges, root_id="it:service:s1")
    assert view.root.children[0].children[0].cycle_reference is True

def test_projection_uses_one_primary_occurrence_and_reference_badges() -> None:
    view = project_relation_tree(nodes, multi_parent_edges, root_id="it:service:s1")
    assert view.reference_count("it:database:d1") == 1
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest nocpro-mock/tests/test_topology_projection.py -q`

Expected: import failure until the projector exists.

- [ ] **Step 3: Implement deterministic projection and API**

```python
def project_relation_tree(
    nodes: Mapping[str, TopologyRelationNode],
    edges: Iterable[TopologyRelationEdge],
    *, root_id: str, max_depth: int = 3, max_children: int = 50,
) -> TopologyTreeProjection:
```

Sort relations by display priority, target type, then target ID. Stop when the
target is in `visited_path`; emit a non-expandable cycle reference. Track the
first occurrence globally; render later parents as references, never copied
subtrees. Return explicit hidden child counts. `ALARM_ONLY` returns topology
unavailable. IP identifies adjacency projection and IT identifies source
relation projection; neither returns a dependency capability.

- [ ] **Step 4: Verify and commit**

Run: `pytest nocpro-mock/tests/test_topology_projection.py nocpro-mock/tests/test_ui.py -q`

Expected: PASS.

Commit:
```bash
git add nocpro-mock/src/nocpro_mock/ui/topology_projection.py nocpro-mock/src/nocpro_mock/ui/server.py nocpro-mock/tests/test_topology_projection.py nocpro-mock/tests/test_ui.py
git commit -m "feat: expose bounded topology tree projections"
```

### Task 3: Separate Explain topology navigator

**Files:**
- Create: `nocpro-chain-explain/services/web/src/TopologyTree.tsx`
- Create: `nocpro-chain-explain/services/web/src/TopologyTree.test.tsx`
- Modify: `nocpro-chain-explain/services/web/src/App.tsx`
- Modify: `nocpro-chain-explain/services/web/src/App.css`
- Modify: `nocpro-chain-explain/services/web/src/types.ts`

**Interfaces:**
- `TopologyTree` consumes normalized projection JSON only.
- Existing `ChainTree` remains untouched as a separate member navigation view.

- [ ] **Step 1: Add failing UI tests**

```tsx
it('labels IT as a relation-tree projection, not a dependency graph', () => {
  render(<TopologyTree projection={itProjection} />)
  expect(screen.getByText(/Relation Tree Projection/i)).toBeInTheDocument()
  expect(screen.queryByText(/upstream|root cause|propagation/i)).not.toBeInTheDocument()
})

it('renders a cycle as a reference rather than a recursive branch', () => {
  render(<TopologyTree projection={cycleProjection} />)
  expect(screen.getByText(/linked to Service S1/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Verify the test fails**

Run: `npm test -- --run src/TopologyTree.test.tsx`

Expected: missing `TopologyTree` module.

- [ ] **Step 3: Implement the compact navigator**

Build a profile/source badge and immutable semantic notice, type/search
filters, shallow expandable tree, and responsive node inspector. Reuse existing
visual tokens without replacing the uncommitted member tree. Cycle/reference
rows are inactive; inspector shows relation type, direction kind, source table,
and source version. Show unavailable distinctly from an empty topology.

- [ ] **Step 4: Integrate and verify**

Add a separate topology navigation view using a typed mock API adapter. Do not
make it a chain-tree grouping. Run:
```bash
npm test -- --run src/TopologyTree.test.tsx src/ChainTree.test.tsx
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit UI work**

```bash
git add nocpro-chain-explain/services/web/src/TopologyTree.tsx nocpro-chain-explain/services/web/src/TopologyTree.test.tsx nocpro-chain-explain/services/web/src/App.tsx nocpro-chain-explain/services/web/src/App.css nocpro-chain-explain/services/web/src/types.ts
git commit -m "feat: add bounded topology tree navigator"
```

### Task 4: Fail-closed regression, documentation, and browser proof

**Files:**
- Modify: `nocpro-mock/README.md`
- Modify: `nocpro-chain-explain/IMPLEMENTATION_STATUS.md`
- Test: `nocpro-mock/tests/test_topology_it_csv.py`
- Test: `nocpro-mock/tests/test_topology_projection.py`
- Test: `nocpro-chain-explain/services/web/src/TopologyTree.test.tsx`

- [ ] **Step 1: Add boundary regression**

```python
def test_real_it_source_relations_do_not_enable_dependency_capabilities() -> None:
    payload = projection_metadata_for("IT_SERVICES")
    assert payload["direction_kind"] == "SOURCE_RELATION"
    assert payload["dependency_semantics"] == "UNVERIFIED"
    assert payload["p2_dependency_capability"] == "UNAVAILABLE"
```

- [ ] **Step 2: Update user-facing docs/status**

Document three source modes, source-relation/adjacency semantics, bounded tree
projection, exact mapping boundary, and P2 availability remaining unavailable.

- [ ] **Step 3: Run focused verification**

```bash
pytest nocpro-mock/tests/test_topology_ip_csv.py nocpro-mock/tests/test_topology_it_csv.py nocpro-mock/tests/test_topology_projection.py nocpro-mock/tests/test_ui.py -q
cd nocpro-chain-explain/services/web && npm test -- --run src/TopologyTree.test.tsx src/ChainTree.test.tsx && npm run build
git diff --check -- nocpro-mock nocpro-chain-explain/services/web nocpro-chain-explain/IMPLEMENTATION_STATUS.md
```

Expected: relevant Python/frontend tests and scoped whitespace check PASS.

- [ ] **Step 4: Run browser acceptance when the stack is available**

Open IT and IP projection fixtures, inspect console, and capture the bounded
tree. Assert that IT cycles render as references and causal/dependency wording
does not appear. If no stack is running, record `NOT_RUN`, never PASS.

- [ ] **Step 5: Commit regression/docs**

```bash
git add nocpro-mock/README.md nocpro-chain-explain/IMPLEMENTATION_STATUS.md nocpro-mock/tests/test_topology_it_csv.py nocpro-mock/tests/test_topology_projection.py nocpro-chain-explain/services/web/src/TopologyTree.test.tsx
git commit -m "test: preserve real topology relation boundaries"
```

## Plan self-review

Tasks 1–2 cover profiles, strict loader schema, normalized graph, bounded/cycle-safe projection, and unavailable states. Task 3 covers a separate operator UI without replacing the member tree. Task 4 locks the fail-closed P2 boundary and tests/docs it. All public labels use `SOURCE_RELATION` or `ADJACENT_TO`; no task creates dependency semantics or fuzzy mappings.
