# Active Methodology

Tài liệu này là bản phương pháp vận hành ngắn gọn của Hindsight. Các quyết định
chi tiết và lý do lựa chọn được giữ trong [33 ADR](adr/README.md). Khi source và
ADR frozen mâu thuẫn, implementation phải được sửa hoặc methodology phải được
revision rõ ràng trước; không được âm thầm đổi semantics.

## 1. Phạm vi và nguyên tắc

Input là snapshot chứa alarm, partition/chain, metadata NocPro tùy chọn,
topology/context tùy chọn và provenance. Hindsight trả lời các câu hỏi hậu kiểm:

- alarm nào thuộc chain và evidence nào hỗ trợ quan hệ đó;
- member nào được hỗ trợ mạnh, yếu, chưa đủ dữ liệu, có tính structural hoặc
  gần trùng lặp;
- descriptor nào mô tả chain và phân biệt chain với candidate khác;
- chain có dấu hiệu over-merge theo evidence graph hay không;
- chain/incident thay đổi thế nào qua snapshot;
- partition thay thế nào được evidence hỗ trợ tốt hơn.

Hindsight không tuyên bố nhìn thấy nội bộ Louvain/NocPro nếu input không cung
cấp. Trong Black-box mode phải dùng ngôn ngữ “post-hoc support”, không nói
“model gom vì topology/time”. Gray-box system facts luôn hiển thị tách biệt với
evidence do Hindsight suy ra.

## 2. Snapshot, identity và provenance

Snapshot là processing boundary. Identity tối thiểu của một artifact gồm
`snapshot_id`, `snapshot_version`, chain/member identity, config version và
fingerprint của input liên quan. Artifact từ snapshot/config khác không được
tái sử dụng như thể tương thích.

Bốn provenance class:

| Class | Ý nghĩa |
| --- | --- |
| `SYSTEM_FACT` | dữ kiện do NocPro/upstream cung cấp |
| `POST_HOC` | evidence do Explain tính độc lập sau chaining |
| `BEHAVIORAL` | mẫu học từ lịch sử hành vi |
| `EXTERNAL_OPERATIONAL` | nhãn hoặc validation vận hành từ nguồn ngoài |

Provenance class mô tả nguồn evidence, không định nghĩa đối tượng được gán
nhãn. `EXTERNAL_OPERATIONAL` tự nó không phải nhãn pair-relatedness, cùng
incident hay đúng/sai của một Audit proposal. `review-label-v1` hiện ánh xạ
feedback vào relevance của Counterfactual candidate; không dùng nó thay cho
nhãn pair hoặc incident nếu chưa có phép ánh xạ được kiểm định riêng.

`source_kind`, `chaining_usage` và quality/capability gate quyết định một dữ
liệu có được dùng cho Explain, Role, Audit hoặc Validate hay không. Synthetic
source luôn phải có nhãn `SYNTHETIC_TEST`; derived window từ một export là
`DERIVED_REPLAY`, không phải snapshot production độc lập.

## 3. Evidence model

Mỗi pair channel trả về availability, positive score, threshold, derivation
group và provenance. Trạng thái chuẩn:

```text
SUPPORT     available và positive_score >= threshold
NEUTRAL     available, đã tính, nhưng dưới threshold
UNAVAILABLE không thể tính hợp lệ
```

Missing không phải negative evidence. `UNAVAILABLE` không được đổi thành
`NEUTRAL`, zero hoặc “weak”. Missing system pair record là `UNKNOWN`, không phải
NocPro đã đánh giá pair là independent.

Các channel pairwise hiện hành được liệt kê đầy đủ trong
[Feature Capability Matrix](FEATURE_CAPABILITY_MATRIX.md). Một số ranh giới cần
giữ rõ khi diễn giải:

- Entity có năm sub-channel: `E_reference`, `E_device`, `E_card`, `E_site` và
  `E_remote`. Bốn channel đầu so khớp các field riêng; `E_remote` là quan hệ
  remote, không phải một mức trong hierarchy containment. Source không bảo đảm
  device → card → site thực sự lồng nhau, cũng không xác lập `E_reference` nằm
  trong hierarchy đó. Mỗi channel có derivation tag riêng; việc có group riêng
  là quy tắc gom hiện hành, không phải bằng chứng rằng field đó độc lập về
  thống kê hay nguồn đo.
- `S`: quan hệ ordinal theo alarm name, family và category có taxonomy phù hợp;
  không phải fuzzy text similarity.
- `T_burst`: cùng contextual burst trong blocking context.
- `T_delay`: compatibility với phân phối delay có hướng học từ lịch sử.
- `Dep_hop`: khoảng cách hop khi alarm-resource mapping và topology semantics
  phù hợp.
- Hai provider `DepUpstreamAncestor` và `DepUpstreamActivePath` đã được gỡ khỏi
  runtime ngày 2026-09-28 vì replay thật hiện không có directed dependency
  records hoặc active-path records phù hợp. Điều kiện khôi phục nằm trong
  [Deferred Directed Topology](DEFERRED_DIRECTED_TOPOLOGY.md).
- `H`: historical pair association/lift chỉ được thêm trong Pair WHY; không vào
  Membership/Role hay `G*_audit`.
- `H_domain`: membership theo failure-domain set/hyperedge để hỗ trợ context và
  candidate generation; không phải điểm pairwise và không được clique-project.
  Quan hệ `INSTANCE_LINKS_STORAGE` được giữ riêng là candidate
  `SHARED_RESOURCE_CONTEXT` khi topology hydrate đầy đủ source trace; chỉ đủ
  điều kiện làm Audit candidate nếu chain có ít nhất hai instance khác nhau
  cùng thuộc context. Nó chỉ nói các resource cùng trỏ tới storage, không biến
  thành failure-domain hay pair support. Edge có `quality_status=FAIL` vẫn có thể
  hiện như context để kiểm tra nhưng không được dùng làm candidate. Preset Explain `real_alarm_it_demo@5` mang 2.373 cạnh loại này trong
  projection hai hop quanh resource được map; 14 storage resource có giao với
  mapping của alarm và tạo 23 source-context memberships trên 14 chain. Không
  chain nào đủ hai instance khác nhau để thành candidate. Các alias topoIT duy nhất mang
  status `STRUCTURED_FIELD_UNIQUE`; chúng chỉ được dùng để tìm shared-storage
  context `UNKNOWN`, không được coi như verified mapping cho `Dep_hop` hoặc
  explicit failure-domain. Đây vẫn là context, không phải dependency hoặc nhãn
  cùng incident.

Input Contract v1 có `operational_context` với context ID/type, affected
resources, thời gian và provenance; Mock có thể tạo các record này cho synthetic
scenario. Pairwise evaluator hiện chưa dùng chúng để ghép hai alarm. Provenance
subtype `MAINTENANCE` tự nó chỉ phân loại nguồn; nó không khẳng định hai alarm
cùng một event vận hành.

Evidence cùng derivation phải được deduplicate trước khi aggregate để tránh
double-count. Một derivation group phải đồng nhất provenance và eligibility.
Raw NocPro values thuộc System Fact, không được normalize lén thành `s_k`.

## 4. Fit, membership và role

Với channel `k`, `Fit_k` là tỉ lệ pair khả dụng của member với các peer đạt
`SUPPORT`:

```text
Fit_k(x,C) = supporting available peers / available peers
```

Không có pair khả dụng thì `Fit_k = unavailable`, không phải 0. Với effective
derivation group `g`, implementation lấy giá trị lớn nhất trong các `Fit_k`
tính được của group đó. Sau đó:

```text
Fit_g(x,C) = max(Fit_k(x,C) for computable k in g)
G_role(x,C) = computable groups whose role_eligible flag is true
MembershipSupport(x,C) = sum(Fit_g for g in G_role) / |G_role|
```

