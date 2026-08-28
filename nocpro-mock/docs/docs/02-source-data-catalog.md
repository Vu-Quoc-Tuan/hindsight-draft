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
