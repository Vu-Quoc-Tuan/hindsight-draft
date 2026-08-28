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
