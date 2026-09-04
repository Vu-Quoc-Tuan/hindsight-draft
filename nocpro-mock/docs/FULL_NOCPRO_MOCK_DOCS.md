# nocpro-mock — Full Documentation Pack

# nocpro-mock — Upstream Replay, Normalization & Scenario Simulator

`nocpro-mock` là upstream simulator dành cho `nocpro-chain-explain`.

Nó **không** implement WHY / Fit / Role / Audit / Evolution của hệ Explain và **không** cố clone đầy đủ NocPro/Louvain. Mục tiêu là biến các export/tài liệu hiện có thành input có kiểm soát, deterministic và đúng provenance cho hệ downstream.

## Vai trò chính

```text
REAL EXPORTS / OBSERVED FIXTURES / SYNTHETIC SCENARIOS
                       │
                       ▼
                 nocpro-mock
        ┌──────────────┼───────────────┐
        │ replay       │ normalize     │ scenario injection
        └──────────────┴───────────────┘
                       │
          versioned Input Contract
                       │
                       ▼
             nocpro-chain-explain
```

`nocpro-mock` phải ưu tiên theo thứ tự:

1. **Replay dữ liệu đã quan sát thật**.
2. **Normalize mà không làm mất raw value**.
3. **Giữ Golden fixture bất biến**.
4. **Chỉ synthetic/mock phần thiếu trong scenario riêng**, có `source_kind=SYNTHETIC_TEST`.
5. **Fail closed** khi mapping/semantics không đủ.

## Nguồn hiện đã xác minh

- `alarm_data(1).csv`
  - 8,714 records
  - 96 columns
  - 2,824 `chaining_id`
  - median chain size = 1
  - 2,072 singleton chains ≈ 73.37%
  - max observed chain size = 1,072 (`chaining_id=6907125`)
  - `node_reference` non-null ≈ 98.06%
  - 26,508 physical text lines → CSV có multiline content
  - có dirty timestamps, gồm 2 start-time records năm 2098 và nhiều trường hợp `end_time < start_time`
  - có columns `cah.chaining_explain`, `is_root_alarm`, nhưng export hiện tại không có non-null values ở hai cột này

- `topoIP-8zjkidh613ffzdck7jca5j6bdc.csv`
  - 201,977 relation rows
  - 16 columns
  - ~90.39% source-side `network_class_name = SITE_ROUTER`
  - dạng device-port ↔ device-port
  - có `update_time_vipa` để đo freshness
  - không có `DEHL01`, `DEHT01`, `HLC9102DEA01`, `HHT9603DEA01`
  - không có field xác nhận routing direction / active path / dependency direction

- `BaoCao_Attribute_Louvain_Chaining.docx`
  - NocPro có Attribute types Expression / Algorithm / TimeWindow / HistorySimilarity / TopologySimilarity
  - TimeWindow có veto `-999999999`
  - raw system scores có thể ngoài [0,1], ví dụ 2.0
  - Attribute Engine tạo `simiDict` pair → score vector
  - có TimeWindow early-break và `maxComparePerAlarm=1000`
  - tài liệu không cung cấp exact `A_ij`, ΔQ, node movement

- Golden case `2214039`
  - 58 alarms, 22s
  - 3 rules, merge OR
  - 1653 pair `<600s`
  - 435 pair `node_reference=DEHL01`
  - 378 pair `node_reference=DEHT01`
  - 153 pair same `alarm_name`
  - 72 historical pairs
  - dùng làm **Golden Gray-box / two-block fixture**, không dùng làm ground-truth `overmerge=true`

- `topoIT-*.zip` và `alarm-*.zip`
  - magic bytes là 7z dù extension `.zip`
  - chưa coi full archive schema/content là verified trong bộ docs này
  - hình topology IT quan sát được cho thấy service/application/server/device nhiều tầng, nhưng **không đủ bằng chứng để freeze directed SERVICE dependency**

## Bắt đầu implementation

Đọc theo thứ tự:

1. `IMPLEMENTATION_BRIEF_FOR_AI.md`
2. `docs/01-boundary-and-responsibilities.md`
3. `docs/02-source-data-catalog.md`
4. `docs/03-data-classification-and-provenance.md`
5. `docs/04-canonical-output-model.md`
6. `docs/07-synthetic-augmentation-policy.md`
7. `docs/11-golden-chain-2214039.md`
8. `docs/13-testing.md`

## Không được làm

- Không import code nội bộ của `nocpro-chain-explain`.
- Không normalize raw NocPro score `2.0` hay veto `-999999999` thành `s_k`.
- Không lấy `72 historical pairs` của NocPro làm `H.support`.
- Không coi NocPro TimeWindow là `T_burst` / `T_delay`.
- Không coi NocPro TopologySimilarity là `Dep_hop`.
- Không prefix/fuzzy-map `DEHL01`/`DEHT01` sang topoIP cho có topology.
- Không suy `SHARED_ACTIVE_PATH` từ undirected adjacency.
- Không gắn synthetic data thành real validation.
- Không tự fill `cah.chaining_explain` / `is_root_alarm` bằng LLM.
- Không biến missing system pair metadata thành NEUTRAL.


---

# Implementation Brief for AI / Developer

## Mục tiêu

Implement `nocpro-mock` như một **replayer + normalizer + scenario injector** đứng upstream của `nocpro-chain-explain`.

Không implement thuật toán Explanation. Không cố clone toàn bộ Louvain.