Hai phép gộp trên đều không trọng số: `Fit_g` là max trong group;
`MembershipSupport` là trung bình cộng giữa các group role-eligible khả dụng.
`domain_size` làm mẫu số bên trong từng `Fit_k`, nhưng không được dùng để cân
trọng số giữa các channel hoặc group. Công thức không có hiệu chỉnh phương sai,
khoảng tin cậy hay shrinkage theo cỡ mẫu; một `Fit_k` có ít pair khả dụng vẫn
có thể cực trị hơn. Đây là giới hạn cần đo độ nhạy, chưa tự nó chứng minh công
thức sai.

`MembershipSupport` là phép aggregate mô tả, không phải xác suất membership và
không tuyên bố các effective group độc lập. Distinct group keys là ranh giới
triển khai, không chứng minh nguồn bằng chứng độc lập. Đây là công thức riêng
với trọng số cạnh Audit, không được dùng thay thế lẫn nhau. Role chỉ được quyết
định khi đạt minimum computable groups và availability coverage; các gate này
không phải hiệu chỉnh bất định lấy mẫu.

Các trục role độc lập:

- membership role: `CORE`, `PERIPHERAL`, `WEAK` hoặc `INSUFFICIENT_DATA`;
- structural role: connector/non-connector từ exact Tier-2 Audit;
- redundancy role: near-duplicate candidate/unique.

`ROOT`/`SYMPTOM` từ upstream, nếu có, là System Fact riêng; membership score
không được đổi thành causal label.

Singleton là first-class: pair-based membership và structural audit là
`NOT_APPLICABLE`, không phải `WEAK` chỉ vì không có peer.

## 5. Descriptor và Similar Chains

Descriptor mining dùng bitmap/index và giữ hai mục tiêu riêng:

- `IDENTITY`: mô tả cái phổ biến/đặc trưng bên trong chain;
- `CONTRASTIVE`: phân biệt target với local candidate universe.

Phải báo các metric liên quan cùng nhau (support, precision, recall/FPR, lift,
margin, representativeness khi khả dụng). Missing descriptor khiến
representativeness unavailable; không có nghĩa chain atypical.

Descriptor predicates hiện có gồm cả severity và alarm type. Các descriptor này
có thể tác động gián tiếp tới representativeness dùng trong phân loại `CORE` và
tới candidate generation của Structural Audit. Chúng không phải pairwise
compatibility channel; `S` cũng không so severity/alarm type. Vì vậy không mô tả
severity/type là “chỉ dùng để viết narrative”, nhưng cũng không diễn giải
descriptor equality thành bằng chứng pairwise rằng hai alarm thuộc cùng sự cố.

Similar Chains dùng fingerprint đã version và cosine baseline trên corpus
`history < current snapshot`. Taxonomy block có thể unavailable mà model vẫn
chạy degraded bằng các feature được phép. Không infer family/category từ tên
alarm khi không có taxonomy authority.

## 6. `T_burst` và `T_delay`

NocPro `TimeWindow` là System Fact và không đồng nhất với `T_burst` hoặc
`T_delay`.

`T_burst` dùng silent-gap segmentation bên trong context hợp lệ; không dùng một
global gap cho toàn bộ national stream.

`T_delay` dùng thứ tự thời gian có hướng. Với quan hệ `A -> B`:

```text
delta_t = start(B) - start(A), delta_t > 0
score(delta_t) = local_mass(delta_t) / max_t local_mass(t)
```

Local mass dùng Histogram hoặc Gaussian KDE. CDF centrality không được dùng làm
typicality vì có thể cho điểm cao ở khoảng rỗng giữa hai mode. Model được đóng
băng theo training cutoff, lineage-prefix fingerprint, taxonomy version,
config và corpus fingerprint.

Điều kiện availability gồm:

- authoritative `TYPE/FAMILY/CATEGORY` taxonomy;
- nhiều historical snapshot trước cutoff và lineage episode hợp lệ;
- timestamp parse được và strict temporal order;
- đủ số episode độc lập cho relation;
- training/fallback config đầy đủ;
- persisted model tương thích snapshot/config.

