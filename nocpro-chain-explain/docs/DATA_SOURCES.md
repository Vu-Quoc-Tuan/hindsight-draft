# Data Sources and Provenance

Tài liệu này mô tả dữ liệu Hindsight biết, mức xác minh và điều tuyệt đối không
được suy ra. `nocpro-mock` sở hữu replay/normalization; `nocpro-chain-explain`
sở hữu evidence và analysis.

## Phân loại

| Loại logic | Cách dùng |
| --- | --- |
| Real live | dữ liệu production trực tiếp, cần version/provenance và quality gate |
| Real export replay | export quan sát thật được replay; không tự trở thành live validation |
| Observed fixture | lát cắt bất biến của dữ liệu/tài liệu đã quan sát |
| Derived replay | nhiều window/snapshot suy ra từ một export để thử pipeline |
| Synthetic test | scenario tạo có chủ đích; chỉ dùng correctness/acceptance |

Contract `source_kind` hiện có `REAL_LIVE`, `REAL_EXPORT_REPLAY`,
`SYNTHETIC_TEST` và `BACKFILL`. “Observed fixture” và “Derived replay” ở bảng
trên là cách tạo/diễn giải dataset, không phải enum mới. Synthetic augmentation
phải scenario-scoped và có `source_kind=SYNTHETIC_TEST`; backfill phải giữ nhãn
`BACKFILL`. Không merge synthetic labels/topology/history vào real fixture rồi
gọi là real.

## Alarm export cơ sở

Source manifest đã ghi nhận cho `alarm_data`:

```text
rows                         8,714
columns                         96
unique chaining_id           2,824
singleton chains             2,072 (73.3711%)
maximum chain size           1,072
maximum chain id           6907125
node_reference fill          98.0606%
physical text lines          26,508
```

CSV có multiline content và timestamp bẩn, gồm record năm 2098 cùng trường hợp
`end_time < start_time`. Các cột `cah.chaining_explain` và `is_root_alarm` có
trong schema nhưng không có observed non-null value ở export cơ sở; không được
tự điền bằng model hoặc LLM.

Raw `group_name` có thể dùng như observed source field khi provenance ghi rõ,
nhưng không chứng minh canonical alarm taxonomy.

## Golden chain 2214039

Observed fixture giữ các fact:

- 58 alarms trong khoảng quan sát khoảng 22 giây;
- 3 rules với merge `OR`;
- 1,653 pair dưới NocPro TimeWindow 600 giây;
- 435 pair cùng `node_reference=DEHL01`;
- 378 pair cùng `node_reference=DEHT01`;
- 153 pair cùng `alarm_name`;
- 72 historical pairs theo metadata nguồn.

Đây là Golden Gray-box/two-block fixture, không phải ground truth
`overmerge=true`. `72 historical pairs` của NocPro không tự động trở thành
`H.support`, và TimeWindow không trở thành `T_burst/T_delay`.

Executable examples và assertions được giữ ở
`nocpro-mock/docs/examples/golden_2214039/`.

## Báo cáo Attribute/Louvain

`nocpro-mock/docs/BaoCao_Attribute_Louvain_Chaining.docx` là source evidence đã
quan sát. Nó cho biết:

- Attribute type gồm Expression, Algorithm, TimeWindow, HistorySimilarity và
  TopologySimilarity;
- TimeWindow có veto raw `-999999999`;
- raw score có thể ngoài `[0,1]`, ví dụ `2.0`;
- Attribute Engine tạo pair-to-score-vector và có bounded comparison behavior;
- tài liệu không cung cấp exact Louvain internals như `A_ij`, modularity delta
  hoặc node movement.

Do đó raw system scores/veto phải được giữ nguyên và hiển thị như System Fact,
không normalize thành evidence-channel score.

## IP topology

Source manifest cơ sở của `topoIP`:

```text
relation rows                         201,977
columns                                    16
source network_class SITE_ROUTER       90.3860%
```

Nó biểu diễn device-port adjacency và có freshness field, nhưng không xác minh
routing direction, active path hoặc dependency direction. Một audit khác trên
bộ `alarmIP/topoIP` cục bộ ghi nhận exact canonical `device_code` mapping cho
140,596/212,636 alarm rows (66.121%) và 1,294/2,908 distinct device codes.
Phép đo này hỗ trợ bounded undirected `Dep_hop` trên endpoint map được; không hỗ
trợ RCA/propagation claim.

Không fuzzy/prefix-map các device code không xuất hiện trong source chỉ để tạo
topology coverage.

## IT topology

IT source relations hữu ích để dựng bounded navigation tree. Audit cục bộ được
ghi nhận:

```text
alarm rows uniquely resolved          169,836 / 258,344 (65.740%)
rows with multiple candidates          44,992
rows touching ambiguous alias             441
rows with no alias hit                  43,106
unambiguous aliases                    111,311
ambiguous aliases                          161
normalized nodes                       128,322
source-relation edges                  218,635
```

Các số này là structural/source-field joins. `DIRECTED_SOURCE_RELATIONS` không
đồng nghĩa verified dependency. Resolver phải để ambiguous alias unavailable
và trả `p2_mapping_eligible=false` cho IT cho tới khi có business semantics.

Các archive mang extension `.zip` từng được quan sát có 7z magic bytes; không
coi full schema/content đã xác minh chỉ từ tên file.

## History, taxonomy và `T_delay`

Production `H` và `T_delay` cần:

- taxonomy authority có `source_id`, `source_version` và mapping
  `TYPE/FAMILY/CATEGORY`;
- multiple snapshots có thời gian và version tin cậy;
- episode lineage chỉ dùng prefix trước training cutoff;
- đủ independent episode cho từng directed relation;
- config/model artifact có provenance và persistence.

Sequence slicer có thể tạo derived replay windows cho test H/T-delay/Evolution,
nhưng các window cùng xuất phát từ một export không phải independent production
snapshots. Synthetic temporal fixtures kiểm tra multimodal local-mass behavior
và directionality; chúng không calibration production threshold.

## Synthetic scenario policy

Synthetic data phù hợp để kiểm tra capability không có trong real source:

- directed hierarchy, active path và failure domain;
- history/temporal delay distributions;
- Evolution split/merge/recombination;
- system-pair metadata states;
- Counterfactual extra-member, over-merge, move và merge candidates;
- quality/error cases.

Mỗi scenario phải deterministic, versioned, khai báo source kind và expected
assertions. Không được dùng synthetic labels để tuyên bố model accuracy hay
operator correctness trên production.

Executable synthetic fixtures được giữ ở
`nocpro-mock/docs/examples/synthetic/` vì Docker Compose và acceptance harness
đọc trực tiếp thư mục này.

## Fail-closed checklist

- Missing pair metadata -> `UNKNOWN`, không phải `NEUTRAL`.
- Missing/ambiguous alarm-resource mapping -> `UNAVAILABLE`.
- Undirected adjacency -> không suy ra upstream/downstream.
- Display hierarchy -> không suy ra active path/dominator/failure domain.
- Missing taxonomy -> không infer family/category từ free text.
- Derived replay/synthetic -> không gắn nhãn production validation.
- Missing timestamps/equal timestamps -> không tạo directed delay giả.
- Missing calibration samples/labels -> không đặt production-calibrated.
