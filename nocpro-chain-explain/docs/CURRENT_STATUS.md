# Current Status

Baseline snapshot: **2026-09-08**, branch `feat/code_ui`. Các mục cập nhật bên
dưới ghi rõ ngày và phạm vi; chúng không phải đợt xác nhận lại toàn bộ
repository. Không capability nào tự trở thành production-ready chỉ vì được ghi
ở đây.

## Cách đọc trạng thái

| Nhãn | Nghĩa |
| --- | --- |
| Implemented | Có code path và contract |
| Unit verified | Có automated unit/regression evidence |
| Synthetic verified | Đã chạy với fixture synthetic |
| Runtime verified | Đã chạy qua service/container/browser được ghi nhận |
| Production validated | Có dữ liệu production, calibration/ground truth phù hợp |
| Unavailable | Thiếu input, semantics, config hoặc exact path; fail-closed |

## Tổng quan capability

| Capability | Implementation | Evidence hiện có | Production boundary |
| --- | --- | --- | --- |
| Input Contract, direct ingest, provenance/eligibility | Implemented | Unit + synthetic + recorded Docker replay | Contract input-dependent |
| Kafka chunk/barrier, PostgreSQL persistence, Tier-1A recovery | Implemented | Unit + synthetic Docker + raw-export replay được ghi nhận | Production sequential validation chưa có |
| Tier-1B indexed chain analysis, Fit/Role/Descriptor | Implemented | Unit + synthetic; large-chain anti-dense regression | `Fit_g` lấy max trong group; MembershipSupport là mean không trọng số giữa group khả dụng; không có hiệu chỉnh bất định theo cỡ mẫu |
| Pair WHY | Implemented | Unit + generic browser/runtime acceptance được ghi nhận | Từng channel có thể unavailable |
| Historical `H` | Pair model implemented | Synthetic model tests | Thiếu authoritative taxonomy và verified historical episodes |
| `T_delay` Pair WHY | Model/training/adapter implemented | Synthetic model tests | Local/production-shaped path chưa có đủ taxonomy, history, persistence và config |
| `T_delay` full-chain Role/Audit | Unavailable by design | Fail-closed regression | Chưa có exact indexed sufficient statistics; dense fallback bị cấm |
| Similar Chains | Implemented | Unit + synthetic + raw replay được ghi nhận | Taxonomy block degraded/input-dependent |
| Evolution lineage | Persisted implementation + bounded local fixture path | Unit + synthetic Docker; local fixture test | Chưa có verified sequential production snapshots |
| Structural Audit, cuts, conductance, attribution | Implemented dưới exact ceilings | Unit + synthetic + recorded Docker; một raw large-chain measurement | Input/config-dependent; một run không phải SLO |
| Bounded Audit visualization | Implemented từ persisted exact artifact | Unit + synthetic + recorded browser/restart | Visualization không phải analysis input |
| Durable Deep Dive on demand | Lifecycle/full public result persisted; UI hydrate latest compatible run | Unit/API + PostgreSQL write/read-back + Chromium reload | Local `make dev` chỉ sống qua browser reload; API-restart durability cần `DATABASE_URL` |
| Counterfactual Review | REMOVE/SPLIT/MOVE/MERGE implemented | Unit + synthetic Kafka/PostgreSQL/restart; browser coverage không đều mọi operation | Proposal-only, production calibration chưa được thiết lập |
| Real topology navigation & graph persistence | Implemented (Kafka chunks/barrier, ADR-0002 envelopes, PostgreSQL materialized graph, API projection/search/resolve) | Unit + synthetic Kafka consumer + API routes | Materialized navigation graph; Undirected proximity only |
| IP `Dep_hop` | Implemented cho exact-mapped endpoints | Unit + targeted replay smoke được ghi nhận | Undirected proximity only |
| Directed topology hypotheses | Removed from runtime; deferred pending eligible directed dependency data | Historical synthetic tests removed with implementation; see [deferred topology note](DEFERRED_DIRECTED_TOPOLOGY.md) | Re-add only after real source semantics, mapping, and availability are validated |
| Assistant/Advisor | Bounded read-only tools, grounded rendering và deterministic fallback implemented | Unit/API/UI; fallback acceptance được ghi nhận | Live provider browser acceptance của loop mới chưa được ghi nhận |