## Repo boundary

```text
workspace/
├── nocpro-mock/
└── nocpro-chain-explain/
```

`nocpro-mock` chỉ giao tiếp với Explain qua **versioned external contract**. Không `import nocpro_chain_explain.*` để dùng business logic.

Canonical contract thuộc `nocpro-chain-explain/contracts/v1`; mock validate output against contract đó.

## Recommended code tree

```text
nocpro-mock/
├── src/nocpro_mock/
│   ├── loaders/
│   │   ├── alarm_csv.py
│   │   ├── topology_ip_csv.py
│   │   └── fixture_loader.py
│   ├── normalize/
│   │   ├── alarms.py
│   │   ├── topology.py
│   │   └── system_metadata.py
│   ├── replay/
│   │   ├── snapshot.py
│   │   ├── step.py
│   │   ├── fast.py
│   │   └── realtime.py
│   ├── scenarios/
│   │   ├── generator.py
│   │   ├── topology.py
│   │   ├── history.py
│   │   └── context.py
│   ├── producer/
│   │   ├── direct_snapshot.py
│   │   └── kafka.py          # optional/later
│   ├── validation/
│   │   ├── contract.py
│   │   ├── provenance.py
│   │   └── quality.py
│   └── cli.py
├── datasets/
│   ├── raw/
│   ├── golden/
│   ├── synthetic/
│   └── generated/
└── tests/
```

## Thứ tự implement bắt buộc

### Phase 1 — Real replay

1. Parser chuẩn cho `alarm_data(1).csv` (quoted multiline CSV).
2. Parser `topoIP`.
3. Raw → canonical transformation.
4. Direct Snapshot output.
5. Golden fixture `2214039`.
6. Contract validation + deterministic seed.

### Phase 2 — Synthetic augmentation cần thiết

Chỉ thêm synthetic scenario cho capability mà real data hiện không đủ:

- directed dependency hierarchy,
- active-path semantics,
- failure-domain membership,
- maintenance/ticket/fault-injection context,
- controlled history with known lift/support,
- split/merge/recombination snapshot sequences,
- complete system pair status / raw Attribute scores for adapter tests.

**Không sửa real/golden data để nhét synthetic topology vào.**
Mỗi augmentation là scenario riêng hoặc derived clone có provenance rõ.

### Phase 3 — Optional integration

- Kafka producer after Direct Snapshot path works.
- Large archive extraction/profile after proper 7z handling.
- Optional partial Attribute emulator only if needed for upstream behavior tests.

## Mock topology — được phép mock gì?

### A. Real topoIP replay

Dùng đúng 201,977 rows như adjacency graph theo relation type phù hợp.

Không infer:
- upstream,
- routing path,
- active path,
- dominator,
- service dependency direction.

### B. Synthetic hierarchy scenario

Để test `SHARED_ANCESTOR`:

```text
SYN-CORE-01
├── SYN-AGG-HN-01
│   ├── SYN-DEA-HN-01
│   └── SYN-DEA-HN-02
└── SYN-AGG-HCM-01
    ├── SYN-DEA-HCM-01
    └── SYN-DEA-HCM-02
```

Edges phải có:

```text
relation_type = LOGICAL_DEPENDENCY
directed = true
source_kind = SYNTHETIC_TEST
scenario_id = ...
generation_rule = ...
```

Không dùng tên `DEHL01`/`DEHT01` để giả đây là real topology.

### C. Synthetic active-path scenario

Để test `SHARED_ACTIVE_PATH`, tạo path cụ thể:

```text
AlarmResource A -> R1 -> R2 -> CORE-X
AlarmResource B -> R3 -> R2 -> CORE-X
```

Phải lưu active path explicitly. Không derive từ adjacency.

### D. Failure-domain scenario

Tạo set/hyperedge:

```text
SRLG-SYN-001 -> {resource_A, resource_B, resource_C}
POWER-SYN-01 -> {...}
```

Không clique-project thành pair edges.

### E. SERVICE topology

Chỉ freeze real SERVICE semantics sau khi extract/verify topoIT schema.

Trước đó:
- ảnh topology IT chỉ là visual evidence rằng có multi-layer graph,
- synthetic SERVICE scenario được phép dùng để test contract,
- mọi synthetic service edge phải ghi `SYNTHETIC_TEST`.

## Golden 2214039

Golden case phải giữ nguyên observed facts.

Không thêm real-looking topology cho case này.

Current topoIP không map được `DEHL01`/`DEHT01`, vì vậy real-replay Golden expected:

```text
mapping_status = UNMAPPED
Dep_* downstream = UNAVAILABLE
```

Nếu cần test dependency trên shape tương tự 2214039, tạo **clone scenario**:

```text
scenario_id = synthetic_2214039_dependency_variant
base_fixture = golden_2214039
mutations = [replace resources with SYN-* resources, attach synthetic topology]
source_kind = SYNTHETIC_TEST
```

Không sửa `golden_2214039`.

## NocPro metadata

Observed:
- rules / connector-extender counts / merge / aggregate characteristics → SYSTEM_FACT replay.
- raw pair scores chỉ emit nếu thực sự có source hoặc synthetic scenario.

Do not generate fake exact `simiDict` for 2214039.

## Determinism

Mọi synthetic generator nhận:

```text
dataset_id
scenario_id
seed
config_version
```

