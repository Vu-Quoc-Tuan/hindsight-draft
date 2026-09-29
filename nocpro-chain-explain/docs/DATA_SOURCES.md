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
đồng nghĩa verified dependency. Resolver phải để ambiguous alias unavailable.
Metadata IT hiện giữ `p2_eligible=false` và
`dependency_semantics=UNVERIFIED`; runtime không phát ra trường
`p2_mapping_eligible` cho kết quả resolve.

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

## Ranh giới feature pairwise đã đối chiếu ngày 2026-09-27

Đã đối chiếu pair evaluator và các consumer với danh mục field trong source.
Đây là kết luận từ code, không khẳng định mọi hệ thống upstream hay mọi field
raw chưa cấu trúc đều không có dữ liệu tương ứng:

- Evaluator có năm entity channel: `E_reference`, `E_device`, `E_card`,
  `E_site` và `E_remote`, với derivation tag riêng. Source không xác lập
  device/card/site lồng nhau trong dữ liệu vận hành, cũng không đặt
  `E_reference` vào thang chứa nhau đó. `E_remote` là một quan hệ.
  Kiểm tra field lineage trong checkout cho thấy `E_device` đọc canonical
  `device_code` (fallback về raw cùng tên), còn `E_card` đọc riêng
  `raw.component`; contract giữ `component` bên trong `raw` và không khai báo
  nó là alias của `device_code`. Không tìm thấy source dictionary trong repo
  định nghĩa quan hệ định danh giữa hai field. Mock topology mapper có fallback
  `component or port`, nhưng fallback đó không thuộc phép tính `E_card`.
  Vì vậy không được suy ra equivalence của hai field từ cùng tên hiển thị,
  mapping topology, hay một chain replay đơn lẻ.
- `Dep_hop` dùng physical adjacency vô hướng. Các provider shared-upstream
  trước đây cần directed dependency context hoặc ordered active-path records;
  chúng đã được gỡ khỏi runtime. Điều kiện dữ liệu để xem xét khôi phục được ghi
  trong [Deferred Directed Topology](DEFERRED_DIRECTED_TOPOLOGY.md).
  `ITTopologyLoader` đọc bốn bảng topoIT và chuẩn hóa thành 128,322 node cùng
  218,635 cạnh có hướng theo *source relation* (`dependency_semantics=UNVERIFIED`);
  đây là số cạnh sau khi bung một số dòng thành nhiều quan hệ, bỏ endpoint rỗng
  và khử cạnh trùng, không phải tổng số dòng CSV. Bốn bảng có tổng 139,314
  record: `service_module_server.csv` 89,350; `module_database.csv` 25,410;
  `database.csv` 6,938; `storage.csv` 17,616. Bản preset Explain `@5` chứa projection
  điều hướng hai hop quanh các resource được map: 3,814 node, 5,603 cạnh, gồm
  `SERVICE_HAS_MODULE`, `MODULE_HAS_INSTANCE`, `MODULE_LINKS_DATABASE`,
  `DATABASE_LINKS_SERVICE`, `DATABASE_LINKS_INSTANCE` và
  `INSTANCE_LINKS_STORAGE`. Mọi cạnh được giữ đúng relation type và source
  table; chúng không được đổi thành `SERVICE_DEPENDS_ON`, không đi vào `Dep_hop`
  hay được coi là causal/dependency graph. Projection chứa đủ 821 cạnh nguồn
  tiếp giáp với 74 resource được map và giữ các đường nguồn dài tối đa 4 hop
  giữa các resource đó; nó không phải toàn bộ topoIT. Snapshot `@1`–`@4` đã
  lưu không tự được viết lại; local dev đã chọn preset hiện hành `@5` ngày
  2026-09-29.
- Mapping của preset `@5` được chạy lại trên 500 alarm: 288
  `STRUCTURED_FIELD_UNIQUE`, 63 `AMBIGUOUS`, 149 `UNMAPPED`, với 74 resource
  phân biệt. `STRUCTURED_FIELD_UNIQUE` nghĩa là trường topoIT nguồn khớp duy
  nhất trong phiên bản nguồn này; đây không phải `VERIFIED_ALIAS` hay xác nhận
  mapping vận hành. Nó chỉ được dùng để tạo shared-storage context có nhãn
  `UNKNOWN`; resolver chung và `Dep_hop` vẫn từ chối trạng thái này. Explicit
  failure-domain records vẫn đòi mapping mạnh hơn.