Các acceptance count/timing chi tiết cũ không được coi là current run. Git history
và test artifacts là nguồn để truy lại phép đo theo ngày.

## Cập nhật phạm vi evidence ngày 2026-09-27; bổ sung Audit ngày 2026-09-28 và đối chiếu topoIT ngày 2026-09-29

Đối chiếu source trong checkout `feat/fix-bugs`; xem
[Methodology](METHODOLOGY.md), [Feature Capability Matrix](FEATURE_CAPABILITY_MATRIX.md)
và [Data Sources](DATA_SOURCES.md) để biết ranh giới chi tiết.

| Khu vực | Trạng thái đã xác nhận | Giới hạn diễn giải |
| --- | --- | --- |
| Entity pair features | Có `E_reference`, `E_device`, `E_card`, `E_site`, `E_remote`; mỗi feature có derivation tag riêng | Chưa có căn cứ source/data để khẳng định device/card/site lồng nhau hoặc các field là nguồn độc lập; `E_remote` là quan hệ riêng |
| Topology pair evidence | `Dep_hop` dựa trên adjacency vô hướng; `DepUpstreamAncestor` và `DepUpstreamActivePath` đã gỡ khỏi runtime | Các channel đã gỡ từng cần dependency edges có hướng hoặc active-path records phù hợp |
| Historical/failure-domain | `H` chỉ vào Pair WHY; explicit `H_domain` records là membership set/hyperedge. File preset IT `@5` mang 2.373 cạnh `INSTANCE_LINKS_STORAGE` trong projection hai hop; có 23 source-context memberships trên 14 chain, nhưng không chain nào có hai instance khác nhau cùng context | Preset vẫn không có explicit failure-domain hay operational-context record. Shared-storage context chỉ nói các instance cùng trỏ tới storage trong source export; `FAIL` quality vẫn có thể hiện để kiểm tra nhưng không được thành Audit candidate; quan hệ này không chứng minh cùng incident, dependency hay nguyên nhân |
| Counter-evidence | Chưa có post-hoc negative channel trong `K_pair`; gray-box có thể giữ upstream `M_pair.system_semantic=VETO` riêng | `SYSTEM_FACT` không vào `G*_audit`; Audit bool hook mặc định `false`, chưa thấy producer; Counterfactual external-validation là đường riêng |
| Change/maintenance event | Contract có `operational_context`, Mock tạo synthetic records; pair evaluator chưa dùng chúng | Ba real replay preset đã kiểm tra có 0 record; provenance subtype `MAINTENANCE` không tự thiết lập quan hệ chung event |
| Severity/alarm type | Predicate descriptor có thể ảnh hưởng gián tiếp tới representativeness/CORE và Audit candidate generation | Chưa có pairwise severity/type compatibility feature; không chỉ là nội dung narrative |
| Review labels | `review-label-v1` tạo relevance cho Counterfactual candidate ranking | Không phải nhãn pair-relatedness, cùng incident hoặc đúng/sai của Audit split |
| Audit coverage diagnostic | Full candidate LOGO reports cho chains 26 và 14 member; exact graph-only LOGO cho chain IT 71 member với 30/30 invariant; Entity cross-tabs trên 6,185 within-chain pairs | Sensitivity mô tả; không có NOC ground truth, candidate/conductance cho IT 71 chưa hoàn tất, `delta_phi` chưa có căn cứ vận hành; gate Entity là `INSUFFICIENT_OPERATIONAL_EVIDENCE` |

Coverage/sensitivity đo các group đã đăng ký trong exact Audit profile. Kết quả
không chứng minh các pairwise channel bao phủ mọi đường quan hệ có thật.

### Review-label readiness checked on 2026-09-28