Pair WHY có adapter dùng frozen model. Full-chain Role/Audit hiện không có exact
indexed sufficient-statistics path cho `T_delay`; phải trả
`NO_EXACT_INDEXED_SUFFICIENT_STATISTICS_PATH`. Dense `O(n^2)` fallback bị cấm.

## 7. Execution tiers và hiệu năng

- Tier-1A: precompute theo snapshot sau barrier hoàn chỉnh.
- Tier-1B: lazy interactive analysis theo chain, dùng exact index/sufficient
  statistics và cache có version.
- Tier-2: async, on-demand, per-chain cho Audit, attribution và Review.

Pair detail phục vụ drill-down/visualization có thể bounded nhưng không được làm
thay đổi statistical truth. Không materialize toàn bộ pair graph ở snapshot
scale hoặc large-chain scale. Pairwise path chỉ dùng cho pair-on-click,
small-chain oracle hoặc explicit equivalence/debugging.

## 8. Structural Audit

Audit chạy trên `G*_audit`, không chạy trên graph đã cắt top-K để hiển thị.
Với mỗi pair, cạnh chỉ tồn tại khi ít nhất hai distinct audit-eligible
derivation groups trả `SUPPORT`. Trọng số hiện tại là tổng positive score của
các group hỗ trợ chia cho số audit-eligible groups khả dụng; group khả dụng
nhưng `NEUTRAL` nằm trong mẫu số, còn group `UNAVAILABLE` không nằm trong mẫu số.
Distinct groups không chứng minh các nguồn bằng chứng độc lập. `SYSTEM_FACT` và
`BEHAVIORAL` không tự động trở thành audit weight; riêng `H` bị loại khỏi pair
profile của Audit.

Candidate cut được tạo deterministic từ entity, dependency, failure-domain và
descriptor primitives cùng phép union/difference đã định nghĩa. Conductance và
multi-evidence verdict được tính trên exact eligible graph trong configured
ceiling. Vượt ceiling hoặc thiếu evidence phải trả component `UNAVAILABLE`,
không chạy một approximation không khai báo.

Audit visualization là projection bounded của artifact exact đã persist. Nó
không feed ngược vào Audit, Role hoặc Counterfactual.
CLI chẩn đoán coverage/LOGO offline được mô tả trong
[Audit Diagnostics](audit-diagnostics.md); nó không thay đổi graph, verdict,
Role hay production policy và không chứng minh feature set đầy đủ.

Pair channels hiện có `SUPPORT`, `NEUTRAL`, `UNAVAILABLE`, chưa có verdict
phủ định tường minh trong `K_pair`. `negative_score` trong cấu trúc channel
không tự tạo ra trạng thái phản đối. Gray-box có thể giữ `M_pair.system_semantic`
với giá trị `VETO` như upstream `SYSTEM_FACT`; nó được trình bày tách biệt và
không tạo Audit edge hay post-hoc negative channel. Tier-2 có input tùy chọn
`cross_block_negative_evidence` (mặc định `false`), nhưng source hiện không có
producer nội bộ đã xác định cho input này. Counterfactual Review cũng có một
đường nhận external-validation contradiction đã qua eligibility gate; đường đó
không phải `K_pair` và không được tự xem là producer cho Audit hook. Audit
coverage/sensitivity diagnostic chỉ đo các evidence group đã khai báo, không
kiểm chứng rằng tập channel bao phủ mọi quan hệ thật.

## 9. Evolution và drift

Evolution theo lineage/membership qua snapshot, không theo raw chain ID. Event
gồm `CONTINUE`, `GROW`, `SHRINK`, `SPLIT`, `MERGE`, `RECOMBINATION`, birth/death
theo contract. Mỗi transition phải thể hiện joined, left, retained và turnover;
`delta_size = 0` không đồng nghĩa không thay đổi.

Drift phân biệt `DATA_DRIFT`, `CONFIG_DRIFT` và `MIXED`. Tier-1B/Tier-2 drift
cần compatible cache/artifact ở cả hai snapshot; thiếu một phía là unavailable.
Derived replay có thể kiểm tra pipeline nhưng không chứng minh production
incident evolution.

