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

Các channel chính:

- `E_device`, `E_card`, `E_site`, `E_remote`: evidence entity/co-location.
- `S`: semantic similarity.
- `T_burst`: cùng contextual burst trong blocking context.
- `T_delay`: compatibility với phân phối delay có hướng học từ lịch sử.
- `Dep_hop`: khoảng cách hop khi alarm-resource mapping và topology semantics
  phù hợp.
- `H`: historical co-occurrence/lift theo episode độc lập.
- dependency/failure-domain signals chỉ khả dụng khi capability tương ứng được
  xác minh.

Evidence cùng derivation phải được deduplicate trước khi aggregate để tránh
double-count. Một derivation group phải đồng nhất provenance và eligibility.
Raw NocPro values thuộc System Fact, không được normalize lén thành `s_k`.

## 4. Fit, membership và role

Với channel `k`, `Fit_k` là tỉ lệ pair khả dụng của member với các peer đạt
`SUPPORT`. Không có pair khả dụng thì `Fit_k = unavailable`, không phải 0.

Với derivation group `g`, `Fit_g` aggregate các channel cùng nguồn suy dẫn.
`MembershipSupport(x,C)` là trung bình trên các group role-eligible và khả dụng.
Role chỉ được quyết định khi đạt minimum computable groups và availability
coverage.

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
Edge cần đủ distinct audit-eligible derivation groups. `SYSTEM_FACT` và
`BEHAVIORAL` không tự động trở thành audit weight.

Candidate cut được tạo deterministic từ entity, dependency, failure-domain và
descriptor primitives cùng phép union/difference đã định nghĩa. Conductance và
multi-evidence verdict được tính trên exact eligible graph trong configured
ceiling. Vượt ceiling hoặc thiếu evidence phải trả component `UNAVAILABLE`,
không chạy một approximation không khai báo.

Audit visualization là projection bounded của artifact exact đã persist. Nó
không feed ngược vào Audit, Role, topology hypothesis hoặc Counterfactual.

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
- Display tree, alias resolver hoặc primary path không được dùng để suy ra
  common ancestor, active path, dominator, propagation hoặc failure domain.

Các P2 topology hypothesis chỉ chạy với directed topology, mapping và temporal
capability phù hợp. Nếu thiếu, kết quả đúng là `UNAVAILABLE`.

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