| Nguồn | Điều kiểm được | Dùng được để học gì lúc này |
| --- | --- | --- |
| `review-label-v1` | Approve/reject và truth tier được ánh xạ thành relevance của từng Counterfactual candidate; review chưa làm, defer và insufficient-evidence không thành nhãn âm | Chỉ bài toán xếp hạng candidate, không phải nhãn pair hoặc cùng incident |
| `artifacts/review_ranker/v1` và `demo` | 13 và 29 review groups; 37 và 82 candidate; toàn bộ `SYNTHETIC_TEST`/`TEST_FIXTURE`, cả hai manifest `DRAFT` | Kiểm tra đường huấn luyện synthetic; không phải hiệu quả vận hành |
| Manual correction contract | Lưu `partition_delta` với `after` hoặc `partitions` (`before` là tùy chọn), có kiểm tra bảo toàn alarm, reviewer, decision và truth tier | Có cấu trúc để điều tra các partition được duyệt; chưa tự xác nhận cùng incident/root cause |
| Review DB tại checkout này | Sau khi được cấp quyền Docker, truy vấn chỉ đọc thấy 526 review sessions, 3.641 candidate exposures và 109 feedback; 108 feedback là `SYNTHETIC_TEST`/`TEST_FIXTURE`, một feedback `REAL_EXPORT_REPLAY`/`PO_ASSERTED` đã `RETRACTED`; không có manual correction | Hiện có 0 feedback vận hành còn hiệu lực trong DB này để huấn luyện/đánh giá Counterfactual ranker |

File `config/review-learning/v1.yaml` khai báo `REVIEW_MEMORY` và ranker
`DISABLED`, nhưng API runtime hiện không đọc file này để quyết định nạp XGB.
Runtime nạp artifact khi có `NOCPRO_REVIEW_RANKER_ARTIFACT_DIR`; `make dev`
trỏ tới artifact `demo` synthetic/DRAFT và tắt governance trong môi trường
development, nên local demo có thể rerank bằng XGB. Production loader mặc
định yêu cầu artifact đã duyệt, chữ ký và source/truth tier hợp lệ; hai artifact
trong repo không đủ điều kiện. API training trực tuyến cũng bị chặn; chỉ có
batch training từ PostgreSQL. Learn hiện chỉ lưu/tra cứu review và phục vụ
bài toán xếp hạng Counterfactual candidate; review gộp/tách không chứng nhận
topology dependency.

File preset Explain `real_alarm_it_demo` hiện mang `snapshot_version=5`: 500
alarm, mapping được tính lại thành 288 `STRUCTURED_FIELD_UNIQUE`, 63
`AMBIGUOUS`, 149 `UNMAPPED`, cùng projection điều hướng topoIT hai hop gồm 3.814
node/5.603 cạnh. Các source relation giữ nguyên nhãn và quality `UNKNOWN`; không
được coi là dependency hay đi vào `Dep_hop`. Timestamp lỗi vẫn được giữ raw và
gắn quality flag nhưng canonical endpoint lỗi bị để trống. Snapshot `@1`–`@4`
đã lưu không tự được viết lại. DB đã có identity `real_alarm_it_demo@4` với
payload cũ; API không cho ghi đè cùng identity bằng payload mới.

Ngày 2026-09-28, migration PostgreSQL hoàn tất, API health trả `ok`, endpoint
chọn snapshot trả đúng `real_alarm_it_demo@3` với 500 alarm, 226 chain và
topology version `it-598b2726fc12d46566800478f5648da4`; catalog báo active
version `3`. Ngày 2026-09-29, API liệt kê file `@4` và DB `@3`, nhưng
`POST /snapshots/select` cho `@4` trả HTTP 422 vì identity đó đã có payload
khác; active snapshot vẫn là `real_alarm_20260907_demo@1`. Không ghi đè DB.
Để giữ snapshot identity bất biến, file mới được version hóa thành `@5` và API
được rebuild. Sau đó catalog liệt kê `@5`, `@4`, `@3`; chọn `@5` trả 500 alarm,
226 chain và topology version
`it-598b2726fc12d46566800478f5648da4`. Catalog xác nhận active
`real_alarm_it_demo@5`. `GET /chains/6336417` trả 2 member, mỗi member mang hai
`SHARED_STORAGE` context ID; Pair WHY trả 200 và `Dep_hop=UNAVAILABLE`. Điều
này xác nhận storage source-context đi tới chain member view, còn không bị
diễn giải thành pair dependency evidence.