## 10. Topology

Topology navigation và analysis semantics là hai capability khác nhau:

- IP export hiện cung cấp undirected structural adjacency. Exact-mapped endpoint
  có thể hỗ trợ bounded `Dep_hop` proximity.
- IT export hiện cung cấp source relations hữu ích cho navigation, nhưng direction
  và business dependency semantics chưa được xác minh.
- Directed dominator/propagation/scope analysis và hai shared-context provider
  hiện không nằm trong runtime. Display tree, alias resolver, primary path,
  undirected adjacency và snapshot metadata không tự xác nhận dependency hoặc
  nguyên nhân. Quy trình bổ sung lại có gate dữ liệu và kiểm thử ở
  [Deferred Directed Topology](DEFERRED_DIRECTED_TOPOLOGY.md).

## 11. Counterfactual Review

Review tạo proposal `REMOVE_MEMBER`, `SPLIT_CHAIN`, `MOVE_MEMBER` và
`MERGE_CHAINS` trong bound cấu hình. Candidate phải bảo toàn partition invariant,
dùng exact affected-region metrics, qua hard gates và Pareto selection.

Review không mutate NocPro. `BETTER_SUPPORTED` chỉ nói metrics hậu kiểm tốt hơn;
chỉ external artifact/ground truth phù hợp mới cho phép claim mạnh hơn.
Synthetic fixture không calibration production. `ADD_MEMBER` vẫn blocked khi
upstream chưa cung cấp semantics cho zero-membership alarm.

## 12. LLM và UI

LLM chỉ render grounded narrative hoặc parse intent trong bounded read-only tool
loop. Deterministic facts, status, target, artifact và action vẫn do backend sở
hữu. Provider lỗi, stale context hoặc vượt bound phải fallback rõ ràng; LLM
không được fill unavailable evidence hay phát lệnh mutation.

UI phải render đúng payload và availability. Không được tạo số phần trăm, delay
range, confidence, causal language hoặc recommendation khi backend không cung
cấp. Loading, empty, unavailable và error là các trạng thái khác nhau.

## 13. Governance và evaluation

Config phải có version và parameter provenance như `FROZEN_SPEC`,
`DOCUMENTED_DEFAULT`, `DATA_DRIVEN` hoặc `SYNTHETIC_ONLY`. Tên `calibrated`
không đủ chứng minh calibration; cần sample counts, source eligibility và
artifact tái kiểm tra được.

Evaluation phải tách:

- correctness/unit and spec-sanity;
- synthetic integration;
- Docker/PostgreSQL/Kafka runtime acceptance;
- raw-export replay measurement;
- controlled production validation và operator ground truth.

Một process/container healthy, một test pass hoặc một benchmark đơn lẻ không
được nâng thành production SLO hay causal validation.

## 14. Durable Deep Dive on demand

Deep Dive là explicit operator action. Mỗi lần chạy phải có durable identity
theo snapshot/version, chain membership, analysis/config version và cache
fingerprint. PostgreSQL lưu lifecycle coarse-grained (`QUEUED`, `RUNNING`,
`SUCCEEDED`, `FAILED`, `INTERRUPTED`) cùng public result payload đã version;
exact Structural Audit tiếp tục dùng immutable `audit_artifact` riêng.

UI khi mở Structural Audit chỉ đọc latest compatible run. Nếu run còn hoạt động
thì nối lại polling; nếu đã hoàn tất thì hydrate result; nếu không tương thích
thì không được render như current. Reload không tự submit compute. API restart
không được để một persisted `RUNNING` giả tồn tại vô hạn: khi chưa có durable
worker/lease recovery, run không còn trong executor phải được trả thành
`INTERRUPTED`.

Mỗi capability trong result giữ status riêng. Một run có thể `SUCCEEDED` trong
khi similarity, topology hoặc attribution là `UNAVAILABLE`/`NOT_APPLICABLE`;
UI phải hiển thị phần có thật và reason của phần thiếu, không đổi partial
availability thành thất bại toàn job hoặc fabricated success.