Cùng input + seed => cùng output byte-equivalent sau canonical sorting nếu khả thi.

## Fail-closed rules

- Unmapped resource => no topology evidence.
- Unknown edge semantics => no upstream/active-path claim.
- Missing pair system metadata => UNKNOWN.
- Missing quality => quality_status UNKNOWN.
- Synthetic/backfill => never real validation.
- Unknown chaining usage => never independent validation.

## Definition of done

Mock MVP hoàn thành khi:

1. Real alarm CSV parse đúng 8,714 records.
2. topoIP parse đúng 201,977 rows.
3. Golden 2214039 replay được System Facts/characteristics.
4. Direct Snapshot passes contract validation.
5. Singleton path replay được.
6. Dirty data được flag, không silently sửa.
7. Synthetic dependency/failure-domain/history/context scenarios chạy deterministic.
8. No test turns synthetic evidence into real validation.


---

# Design Principles

1. **Replay before emulation.** Có output NocPro quan sát thật thì replay, không tính lại để “trông giống”.
2. **Raw preserved, canonical added.** Normalize không được phá raw source.
3. **Real before synthetic.** Synthetic chỉ lấp capability/test gap.
4. **Golden fixtures immutable.** Scenario synthetic phải clone/mutate có nhãn, không sửa Golden.
5. **Fail closed.** Thiếu mapping/semantics/quality ⇒ UNKNOWN / UNAVAILABLE, không đoán.
6. **System Fact ≠ Explain Evidence.** Mock không được biến NocPro score/config thành normalized evidence của downstream.
7. **Transport-neutral.** Direct Snapshot trước; Kafka chỉ adapter.
8. **Deterministic.** Scenario synthetic có seed/config/generation rule.
9. **No circular validation.** Synthetic/backfill/unknown-usage không được masquerade as independent validation.
10. **No fake model internals.** Không tạo `A_ij`, ΔQ, node movement nếu source không có.


---

# Boundary & Responsibilities

## Upstream role

`nocpro-mock` mô phỏng **interface** của upstream systems, không mô phỏng toàn bộ implementation.

Nó có thể đại diện cho:

```text
NocPro chaining output
Inventory / topology
Operational context
Historical replay
Scenario controller
```

## Input/output boundary

```text
raw exports
observed fixtures
scenario definitions
      │
      ▼
 nocpro-mock
      │
      ├── validate
      ├── normalize
      ├── replay
      └── inject explicitly-synthetic scenario data
      │
      ▼
versioned Input Contract
      │
      ▼
nocpro-chain-explain
```

## Mock owns

- file loaders,
- canonicalization,
- raw-source retention,
- snapshot packaging,
- replay clock,
- scenario generation,
- synthetic source stamping,
- output contract validation.

## Mock does NOT own

- `T_burst`, `T_delay`, `E_*`, `Dep_*`, `H`, `S`,
- derivation groups,
- Fit / MembershipSupport,
- role classification,
- descriptor mining,
- audit conductance,
- lineage reasoning inside Explain,
- Similar Chains,
- Evidence Coverage Attribution,
- validation verdict.

## Repository dependency

`nocpro-mock` SHALL NOT import Explain business logic.

Allowed coupling:
- versioned JSON schema / contract artifact,
- documented enum values,
- integration test fixture exchange.

Forbidden coupling:
- calling Explain engines to create mock source data,
- using Explain result to decide what upstream “should have said”.


---

# Source Data Catalog

## S1 — Alarm export

File: `alarm_data(1).csv`

Verified profile:

| Item | Value |
|---|---:|
| Records | 8,714 |
| Columns | 96 |
| Unique `chaining_id` | 2,824 |
| Median chain size | 1 |
| Singleton chains | 2,072 (73.37%) |
| Largest observed chain | 1,072 (`6907125`) |
| Unique `device_code` | 309 |
| `node_reference` non-null | 98.06% |
| Physical text lines | 26,508 |
| `cah.chaining_explain` non-null | 0 |
| `is_root_alarm` non-null | 0 |

Important fields include:

```text
chaining_id / chaining_name
cah.id
alarm_name
severity_*
cah.start_time / end_time
content / addition_info
kedb_code
device_*
network_*
location_*
remote_node
node_reference
service_description
group_alarm_name
...
```

Data-quality observations:
- multiline CSV content exists,
- 2 `cah.start_time` values parse to year 2098,
- multiple rows have `end_time < start_time`.

### Policy

- Parse with a real CSV parser supporting quoted multiline fields.
- Preserve raw string values.
- Add canonical parsed values + quality flags.
- Do not silently repair timestamps.

## S2 — IP topology export

File: `topoIP-8zjkidh613ffzdck7jca5j6bdc.csv`

Verified:

| Item | Value |
|---|---:|
| Relations | 201,977 |
| Columns | 16 |
| SITE_ROUTER source rows | ~90.39% |

Columns:

```text
id
device_code
network_class_name
interface_port
device_code_relation
network_class_name_relation
interface_port_relation
update_time_vipa
port_type
fix_relation
using_ipphone
using_vtoffice
using_gpon_static
using_gpon_dynamic
using_nms
insert_time
```

Important negative evidence:
- no exact `DEHL01`
- no exact `DEHT01`
- no exact `HLC9102DEA01`
- no exact `HHT9603DEA01`

Prefixes `HLC9102*` / `HHT9603*` exist for other device types, which is **not** permission to fuzzy-map the DEA resources.