`alarmIT.csv` có 258.344 alarm/82.453 chain ID; `@5` dùng lại chính xác 500
alarm ID của `@3` (0,1935% export), không phải toàn bộ hoặc mẫu đại diện. Trong
226 chain xuất hiện ở slice, 225 đủ thành viên theo file nguồn; chain `6336451`
thiếu 10 alarm ngoài slice. Trong ba alarm có timestamp 2057/đảo thứ tự, raw
timestamp và cờ chất lượng được giữ nhưng canonical thời gian sai không còn đi
vào chain span/T_burst. `parent_id`, `child_id`, `is_root_alarm` vẫn được giữ raw;
chưa dùng như quan hệ incident/causal vì repo không có codebook/source contract
xác nhận ngữ nghĩa.
Trong 500-row slice, `cah.trouble_code` có 357 giá trị không rỗng/354 mã khác
nhau; hai mã lặp. Mã `GNOC_TT_IT_260728_182581780` xuất hiện ba lần qua chain
`6336416` và `6336417`; cả ba alarm map vào cùng instance
`it:instance:17865`. Mã `GNOC_TT_IT_260728_182581957` xuất hiện một lần ở mỗi
chain `6336430` và `6336450`; cả hai alarm chưa map được resource. Đây là các
ứng viên raw để kiểm tra ý nghĩa field, không phải bằng chứng incident.
`parent_id`/`child_id` có 2/1 record chứa danh sách ID ngoài `[]`; trong đó
alarm `2010140605` ở chain `6336416` tham chiếu parent `2010140606` ở chain
`6336417`, nên có một liên kết raw bắc qua chain. Chưa có contract xác nhận
semantics, valid-time hay độ độc lập của các field này; chúng chưa được nâng
thành `operational_context`, pair evidence hoặc nhãn cùng incident. `wo_code`,
`cr_number` và `alarm_type_name` trống toàn bộ slice. Vì vậy raw có dấu hiệu
liên hệ cần điều tra, nhưng chưa có feature pairwise mới nào đủ căn cứ để bật.

### Fit aggregation clarified on 2026-09-27

Source inspection confirms the same formula in streamed and indexed paths:
`Fit_k = supporting / available`, `Fit_g = max(computable Fit_k in group)`, and
`MembershipSupport = unweighted arithmetic mean of computable role-eligible
Fit_g`. `domain_size` enters the per-channel ratio only; it does not weight the
group maximum or the cross-group mean. There is no variance, confidence
interval, or small-sample shrinkage correction in this score. The formula is
retained as the versioned baseline pending a labeled sensitivity evaluation;
the score is compatibility evidence, not a calibrated membership probability.
The Entity channels have separate derivation tags in the current registry, so
the group-local maximum does not collapse them into one Entity vote.

### Entity co-support and grouping sensitivity on replay data

An entity-only state cross-tab covered every within-chain pair in the three
checked 500-alarm fixtures: IP 1,008 pairs, IT 4,463, and `20260907_demo` 714.
In IT, `E_device` and `E_card` states match on 4,084/4,463 pairs (91.5%); in
the selected 71-member chain they induce the same equality partition, and
`E_site` supports every pair. A diagnostic-only shared tag for device/card/site
removed 3 of 2,058 Audit edges in that chain and changed 1,782 other edge
weights. The three removed edges were supported by those three Entity groups
alone; Semantic and temporal-burst were neutral. The corresponding graph
scenario preserved the winner on the 26- and 14-member chains, with raw
conductance drift 0.1198 and 0.0599. No materiality threshold or independent
incident labels exist, so these results confirm group-count sensitivity, not
that a particular edge or split is wrong. A narrower device/card-only scenario
kept all edges but changed 1,785 IT and 205 IP edge weights; it was defined
after inspecting the same data and is exploratory, not a holdout result. Full
tables are in the remediation plan; machine-readable exploratory outputs are
under `/tmp` and are ephemeral.

### Entity field lineage checked across all preset alarms

`E_device` reads `device_code`; `E_card` reads raw `component` only. Contract v1
keeps `component` inside the raw field map and declares no identity/alias
relation with `device_code`. The Mock topology mapper's `component or port`
fallback is a separate mapping path, not the input rule for `E_card`. No
authoritative field dictionary was found in the inspected repository.