- `alarmIT.csv` có 258,344 alarm ở 82,453 chain ID; preset `@5` vẫn là slice 500
  alarm (0.1935%), được giữ nguyên chính xác từ danh sách ID của `@3`, không
  phải toàn bộ export hay mẫu đại diện thống kê. Trong 226 chain có mặt trong
  slice, 225 đủ thành viên theo file nguồn; chain `6336451` thiếu 10 alarm ngoài
  slice. Manifest lưu rõ việc chọn bằng `alarm_ids`; chain partition không bị
  tái phân cụm.
- Ba alarm có timestamp bắt đầu ở năm 2057 và kết thúc trước bắt đầu. `@5` giữ
  nguyên raw timestamp và quality flags nhưng canonical start/end bị để trống,
  nên chúng không làm phình temporal burst hoặc chain span. Chỉ endpoint sai bị
  loại khỏi canonical time; timestamp hợp lệ khác của cùng alarm vẫn được giữ.
- `topoIT/storage.csv` có 17,616 dòng CSV; 17,412 dòng có `instance_id` và tạo
  cạnh `INSTANCE_LINKS_STORAGE` trong full normalized graph, còn 204 dòng thiếu
  `instance_id` nên loader không tạo cạnh cho chúng. Bản `@5` chứa 2,373 cạnh
  `INSTANCE_LINKS_STORAGE` trong projection hai hop; đây
  là toàn bộ các cạnh storage nằm trong vùng chiếu, không chỉ cạnh tiếp giáp
  trực tiếp với alarm resources. Có 14 storage resource giao với các mapping
  của alarm slice. Adapter bộc lộ 23 source-context memberships trên 14 chain;
  không chain nào có hai instance khác nhau cùng context, nên không có shared-
  storage Audit candidate. Hai alarm trên cùng một instance không được tính
  thành hai resource dùng chung storage. Đây là source context, không phải
  explicit failure-domain, nhãn cùng incident, dependency hay bằng chứng nhân
  quả. Các cạnh ngoài vùng hai hop quanh resource được map không thuộc
  projection.
- Raw `alarmIT.csv` có 100 cột; toàn bộ 100 cột của từng alarm được giữ trong
  `alarm.raw`. Mapping topo hiện đọc `device_code`, `node_reference`,
  `device_ip`, `component` và `port`; canonical time dùng `cah.start_time`/
  `end_time`; channel analysis chủ yếu dùng các canonical field tương ứng.
  Một số trường enrichment vẫn chỉ được giữ raw trong slice `@5`: chẳng hạn
  `device_ip_mapping` (7 dòng), `instance_primary_ip` (39), `db_id_dcim` (2),
  `db_id_iim` (1), `service_name_mapping` (7), `compute_host` (162), và
  `server_serial_mapping` (45). Chúng chưa được đưa vào mapping vì repo không
  có crosswalk xác nhận chúng cùng định danh resource topoIT; chuỗi khớp chính
  xác tự nó chưa đủ để tạo mapping.
- Trên toàn `alarmIT.csv`, `is_root_alarm` có các giá trị `1`/`2` ở 2,814 dòng;
  cả 500 alarm của slice `@5` đều để trống field này. `cah.chaining_explain` và
  `is_root_alarm_staging` trống toàn export. Giá trị `1`/`2` của cờ root chưa có
  codebook trong repo nên vẫn là raw source fact, không được dùng như nhãn
  ground truth cho CORE/root cause. `parent_id`/`child_id` có một số giá trị
  ngoài placeholder ở toàn export, nhưng slice `@5` chỉ có 2/1 dòng như vậy;
  danh sách của alarm `2010140605` trong chain `6336416` tham chiếu parent
  `2010140606` ở chain `6336417`. Đây là liên kết raw bắc qua chain, nhưng chưa
  có contract/codebook/valid-time để biến nó thành cạnh incident.
- `H` chỉ được thêm trong Pair WHY tường minh. `H_domain` là membership theo
  explicit failure-domain records dùng cho context/candidate generation, không
  phải pair evidence `H`. Capability hoặc fixture failure-domain synthetic
  không chứng minh đã có nguồn Shared Risk Group vận hành được ánh xạ.