Semantics currently supported:
- adjacency,
- endpoint device/port,
- network class,
- freshness via `update_time_vipa`.

Not supported by current schema alone:
- routing direction,
- upstream/downstream,
- active path,
- dominator,
- fault dependency.

## S3 — Attribute/Louvain technical report

File: `BaoCao_Attribute_Louvain_Chaining.docx`

Verified semantics:
- Attribute type 1 Expression
- type 2 Algorithm
- type 3 TimeWindow
- type 4 HistorySimilarity
- type 5 TopologySimilarity
- raw scores can include `2.0`
- TimeWindow veto uses `-999999999`
- `simiDict` pair → vector
- TimeWindow early-break
- `maxComparePerAlarm=1000`

Not supplied:
- exact `A_ij`
- modularity contribution / ΔQ
- node movement
- complete executed attribute config for every observed chain

## S4 — Golden chain 2214039

Observed Gray-box fixture, stored separately from current alarm CSV.

Facts:
- 58 members
- 14:30:02 → 14:30:24
- 22s
- rules:
  - REMOTE_NODE: 34/58 connector, 6 extender
  - REFERENCE_NODE: 58/58 connector
  - DEFAULT: 18/58 connector
- merge OR
- characteristic counts: 1653, 435, 378, 153, 72, 36, 36, ...

Derived sanity checks:
- C(58,2)=1653
- C(30,2)=435
- C(28,2)=378
- C(18,2)=153
- C(9,2)=36

Derived values are assertions/inference, not silently promoted to system-provided facts.

## S5 — topoIT visual/archive

The visible graph shows multi-layer IT/service/application/server/device structure (VOFFICE, VSTORE, Elasticsearch, server groups, devices).

The supplied archive has 7z magic bytes despite `.zip` extension and has not been schema-verified in this documentation pass.

Therefore:
- keep `SERVICE topology from topoIT` as `UNVERIFIED_CAPABILITY`,
- do not freeze directed `SERVICE_DEPENDS_ON` semantics yet.

## S6 — large alarm archive

The supplied `alarm-*.zip` also has 7z magic bytes.

Use later for profile/benchmark after proper extraction. No detailed schema/count claim is frozen here.


---

# Data Classification & Provenance

Every emitted object must distinguish **origin**, **runtime use**, and **validation independence**.

## source_kind

```text
REAL_LIVE
REAL_EXPORT_REPLAY
SYNTHETIC_TEST
BACKFILL
```

Rules:
- `SYNTHETIC_TEST` never validates.
- `BACKFILL` means bootstrap/train/backfill state; it never validates.
- Historical real observations replayed as observations use `REAL_EXPORT_REPLAY`, not BACKFILL merely because they are old.
- REAL_LIVE / REAL_EXPORT_REPLAY only pass the first gate; they are not automatically independent.

## provenance_class

```text
SYSTEM_FACT
POST_HOC
BEHAVIORAL
EXTERNAL_OPERATIONAL
```

Mock primarily emits upstream facts/context; it must not reclassify downstream POST_HOC analysis.

## chaining_usage

```text
CONFIRMED_USED
CONFIRMED_NOT_USED
UNKNOWN
```

`chaining_usage` is resolved in context:

```text
source_id
source_version
chaining_config_version
executed_rule_set / attribute_set (if known)
snapshot/run context
```

Do not attach one global USED/NOT_USED flag to an entire topology store if different rules/configurations may use it differently.

Missing complete executed configuration => `UNKNOWN`.

## quality_status

```text
PASS
FAIL
UNKNOWN
```

The mock may compute source-quality inputs (freshness, mapping status, coverage), but final thresholds are config-versioned.

Missing required quality => UNKNOWN.

## System metadata types

```text
M_pair
  exact pair raw system score/veto/status

M_chain_rule
  rule / connector-extender / merge

M_chain_characteristic
  aggregate characteristic / pair_count / coverage_scope

M_attribute_config
  type / content / algorithmType / filterName / weight
```

Never put raw pair score inside `M_attribute_config`.

## system_pair_status

```text
EVALUATED
NOT_EVALUATED
UNKNOWN
```

Missing record defaults to UNKNOWN.

## coverage_scope

```text
FULL_PAIR_SPACE
BOUNDED_COMPARISON
UNKNOWN
```

Coverage scope is per characteristic/attribute export, not a blanket property of a whole chain.


---

# Canonical Output Model

The mock outputs a complete `MockSnapshotPackage` conforming to the versioned contract owned by `nocpro-chain-explain`.

## Logical package

```text
MockSnapshotPackage
├── snapshot
├── alarms[]
├── chains[]
├── memberships[]
├── system_metadata
│   ├── chain_rules[]
│   ├── chain_characteristics[]
│   ├── attribute_configs[]
│   └── pair_metadata[]
├── topology
│   ├── nodes[]
│   ├── edges[]
│   ├── failure_domains[]
│   └── mappings[]
├── operational_context[]
└── provenance_manifest
```

## Snapshot

Minimum:

```json
{
  "schema_version": "v1",
  "snapshot_id": "...",
  "snapshot_time": "...",
  "status": "COMPLETE",
  "source": "nocpro-mock",
  "source_kind": "REAL_EXPORT_REPLAY"
}
```

## Alarm

Preserve:
- raw source ID,
- raw timestamp strings,
- canonical parsed time,
- device/resource/entity fields,
- quality flags.

Example quality flags:

```text
TIMESTAMP_FUTURE_OUTLIER
END_BEFORE_START
UNPARSEABLE_TIMESTAMP
MISSING_DEVICE_CODE
MISSING_NODE_REFERENCE
```

## Topology edge

Required semantic fields:

```text
edge_id
source_resource_id
target_resource_id
relation_type
directed
source_id
source_version
source_kind
freshness
```

Do not use a generic directed edge when source only provides undirected adjacency.

## Alarm-resource mapping

```text
alarm_id
resource_id
mapping_status
mapping_method
mapping_confidence
topology_layer
source_version
```

`mapping_status`:
- EXACT
- VERIFIED_ALIAS
- UNMAPPED
- AMBIGUOUS

Fuzzy prefix match is not a default mapping method.

## Contract ownership

The actual JSON Schema lives in:

```text
nocpro-chain-explain/contracts/v1/
```

The mock may vendor a generated/read-only copy for CI, but must not create an incompatible second canonical schema.


---

# NocPro Gray-box Replay

## Fidelity levels

### Level 0 — Observed partition replay

Use observed `chaining_id` / memberships exactly as exported.

No re-clustering.

### Level 1 — Observed Gray-box metadata replay

Attach real/observed:
- rules,
- merge strategy,
- connector/extender labels/counts,
- aggregate characteristics,
- exact system pair metadata only when actually available.

This is the MVP target.

### Level 2 — Synthetic system-metadata scenarios

Create controlled `SYNTHETIC_TEST` metadata to exercise:
- raw score 2.0,
- TimeWindow veto,
- pair EVALUATED / NOT_EVALUATED / UNKNOWN,
- bounded coverage.

These are contract/scenario tests, not claims about a real chain.

### Level 3 — Partial Attribute emulator (optional)

Only if needed later.

May emulate a documented subset of Attribute behavior, but:
- must be clearly synthetic/emulated,
- must not be used to infer missing real system internals,
- must not become a dependency of Explain methodology.

## Golden 2214039 policy

Replay:
- 3 rules,
- OR merge,
- observed connector/extender counts,
- observed aggregate characteristics.

Do NOT create:
- fake exact `simiDict`,
- fake `A_ij`,
- fake ΔQ,
- fake pair score vector,
- fake connector semantics.

## `M_attribute_config`

General Attribute schema can be modeled from the technical report.

Exact executed config for 2214039 should remain UNKNOWN unless sourced.

If a synthetic scenario needs it:

```text
source_kind = SYNTHETIC_TEST
scenario_id = ...
generation_rule = ...
```


---

# Topology & Inventory Replay

## Real topoIP

Treat `topoIP` as a real exported **IP adjacency/inventory relation source**.

Supported baseline capability:

```text
ADJACENCY
PORT_ENDPOINTS
NETWORK_CLASS
FRESHNESS
```

Not supported without additional data:

```text
DIRECTED_DEPENDENCY
SHARED_ANCESTOR
ACTIVE_PATH
ROUTING_PATH
DOMINATOR
FAILURE_DOMAIN
```

## Mapping policy

1. exact device/resource identity,
2. otherwise UNMAPPED.

topoIT aliases are structural source-table joins for navigation. They are not
an authoritative alarm-to-resource mapping table and must not be promoted to
`VERIFIED_ALIAS` by the replay adapter. Exact canonical identity matches may
exist, but partial match coverage is not a complete P2 mapping prerequisite.

Never use prefix similarity as truth.

For Golden 2214039:

```text
DEHL01          -> UNMAPPED in current topoIP
DEHT01          -> UNMAPPED
HLC9102DEA01    -> UNMAPPED
HHT9603DEA01    -> UNMAPPED
```

So the real-replay mock emits mapping status, not invented topology.

## relation_type

Normalize only what source supports.

Example baseline:

```text
IP_ADJACENCY
```

Do not rename an adjacency edge to `LOGICAL_DEPENDENCY` merely because its endpoints have hierarchy-looking network classes.

## Freshness

Use `update_time_vipa` as a source-quality input.

Store:
- topology source version,
- edge update time,
- snapshot replay time,
- freshness age.

Do not hardcode PASS threshold in the mock spec; config decides.

## topoIT

Until archive schema is extracted and verified:
- preserve it as pending source,
- use the image only to motivate future multi-layer support,
- do not claim real directed SERVICE dependency.

## What to mock for missing topology capabilities

Create separate synthetic scenarios:

1. `synthetic_hierarchy`
   - directed logical dependency tree
   - enables shared-ancestor tests

2. `synthetic_active_path`
   - explicit path membership
   - enables shared-active-path tests

3. `synthetic_failure_domain`
   - SRLG/power/rack/service-instance hyperedges

4. `synthetic_service_dependency`
   - only for contract tests until topoIT semantics are verified

All use `SYN-*` resource IDs and `source_kind=SYNTHETIC_TEST`.


---

# Synthetic Augmentation Policy

Synthetic data is allowed and expected — but only as **explicit scenario augmentation**, never as silent completion of real data.

## Three dataset classes

```text
REAL EXPORT
  scale, distribution, parser, replay

GOLDEN OBSERVED FIXTURE
  integration fidelity and system metadata correctness

SYNTHETIC SCENARIO
  known ground truth / capability edge cases
```

## Golden immutability rule

Never modify a Golden fixture in place.

If a capability is missing, clone:

```text
base_fixture = golden_2214039
scenario_id = synthetic_2214039_dependency_variant
```

Then mutate with provenance.

## What SHOULD be mocked

### 1. Directed hierarchy

Needed to test CommonDependency `SHARED_ANCESTOR`.

Use synthetic resource names and explicit directed edges.

### 2. Active path

Needed to test `SHARED_ACTIVE_PATH`.

Store the path as first-class path data, not inferred shortest path.

### 3. Failure domains

Mock SRLG/power/rack/service-instance membership as hyperedges.

### 4. Operational context

Mock:
- maintenance,
- ticket,
- operator label,
- fault injection.

All synthetic. They test code paths, not real validation.

### 5. History

Mock controlled episodes with known:
- support,
- lift,
- family/type backoff,
- target snapshot exclusion.

Mark bootstrap as BACKFILL.

### 6. Evolution

Mock deterministic snapshot sequences:
- continue,
- grow,
- shrink,
- split,
- merge,
- recombination,
- chain-ID change with same membership,
- singleton → multi-member and reverse.

### 7. System pair metadata

Mock:
- score 2.0,
- veto -999999999,
- EVALUATED,
- NOT_EVALUATED,
- UNKNOWN,
- FULL_PAIR_SPACE vs BOUNDED_COMPARISON.

This tests Gray-box adapter typing.

## What SHOULD NOT be mocked into real fixtures

- missing DEA topology for chain 2214039,
- exact NocPro pair scores,
- exact Louvain edges,
- ΔQ,
- root-cause labels,
- `cah.chaining_explain`,
- active paths not present in source,
- ticket/maintenance that did not actually exist.

## Generation metadata

Every synthetic object includes:

```text
scenario_id
seed
generator_version
generation_rule
base_fixture_id (optional)
source_kind = SYNTHETIC_TEST
```

## Naming

Use obvious synthetic identifiers:

```text
SYN-CORE-01
SYN-AGG-HN-01
SYN-DEA-HN-01
SRLG-SYN-001
TICKET-SYN-001
```

Never reuse real-looking IDs to make the demo appear more realistic.


---

# History & Operational Context

## Three different histories

Do not collapse:

```text
NocPro HistorySimilarity / UI characteristic
  -> SYSTEM_FACT

Explain grouping-history H
  -> BEHAVIORAL
  -> computed downstream, not by mock as evidence score

Ticket/incident/maintenance history
  -> EXTERNAL_OPERATIONAL
```

The mock may provide raw historical snapshots/episodes, but it must not compute downstream `H.support/lift` and pretend it is source truth.

## Bootstrap split

For synthetic or replay history:

```text
history window < target snapshot
```

Target snapshot must not be inserted into backfill before it is emitted/evaluated.

## Context scenarios

Mock may generate separate scenarios:
- planned maintenance with scope,
- ticket covering a subset,
- conflicting maintenance windows,
- operator label,
- fault injection with known affected set.

Synthetic context is for testing and cannot become real operational validation.

## Source kind

- real ticket replay => REAL_EXPORT_REPLAY
- synthetic ticket => SYNTHETIC_TEST
- training/backfill state => BACKFILL


---

# Snapshot & Replay Model

## Primary unit

Mock emits **complete snapshot packages**, matching the downstream snapshot boundary.

## Replay modes

### `snapshot`

Emit one complete snapshot and stop.

### `step`

Emit next snapshot only on command.

Best for Evolution debugging.

### `fast`

Replay temporal sequence with time compression.

### `realtime`

Replay according to observed timestamps when a genuine sequence exists.

## Important restriction

A single alarm export does not automatically provide a historical sequence of NocPro partitions.

Do not fabricate “real evolution” by slicing one export and pretending each slice is an observed NocPro snapshot unless the scenario is explicitly synthetic.

## Direct Snapshot first

Prototype path:

```text
nocpro-mock
  -> canonical JSON snapshot
  -> nocpro-chain-explain Direct Snapshot Adapter
```

Kafka comes later.

## Kafka if added

Kafka must preserve the same canonical semantics.

If multiple topics are used, define snapshot completeness/barrier semantics. Never assume cross-topic ordering.


---

# Scenario & Fixture Model

## Directory classes

```text
datasets/
├── raw/
│   ├── alarms/
│   └── topology/
├── golden/
│   └── chain_2214039/
├── synthetic/
│   ├── dependency_hierarchy/
│   ├── active_path/
│   ├── failure_domain/
│   ├── weak_member/
│   ├── insufficient_data/
│   ├── split_merge/
│   ├── history/
│   └── context/
└── generated/
```

## Scenario schema

Minimum:

```yaml
scenario_id: ...
scenario_version: ...
seed: ...
base_fixture: null
mutations: []
expected_contract_assertions: []
source_kind: SYNTHETIC_TEST
```

## Required scenario set

### Contract / provenance

- raw score out of range
- TimeWindow veto
- M_pair missing => UNKNOWN
- bounded pair coverage
- synthetic source cannot validate

### Topology

- exact mapped adjacency
- unmapped alarm
- ambiguous mapping
- directed hierarchy
- explicit active path
- failure-domain hyperedge

### Membership / data availability

- singleton
- temporal-only + others unavailable
- neutral-vs-unavailable
- two computable role groups
- very large chain shape

### Evolution

- stable membership new chain ID
- grow/shrink
- split
- merge
- recombination

### Data quality