Across all 500 alarms in each replay preset, the device/component equality
partitions agree on 1,026 and disagree on 1,114 of 82,621 comparable IP pairs;
they agree on 2,081 and disagree on 186 of 44,551 comparable IT pairs. The IP
mapping is many-to-many among rows where both values exist; IT has nine device
values associated with multiple component values; `20260907_demo` has no
component values. These all-preset pairs are descriptive only, not labels or
same-chain Audit outcomes. This rules out a global merge based on current
fixture evidence, but does not prove the fields are statistically independent
or that any existing Audit edge is wrong. Keep current derivation tags pending
upstream field semantics and correctly typed holdout labels.

## Những điểm UI hiện chưa phản ánh đúng backend

### Chain WHY

Chain WHY hiện tách rõ thống kê descriptor khỏi Historical H. Thống kê 60 giây
đầu là phép đếm timestamp quan sát của UI, có mẫu số timestamp hợp lệ và không
được gọi là điểm `T_burst`. `T_delay` chỉ báo model khả dụng khi backend cấp
trạng thái AVAILABLE; điểm của một cặp vẫn phải xem tại Pair WHY. Topology
không còn tự hiện 100% khi thiếu số mapped/total. Các thống kê quan sát này
không chứng minh quan hệ nhân quả hoặc độ đúng của Audit.

Phần cohesion narrative đã có API mới, nhưng header “4 of 6 dimensions” và
fallback narrative vẫn chứa copy cố định. Narrative không sửa được các metric
hardcode phía trên.

### Evolution

Tab cross-snapshot và chronological timeline hiện đã conditional-render đúng;
các fallback thời gian/duration giả trước đó đã được giảm. Local API có thể dựng
một DAG từ ba derived-replay snapshot cụ thể và trả lineage cho chain tương ứng.
Đây là fixture-specific path, không phải Evolution cho mọi preset. Snapshot
demo mặc định có thể vẫn trả unavailable nếu không nằm trong DAG đó.

### Recommendations

UI đã có GET/latest, submit Review và polling flow. Workspace hiện có thể tự
submit Deep Dive trước Review, nhưng việc mở tab có thể khởi tạo compute và có
race nếu Audit chưa hoàn tất trong khoảng đợi bounded. Đây không phải bằng chứng
rằng recommendations luôn sẵn sàng.

## `T_delay`: vì sao local chưa train

Model thống kê có thật: nó học directed delay distribution theo
`TYPE/FAMILY/CATEGORY`, chọn Histogram hoặc Gaussian KDE, tính normalized local
mass và đóng băng artifact theo cutoff/config/taxonomy/corpus.

Local `make dev` có truyền `DATABASE_URL` và khởi động hạ tầng PostgreSQL.
Điều này không tự tạo historical corpus hợp lệ, taxonomy có thẩm quyền hoặc
model `T_delay` đã train. Demo ranker XGB dùng config riêng
`config/review-learning/demo.yaml` cùng artifact synthetic DRAFT; config mặc
định `v1.yaml` giữ ranker DISABLED. Demo không phải model production.

Vì vậy Pair WHY phải trả unavailable khi model/taxonomy/relation không tồn tại.
Chain WHY hiển thị model readiness thô, không hiển thị điểm pair `T_delay`.

## Calibration Status & Prerequisites

`config/thresholds/calibrated.yaml` đã được chuẩn hoá với `counterfactual.calibration_status: SYNTHETIC_ONLY`.
Calibration đo MembershipSupport theo member, gap theo context của `T_burst`,
và conductance từ candidate Audit canonical. Mỗi họ tham số đủ mẫu được áp
dụng trực tiếp vào cấu hình đang chạy sau khi validate và ghi nguyên tử; họ
thiếu mẫu giữ giá trị cũ. Không có report API/file. Nút trả 204 khi có cập
nhật, 422 khi không họ nào hợp lệ. Startup calibration mặc định tắt.

`DATA_DRIVEN` chỉ chỉ nguồn giá trị phân vị; P95/P25/P50/P5 và các clamp vẫn
là policy đặt tay, chưa được kiểm outcome NOC. Calibration không tự đặt
`PRODUCTION_CALIBRATED`. Nhãn `SYNTHETIC_ONLY` của Counterfactual vẫn giữ.

## Data/topology blockers

- Chưa có authoritative alarm taxonomy `TYPE/FAMILY/CATEGORY` dùng được cho H
  và `T_delay` production.