- `K_pair` chưa có producer counter-evidence phủ định đang hoạt động. Gray-box
  có thể giữ `M_pair.system_semantic=VETO` như System Fact upstream và trình bày
  riêng; `SYSTEM_FACT` không góp trọng số `G*_audit`. Tier-2 nhận boolean tùy
  chọn `cross_block_negative_evidence`, mặc định `false`, nhưng repository đã
  kiểm tra không có producer nội bộ suy ra nó từ pair evidence. Counterfactual
  Review có đường nhận external-validation contradiction đã qua eligibility
  gate; đó không phải pair channel hay producer cho Audit hook.
- Input Contract v1 có `operational_context` records gồm context ID/type,
  affected resources, thời gian và provenance; Mock generator tạo chúng cho
  synthetic scenarios. Ba real replay preset đã kiểm tra
  (`real_alarm_ip_demo`, `real_alarm_it_demo`, `real_alarm_20260907_demo`) đều có
  0 record ở field này. Pair evaluator hiện không tiêu thụ records đó để ghép
  alarm theo change ticket, maintenance window hay deployment event.
  `MAINTENANCE` là provenance subtype; riêng nó không liên kết hai alarm với
  cùng một event.
- Severity và alarm type là descriptor predicates. Descriptor có thể ảnh hưởng
  representativeness và Audit candidate generation, nhưng không có pairwise
  severity/type compatibility channel riêng và chúng không thuộc `S`.

Các gap pairwise trên được kết luận từ evaluator và consumer path đã kiểm tra.
Điều đó không chứng minh field hay source system tương ứng không tồn tại ngoài
repository này.

## Review labels không phải pair labels

`review-label-v1` trong `services/analysis-worker/review_learning/labels.py`
ánh xạ approve/reject và truth tier thành mức relevance của Counterfactual
candidate cho bài toán ranking. Nó không trực tiếp gán nhãn “cặp alarm liên
quan”, “cùng một incident”, hay “Audit split đúng”. Provenance
`EXTERNAL_OPERATIONAL` cũng chỉ mô tả nguồn; không tự xác định target label.

Backtest cho feature pairwise cần giữ riêng ít nhất ba target: pair
related/unrelated được adjudicate; cùng/khác incident từ nguồn incident được
duyệt; và kết quả của proposal split/merge đã được reviewer xem. Không chuyển
nhãn giữa các target nếu chưa có mapping được kiểm định. `DEFER`,
`INSUFFICIENT_EVIDENCE` và trường hợp chưa review không được biến thành negative.

Kiểm kê file trong repo ngày 2026-09-28: hai artifact ranker `v1` và `demo`
đều ở trạng thái `DRAFT`; data profile lần lượt có 13 và 29 review groups,
nhưng toàn bộ là `SYNTHETIC_TEST`/`TEST_FIXTURE`. Fixture feedback khác có
4 record synthetic và tự khai báo không hợp lệ làm production ground truth.
Không tìm thấy bộ nhãn pair/incident NOC được lưu trong repo. Đường review
runtime có thể lưu `MANUAL_CORRECTION` với `partition_delta` đã kiểm tra tính
bảo toàn alarm, cùng reviewer/truth tier; một partition do reviewer đề xuất
vẫn chưa tự chứng minh “cùng root cause” hoặc “cùng incident”. Cần xác nhận
ngữ nghĩa nhãn và nguồn adjudication trước khi suy ra nhãn pair. Sau khi có
quyền Docker, truy vấn chỉ đọc PostgreSQL ngày 2026-09-28 thấy 526 review
sessions: 460 `REAL_EXPORT_REPLAY`, 30 `SOURCE_KIND_UNAVAILABLE` và 36
`SYNTHETIC_TEST`. Trong 109 feedback, 108 thuộc synthetic fixture; feedback
duy nhất thuộc real replay là `APPROVE`/`PO_ASSERTED` cho `REMOVE_MEMBER` và
đã bị `RETRACTED`. Không có manual correction. Vì vậy DB này không có feedback
vận hành còn hiệu lực để huấn luyện Counterfactual ranker; session chưa được
review không phải nhãn âm.

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