- multiline content
- future timestamp
- end before start
- missing device
- stale topology


---

# Golden Scenario — Chain 2214039

## Purpose

Primary Gray-box integration fixture.

Tests:
- raw alarm normalization,
- observed chain membership,
- rule/merge metadata replay,
- aggregate characteristic typing,
- SYSTEM_FACT vs downstream post-hoc separation,
- two-block candidate visibility,
- fail-closed topology mapping.

## Observed facts

```text
chain_id = 2214039
member_count = 58
event_span = 14:30:02 -> 14:30:24
duration = 22s
```

Rules:

```text
CORE_CHAINING_REMOTE_NODE
  connector = 34/58
  extender = 6

CORE_CHAINING_REFERENCE_NODE
  connector = 58/58

CORE_CHAINING_DEFAULT
  connector = 18/58

merge = OR
```

Characteristics:

```text
1653 pair time <600s
435 pair node_reference = DEHL01
378 pair node_reference = DEHT01
153 pair same alarm_name
72 pair historical grouping
36 pair device_code = DEHL01
36 pair device_code = DEHT01
...
```

## Derived assertions

These are **derived sanity checks**, not automatically system facts:

```text
C(58,2) = 1653
=> characteristic <600s covers full pair space

C(30,2) = 435
C(28,2) = 378
30+28 = 58
=> aggregate reference counts are consistent with two complete blocks 30/28

C(18,2) = 153
=> same-name count is consistent with a complete block of 18

C(9,2) = 36
=> each device-code count is consistent with a block of 9
```

## Expected mock output

Golden must emit:
- chain/members,
- M_chain_rule,
- M_chain_characteristic,
- exact original alarm fields available in fixture,
- source provenance.

Golden must NOT emit unless sourced:
- exact M_pair score vectors,
- simiDict,
- A_ij,
- ΔQ,
- node movement,
- semantics of connector/extender beyond source labels.

## Topology

Current topoIP has no exact mapping for the relevant Golden DEA resources.
This does not mean the whole IP export has zero exact matches: its regular
alarmIP/device_code records can partially match topology device_code by exact
identity. That partial source mapping remains distinct from a complete,
authoritative P2 alarm-to-resource mapping contract.

Expected:

```text
mapping_status = UNMAPPED
```

Do not attach a synthetic topology to the Golden fixture.

If dependency testing is required, use a synthetic clone with SYN-* resources.

## Not an over-merge ground truth

Expected downstream behavior may include:
- detect two dominant reference blocks,
- generate a reference/entity candidate cut,
- show contrastive separation.

Do not assert:

```text
overmerge = true
NocPro is wrong
```

without external ground truth.


---

# Data Quality & Fail-Closed Rules

## Alarm CSV

Required quality flags:

```text
MULTILINE_CONTENT
TIMESTAMP_FUTURE_OUTLIER
END_BEFORE_START
UNPARSEABLE_TIMESTAMP
MISSING_REQUIRED_ID
MISSING_DEVICE_CODE
MISSING_NODE_REFERENCE
```

Preserve raw and parsed values.

No silent correction.

## Topology

Required mapping/status behavior:

```text
UNMAPPED
AMBIGUOUS
EXACT
VERIFIED_ALIAS
```

Do not choose the “closest-looking” resource.

## Quality status

For validation-oriented source metadata:

```text
PASS
FAIL
UNKNOWN
```

Missing required freshness/coverage/mapping info => UNKNOWN.

Thresholds live in versioned config, not hardcoded in dataset generator.

## Missing system pair metadata

```text
missing -> UNKNOWN -> unavailable
```

Not NEUTRAL.

## Archives

Detect by magic bytes, not extension.

If file starts with 7z signature, invoke the correct extractor or mark source unavailable.

Do not claim full archive inspection if extraction failed.


---

# Testing & Expected Contracts

## Layer 1 — Parser tests

Alarm CSV:
- parses exactly 8,714 records from current export,
- supports 26,508 physical lines,
- preserves quoted multiline content.

topoIP:
- parses exactly 201,977 rows,
- keeps all 16 columns,
- parses `update_time_vipa`.

## Layer 2 — Normalization tests

- raw values preserved,
- future timestamp flagged,
- end-before-start flagged,
- no silent repair,
- missing fields become explicit null/quality flags.

## Layer 3 — Golden tests

2214039:
- member_count = 58,
- rule count = 3,
- merge = OR,
- characteristic 1653 has FULL_PAIR_SPACE sanity,
- 435/378 remain aggregate characteristics,
- no exact pair edges synthesized,
- topology mapping remains UNMAPPED.

## Layer 4 — Synthetic scenario tests

- same seed => same output,
- synthetic resources use SYN-* IDs,
- synthetic source never becomes real validation,
- directed hierarchy enables only hierarchy capability,
- active-path scenario stores explicit paths,
- H_domain stays a set/hyperedge.

## Layer 5 — Contract equivalence

Direct Snapshot and Kafka adapter (when added) must produce identical canonical state for the same scenario.

## Layer 6 — Negative tests

Must fail:
- mapping `DEHL01` to `HLC9102*` by prefix,
- treating undirected topoIP as active path,
- inserting raw score 2.0 into normalized evidence,
- using NocPro 72 historical pairs as behavioral H,
- changing Golden fixture to make an expected Explain verdict pass.


---

# Limitations & Non-goals

## Not a NocPro clone