- Chưa có chuỗi production snapshot liên tiếp, verified và trước cutoff.
- IP topology chỉ xác minh undirected adjacency.
- IT topology direction/business meaning chưa xác minh; alias mapping chỉ dùng
  cho navigation.
- Chưa có ground-truth operator corrections đủ để calibration recommendation.
- `ADD_MEMBER` chưa có upstream zero-membership semantics.

## Việc nên làm tiếp

Ưu tiên theo data truth, không theo độ bắt mắt UI:

1. Loại bỏ hoặc nối backend cho toàn bộ metric hardcode trong Chain WHY; nếu
   backend thiếu thì hiển thị explicit unavailable.
2. Sửa calibration pipeline/config để sample count bằng 0 không thể tạo nhãn
   `PRODUCTION_CALIBRATED`.
3. Quyết định local developer fixture có chủ động attach synthetic taxonomy và
   T-delay model hay giữ production-shaped fail-closed; UI phải ghi đúng mode.
4. Làm generic Evolution source hoặc ghi rõ catalog preset/chain được hỗ trợ.
5. Tách action “open Recommendations” khỏi side effect submit compute, hoặc làm
   trạng thái submit/poll/audit dependency rõ ràng.
6. Thu thập authoritative taxonomy, sequential snapshots và operator labels để
   đóng các production gate.

## Kiến trúc phân tách Mock & Pure Kafka Topology Pipeline (Cập nhật 2026-09-09)

1. **Phân tách hoàn toàn `nocpro_mock` khỏi Explain API**:
   - `services/api/nocpro_api/catalog.py` đã loại bỏ hoàn toàn việc import `nocpro_mock` và `replay_csv`.
   - Toàn bộ 12 snapshot catalog presets (bao gồm 3 real replay: IP, IT, 20260907) đã được tiền sinh và lưu trực tiếp trong `nocpro-chain-explain/config/presets/`.
   - API hoàn toàn tự lực (self-contained) cả khi chạy local lẫn trong Docker container.
   - Kiểm tra `test_catalog_truth.py` tự động xác thực toàn bộ 12 preset về tính tồn tại của file và tính chính xác của `alarm_count`/`chain_count`.

2. **Đường truyền Topology thuần Kafka (Pure Kafka Topology Pipeline)**:
   - Giao tiếp giữa Mock và Explain API hoàn toàn 100% qua Kafka streaming, không qua HTTP proxy.
   - Mock bắn initial topology snapshot qua topic chuyên biệt `nocpro.topology.v1` (`nocpro.topology.v1.dlq` cho dead-letter queue).
   - **Phạm vi hiện tại (Current Scope)**: Hệ thống triển khai cơ chế **initial full-graph snapshot bootstrap** (`TOPOLOGY_CHUNK` + `TOPOLOGY_COMPLETE`). Mỗi khi có cập nhật hoặc khởi động lại, toàn bộ đồ thị theo phiên bản được stream nén theo chunk (2MB/chunk) và kết thúc bằng commit barrier. Cơ chế **incremental delta streaming** (stream từng thay đổi node/edge vi mô) được quy hoạch vào giai đoạn sau khi có upstream CDC/delta stream khả dụng.
   - Payload được nén zstandard (level 3) và chia chunk an toàn, kết thúc bằng barrier `TOPOLOGY_COMPLETE`.
   - Explain API (`KafkaTopologyConsumer`) lắng nghe, deduplicate qua `topology_kafka_inbox`, giải nén có cơ chế bảo vệ zip bomb (chặn nếu vượt quá 256MB), kiểm tra checksum SHA-256 toàn vẹn, và vật chất hóa (materialize) vào các bảng PostgreSQL:
     - `topology_versions`, `topology_active_versions`
     - `topology_nodes`, `topology_edges`, `topology_alias_resolution`
   - Giải quyết triệt để race condition: Nếu snapshot đến trước topology mà nó tham chiếu (`topology_ref`), snapshot chuyển sang trạng thái `PENDING_TOPOLOGY`. Khi topology version tương ứng commit thành công, snapshot lập tức được đánh thức (`wake_pending_topology`) và đẩy sang Tier-1A.

3. **Snapshot Decoupling & Slimming Invariant**:
   - Snapshot alarm đã được tách rời hoàn toàn khỏi đồ thị topology thô.
   - Mặc định snapshot chỉ mang `topology_ref` (`profile_id`, `topology_version`) cùng với `mappings`. Thuộc tính `nodes=()` và `edges=()` để rỗng (0 nodes, 0 edges).
   - Analysis Worker khi phân tích tương quan graph (ví dụ `Dep_hop` hoặc role analysis) sẽ hydrate trực tiếp từ PostgreSQL materialized graph theo đúng `topology_ref`, không còn phụ thuộc vào việc nhét hàng nghìn node/edge thô vào snapshot payload.

4. **Chuẩn hóa Versioning Canonical đồng nhất**:
   - Sử dụng hàm chuẩn duy nhất `canonical_topology_version(profile_id: str, source_version: str) -> str` tại `contracts/v1/models.py`.
   - Hàm chuẩn hóa loại bỏ tiền tố `sha256:`, trích xuất 32 ký tự hex đầu tiên, và gắn tiền tố profile (`ip-` hoặc `it-`), đảm bảo tính nhất quán tuyệt đối giữa publisher, snapshot replay, và database persistence.
   - Được bảo vệ bởi test tự động đa repository: `tests/test_cross_repo_topology_version.py`.

5. **Phục vụ Navigation Tree trực tiếp từ Explain API**:
   - Explain API cung cấp trực tiếp các endpoint REST:
     - `GET /api/v1/topology/profiles`
     - `GET /api/v1/topology/projection`
     - `GET /api/v1/topology/search`
     - `GET /api/v1/topology/resolve`
   - Web frontend chuyển sang gọi trực tiếp Explain API (`/api/v1/topology/*`), loại bỏ hoàn toàn mọi liên kết tới `/mock-api`.
   - Dữ liệu giữa `nocpro-mock` và `nocpro-chain-explain` hoàn toàn 100% qua Kafka streaming. Nginx gateway trong production cung cấp route `/mock-studio/` như kênh browser/operator điều khiển Mock Studio trực tiếp, không phải kênh truyền dữ liệu sang Explain; các endpoint legacy `/mock-api/` bị chặn 404 hoàn toàn.

6. **Bảo tồn bất biến phương pháp luận (Methodology Invariants)**:
   - IT Topology mang `relation_model="SOURCE_RELATION"`, `direction_kind="SOURCE_RELATION"`, `p2_eligible=False`, `dependency_semantics="UNVERIFIED"`.
   - IP Topology mang `relation_model="PHYSICAL_ADJACENCY"`, `direction_kind="NONE"`, `p2_eligible=False`, `dependency_semantics="UNAVAILABLE"`.
   - Các quan hệ navigation thuần túy không bao giờ bị thăng hạng (promoted) nhầm lẫn thành bằng chứng phụ thuộc vận hành (P2 operational dependency).

## Verification gần nhất trong phiên review (2026-09-09)

- `make test`: **120 backend tests** passed, **28 mock server tests** passed, **59 web frontend Vitest tests** passed.
- `tests/test_topology_engine.py`: **4 passed** (kiểm tra directed hierarchy, cycles, multi-parent, undirected adjacency).
- `tests/test_kafka_topology_consumer.py`: **5 passed** (kiểm tra deduplication inbox, DLQ routing khi payload lỗi/mismatched key, chunk assembly, barrier commit & coordinator wake).
- `tests/test_topology_api_routes.py`: **4 passed** (kiểm tra `/api/v1/topology/{profiles,projection,search,resolve}`).
- `tests/test_cross_repo_topology_version.py`: **3 passed** (kiểm tra snapshot & publisher version parity, deterministic digest, và snapshot slimming invariant).
- `tests/test_topology_repository_integration.py`: **3 passed** (kiểm tra real table lifecycle, atomic inbox deduplication, dual-path barrier assembly, IP undirected projection, IT alias resolution, status lock).
- `tests/test_kafka_topology.py` (mock producer): **3 passed** (kiểm tra IP, IT và chunk wire serialization).
- `grep -rn "mock-api" nocpro-chain-explain/services/web/`: **0 kết quả trong code thực thi** (đã gỡ sạch khỏi frontend và Nginx).
- `pnpm lint` (web): **0 warnings, 0 errors** (65 files, 116 rules).