The mock does not promise byte-for-byte or algorithm-for-algorithm reproduction of NocPro chaining.

Observed outputs are replayed where available.

## Not a Louvain internals simulator

No fake:
- `A_ij`,
- ΔQ,
- node movement,
- modularity trace.

## Not an oracle

Synthetic scenario truth is only truth for that scenario.

It is not evidence about production NocPro correctness.

## Topology limitation

Current topoIP is useful for IP adjacency/freshness tests but does not cover the Golden DEA resources and does not expose active path semantics.

## topoIT limitation

Visible multi-layer topology is promising, but full archive schema is not frozen until the 7z content is extracted and verified.

## Alarm archive limitation

Large alarm archive is not profiled in this docs release.

## Evolution limitation

One export is not automatically a real snapshot sequence.

Synthetic evolution must be clearly labeled.

## Metadata limitation

`cah.chaining_explain` and `is_root_alarm` columns exist in the current alarm schema but are empty in the verified export. Do not fabricate values.


---

# Implementation Plan

## P0 — Must work first

1. repository skeleton
2. canonical contract consumer
3. alarm CSV loader
4. topoIP loader
5. raw + canonical models
6. quality flags
7. Direct Snapshot producer
8. observed chaining_id replay
9. Golden 2214039 fixture
10. singleton replay path
11. deterministic scenario runner
12. contract/provenance tests

## P0.5 — Synthetic capabilities necessary for Explain testing

Implement scenario generators for:
- directed hierarchy,
- explicit active path,
- failure-domain hyperedges,
- operational context,
- controlled history,
- split/merge/recombination,
- system pair-status/raw-score edge cases.

These are **necessary test inputs** because current real exports do not cover all Explain capabilities.

## P1 — Integration

- step/fast/realtime replay,
- topology freshness controls,
- alias mapping table,
- optional Kafka producer,
- large archive extraction/profile.

## P2 — Only if useful

- partial Attribute emulator,
- verified topoIT SERVICE adapter,
- richer real context/ticket source adapters.

## Do not block P0 on

- Kafka,
- full NocPro Attribute reimplementation,
- Louvain internals,
- topoIT extraction,
- real active-path source.


---

# Documentation Index

- `00-design-principles.md`
- `01-boundary-and-responsibilities.md`
- `02-source-data-catalog.md`
- `03-data-classification-and-provenance.md`
- `04-canonical-output-model.md`
- `05-nocpro-graybox-replay.md`
- `06-topology-inventory-replay.md`
- `07-synthetic-augmentation-policy.md`
- `08-history-and-operational-context.md`
- `09-snapshot-and-replay-model.md`
- `10-scenarios-and-fixtures.md`
- `11-golden-chain-2214039.md`
- `12-data-quality-and-fail-closed-rules.md`
- `13-testing-and-expected-contracts.md`
- `14-limitations-and-non-goals.md`
- `15-implementation-plan.md`
- `adr/` — mock-specific decisions


---

# ADR-MOCK-0001 — Replay observed outputs before reimplementing chaining

- Status: Accepted

## Decision

Observed NocPro chain IDs/memberships and Gray-box metadata are replayed as source facts.

The mock does not recompute Louvain/Rule chaining to reproduce an observed fixture.

## Why

Reimplementation can diverge from the system and would make downstream tests depend on an invented NocPro.

## Invariant

Golden fixture output cannot change because a local emulator algorithm changed.


---

# ADR-MOCK-0002 — Preserve raw source values alongside canonical values

- Status: Accepted

## Decision

Every loader preserves raw fields and adds parsed/canonical fields plus quality flags.

No silent repair of timestamps or identifiers.

## Invariant

A dirty source row can always be reconstructed/audited from the mock output or retained raw store.


---

# ADR-MOCK-0003 — Prefer real exports before synthetic generation

- Status: Accepted

## Decision

Use real alarm/topology exports whenever they cover the required capability.

Synthetic data is only for missing capability, known-ground-truth edge cases, and contract testing.

## Invariant

A synthetic edge/context object is never presented as a real-export object.


---

# ADR-MOCK-0004 — Synthetic augmentation is scenario-scoped and never mutates Golden fixtures

- Status: Accepted

## Decision

Golden fixtures are immutable.

To test missing topology/history/context capability, create a separate scenario or clone with explicit mutation list and `source_kind=SYNTHETIC_TEST`.

## Invariant

`golden_2214039` remains unmapped to current topoIP even if a dependency-test variant exists.


---

# ADR-MOCK-0005 — Topology mapping and semantic capability fail closed

- Status: Accepted

## Decision

Exact/verified mapping is required. Unknown mapping => UNMAPPED.

Undirected adjacency enables adjacency/hop-style source representation only; it does not create upstream/active-path semantics.

## Invariant

No fuzzy prefix mapping or shortest-path inference is used to fabricate an active path.


---

# ADR-MOCK-0006 — History bootstrap precedes the target snapshot

- Status: Accepted

## Decision

Synthetic/backfill history is built only from periods before the target snapshot.

Target snapshot does not enter history before it is emitted/evaluated.

## Invariant

A scenario cannot use the target chain itself to manufacture prior-history support.


---

# ADR-MOCK-0007 — Direct Snapshot is the reference prototype output

- Status: Accepted

## Decision

Implement complete canonical snapshot output first.

Kafka is an optional transport adapter later and must preserve identical semantics.

## Invariant

Core mock tests run with no Kafka broker.
