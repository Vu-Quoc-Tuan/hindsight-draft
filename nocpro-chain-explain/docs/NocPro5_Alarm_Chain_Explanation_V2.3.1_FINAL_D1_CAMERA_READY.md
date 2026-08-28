# NocPro 5 — Thiết kế cuối: Module Giải thích & Kiểm định Xâu chuỗi Cảnh báo

**V2.3.1 FINAL + Data/Integration Addendum D1 (28/08/2026)**

**Camera-ready editorial/fail-closed pass:** khóa semantics `source_kind`, `chaining_usage`, `Quality`, system metadata typing, singleton behavior và MVP adapter; **không đổi methodology/toán**.

Bản thiết kế baseline cuối cùng của module Alarm Chain Explanation & Validation cho NocPro 5: dual-mode Gray-box/Black-box, Evidence Engine đa kênh, 6 loại WHY, Audit, Evolution, thực thi phân tầng Tier-1A precompute 10–30s mỗi snapshot, Tier-1B tương tác P95 <5s và Tier-2 on-demand 5–30s; kèm scope MVP/P0/P1/P2, evaluation và tài liệu tham khảo đã kiểm chứng. Các con số latency là design objective chờ benchmark trên dữ liệu/hardware thật.

## 0. Phán quyết & thay đổi ở vòng chốt này

**Trạng thái: V2.3.1 FINAL — KIẾN TRÚC VÀ MATHEMATICAL SPEC ĐÃ FREEZE. KHÔNG có V2.4 theo hướng design-paper.** Data/Integration Addendum D1 bên dưới **không đổi các công thức 4A–4B**; nó chỉ siết semantics tích hợp sau khi có tài liệu Attribute/Louvain, chain thực 2214039 và topology export thật. Từ đây, thay đổi tiếp tục chỉ đến từ Data thật → Prototype → Benchmark → Failure cases.

**Patch V2.3.1 (theo danh sách reviewer, không thêm gì ngoài):**

🔴 **1. Provenance class thêm POST_HOC** — bộ class đúng: SYSTEM_FACT / **POST_HOC** / BEHAVIORAL / **EXTERNAL_OPERATIONAL** (đổi tên từ INDEPENDENT — mơ hồ). Evidence từ raw alarm fields (same name/device/reference/burst) là POST_HOC, KHÔNG được gọi independent vì raw field có thể chính là feature NocPro dùng để chaining (mục 4).
🔴 **2. Derivation-group aggregation cho G\* VÀ Attribution** — v2.3 mới chống double-count ở Agreement; w* và φ vẫn đếm theo channel → reference sinh 3 channel có thể ăn 3 lần weight / ~75% credit (representation artifact). Fix: aggregate s_g⁺ = max{s_k⁺ : k∈g} trước, w* và Attribution chạy trên GROUPS (4B, 8).
🔴 **3. Temporal typicality sửa cho multimodal** — 2·min(F, 1−F) SAI khi delay đa mode (bimodal {2s,100s}: Δt=50s → F≈0.5 → score 1.0 dù vùng gần như không xảy ra). Fix: local probability mass s⁺(Δt) = P_r(|T−Δt|≤h)/max_t P_r(|T−t|≤h); CDF chỉ dùng hỏi tail extremeness (4A).
🔴 **4. Tách K_pair khỏi H_domain** — Dep_domain không còn là pairwise channel: formalize K_pair (pairwise) và H_domain (failure-domain hyperedges, không có s(i,j)); hypergraph dùng cho WHY/member/cross-block/context, không vào G* (4/4A).

🟠 **5. MembershipSupport scalar định nghĩa** = mean Fit_g trên explanatory derivation groups đủ availability; vector giữ, scalar chỉ để ranking; WEAK gate đổi chữ thành "≥2 DISTINCT COMPUTABLE DERIVATION GROUPS" (4B). **6. Type discipline pair vs chain** — chain-level descriptor không được làm player trong pair-level Agreement; provenance DAG tách pair-evidence / chain-descriptor / rule-annotation (4). **7. Drift đúng tier 3 mức** — 1A basic / 1B cached (roles chỉ khi cả hai snapshot có 1B cache) / Tier-2 deep (7). **8. Similar Chains baseline spec** — fingerprint TF-IDF(family)+TF-IDF(device)+top descriptors+size/duration bins; baseline cosine similarity (8).

🟡 **9. Specificity normalize** — log(1+N/|Desc|)/log(1+N) ∈ [0,1] (công thức cũ vượt 1 khi |Desc|=1) (4A). **10. Identity vs Contrastive descriptor** — hai search objective riêng; global floor không giết rule "globally common, locally discriminative" (5). **11. Candidate-cut generation bảng tất định** (6). **12. ε_Φ binning fallback** — n_min per bin → coarser bin → global weak baseline (6). **13. Attribution scalability guard** — không materialize C(20k,2) (8). **14. Self-contained pass** — inline các định nghĩa "giữ v2.1/v2.2" vào chỗ (4B/5/6/7/8). **15. P1-core minimum bar** — commitment thật khi một người/một kỳ = 3+1 mục (14).

**Final cleanup:** History chỉ tạo positive evidence khi lift>1; support threshold được quyết định ở channel trước khi aggregate derivation-group; thêm eligibility mask (explain/role/audit/validation) để ngăn circular reinforcement; tách M_pair khỏi M_chain_rule; thống nhất EXTERNAL_OPERATIONAL/subtype; Similar Chains baseline chốt cosine; consensus/derivation infrastructure được đưa xuống MVP/P0.


**Nguyên lý thống nhất của đề tài (chốt):** giải thích dưới partial observability — không đánh đồng evidence với model reasoning, không đánh đồng behavioral consistency với operational correctness, mọi claim truy ngược được về nguồn + config version. Bốn lớp provenance được enforce bằng công thức (consensus, w*, attribution đều dedup theo derivation).


## 0A. Data/Integration Addendum D1 — ràng buộc sau khi đối chiếu dữ liệu thật

**Mục đích:** giữ nguyên mathematical core V2.3.1 nhưng ngăn implementation hiểu sai tính độc lập của nguồn, raw score của NocPro, availability của metadata pair và semantics topology.

### 0A.1. Evidence thực tế dùng để freeze Addendum

Các ràng buộc dưới đây xuất phát từ ba nguồn đã có:

1. **Báo cáo Attribute/Louvain của NocPro (26/06/2026):**
   - Rule và Louvain cùng sử dụng tầng Attribute.
   - Có `TimeWindow`, `HistorySimilarity`, `TopologySimilarity`.
   - Raw system score không bị giới hạn trong [0,1] (có giá trị 2.0) và `TimeWindow` có veto `NEGATIVE_INFINITY_SCORE = -999999999`.
   - Attribute Engine sinh `simiDict` dạng pair → vector score.
   - Có early-break theo TimeWindow và `maxComparePerAlarm = 1000`.
   - Tài liệu này **không cung cấp** exact `A_ij`, ΔQ, node movement hay modularity trace.

2. **Golden case 2214039:**
   - 58 alarms, event span 22s.
   - 1653 = C(58,2): toàn bộ pair nằm trong characteristic `<600s`.
   - 435 = C(30,2) và 378 = C(28,2), 30+28=58: aggregate count nhất quán với hai block sạch theo `node_reference`.
   - 153 = C(18,2): nhất quán với block 18 alarms cùng `alarm_name`.
   - Đây là **two-block Gray-box fixture**, không phải ground-truth khẳng định NocPro over-merge sai.

3. **topoIP export hiện có:**
   - 201,977 relation rows, phần lớn là `SITE_ROUTER`.
   - Không có `DEHL01`, `DEHT01`, `HLC9102DEA01`, `HHT9603DEA01`.
   - Schema hiện có hai endpoint device/port và network class, nhưng không encode active path, routing direction hay dependency direction.
   - Vì vậy chain 2214039 hiện **không map được** sang topoIP này; `Dep_*` cho case đó phải là `⊥ UNAVAILABLE`, không được fuzzy-map cho có output.

### 0A.2. Sáu patch tích hợp bắt buộc

#### D1-1 — External source ≠ independent validation

Giữ nguyên bốn provenance class:

```
SYSTEM_FACT
POST_HOC
BEHAVIORAL
EXTERNAL_OPERATIONAL
```

Nhưng thêm hai metadata dimension **không phải provenance class mới**:

```
source_kind:
  REAL_LIVE
  REAL_EXPORT_REPLAY
  SYNTHETIC_TEST
  BACKFILL

chaining_usage:
  CONFIRMED_USED
  CONFIRMED_NOT_USED
  UNKNOWN
```

Thứ tự eligibility:

```
source_kind gate
      ↓
chaining_usage / independence gate
      ↓
provenance eligibility mask
```

Một nguồn external chỉ được dùng để **VALIDATE NocPro** khi:
- `source_kind ∈ {REAL_LIVE, REAL_EXPORT_REPLAY}`;
- `chaining_usage = CONFIRMED_NOT_USED`;
- provenance subtype cho phép validate;
- `quality_status = PASS`.

`SYNTHETIC_TEST` và `BACKFILL` **không được validate**. `BACKFILL` ở đây nghĩa là dữ liệu dùng để bootstrap/train/backfill state; historical export thật được replay đúng provenance dùng `REAL_EXPORT_REPLAY`, không gắn `BACKFILL` chỉ vì nó cũ.

`quality_status ∈ {PASS, FAIL, UNKNOWN}`; ngưỡng freshness/coverage/mapping/sample-size nằm trong `config_version`. `FAIL` hoặc `UNKNOWN` ⇒ **Validate = NO**.

`chaining_usage` **chỉ thắt VALIDATE**. Explain/Role/Audit tiếp tục theo provenance/type eligibility mask ở mục 4B; không có một policy ẩn thứ hai.

`chaining_usage` không phải property per-pair/per-alarm, cũng không nên gắn thô cho cả topology/history store. Nó được resolve theo **source identity/version + chaining configuration/run context**:

```
ChainingUsageAssessment
  source_id
  source_version
  chaining_config_version
  executed_rule_set / attribute_set (nếu biết)
  snapshot/run context
  usage ∈ {CONFIRMED_USED, CONFIRMED_NOT_USED, UNKNOWN}
```

Nếu không có đủ executed config để chứng minh nguồn không tham gia chaining ⇒ `UNKNOWN`.

**Không được suy `CONFIRMED_NOT_USED` chỉ vì UI/characteristic của một chain không liệt kê topology/history.**

#### D1-2 — NocPro Attribute là SYSTEM_FACT adapter, không phải normalized Evidence channel

Gray-box bổ sung **NocProMetadataAdapter** với các object tách type rõ:

```
M_attribute_config
  rule_id / rule_name
  attribute_id
  type
  content
  algorithmType
  filterName
  weight

M_pair
  alarm_i / alarm_j
  raw_score
  system_semantic / veto
  system_pair_status

M_chain_rule
  rule
  connector/extender metadata
  merge strategy

M_chain_characteristic
  characteristic
  value / threshold
  pair_count
  coverage_scope
```

Raw score/veto thuộc `M_pair`, **không thuộc `M_attribute_config`**. Aggregate characteristic thuộc `M_chain_characteristic`, không giả thành exact pair metadata.

Raw score NocPro giữ nguyên trong SYSTEM_FACT; **không normalize** `2.0`, `0.8`, `-999999999` vào `s_k⁺/s_k⁻ ∈ [0,1]`.

Ví dụ:

```
NocPro TextEqual(NODE_REFERENCE) → SYSTEM_FACT
E_reference tự tính từ raw alarm → POST_HOC
```

Hai đường có thể dùng cùng field nhưng không được collapse provenance.

#### D1-3 — System TimeWindow/HistorySimilarity/TopologySimilarity ≠ channel của Explain

Phân biệt bắt buộc:

```
NocPro TimeWindow         ≠ T_burst / T_delay
NocPro HistorySimilarity  ≠ H grouping-history
NocPro TopologySimilarity ≠ Dep_hop / Dep_upstream
```

- Characteristic `1653 pairs <600s` của 2214039 là SYSTEM_FACT.
- Characteristic `72 historical pairs` nếu do NocPro báo là SYSTEM_FACT.
- `H` của module vẫn phải episode-dedup + support/lift/reliability + temporal split.
- Không dùng system characteristic để “chứng minh” post-hoc channel tương ứng.

#### D1-4 — Missing system pair metadata không đồng nghĩa NEUTRAL

Pair-level SYSTEM_FACT dùng:

```
system_pair_status:
  EVALUATED
  NOT_EVALUATED
  UNKNOWN
```

- `EVALUATED` + known no-support ⇒ system neutral fact.
- `NOT_EVALUATED` ⇒ unavailable.
- `UNKNOWN` ⇒ unavailable.
- Missing record mặc định là `UNKNOWN`, không tự suy thành `NOT_EVALUATED`.

Aggregate system characteristic thêm:

```
coverage_scope:
  FULL_PAIR_SPACE
  BOUNDED_COMPARISON
  UNKNOWN
```

Case 2214039 có sanity mạnh cho characteristic `<600s`: 1653=C(58,2), nên có thể gắn `FULL_PAIR_SPACE` cho **characteristic đó**. Không áp suy luận này cho chain lớn.

#### D1-5 — Alarm→topology mapping và topology capability phải fail closed

Mọi topology-derived evidence phải qua:

```
alarm
  ↓
resource mapping
  ↓
topology semantic capability
  ↓
Dep_* hoặc ⊥
```

Mapping metadata tối thiểu:

```
topology_layer
mapping_method
mapping_confidence
mapping_status
source_version
freshness
```

Nếu alarm/resource không map được ⇒ `Dep_* = ⊥`.

Capability gate:
- adjacency đúng relation_type ⇒ `Dep_hop` có thể tính;
- directed hierarchy hợp lệ ⇒ mới bật `SHARED_ANCESTOR`;
- active-path semantics thật ⇒ mới bật `SHARED_ACTIVE_PATH`;
- dominator semantics ⇒ `UNAVOIDABLE_DEPENDENCY` (P2).

Không suy active path/upstream từ undirected device–port adjacency.

#### D1-6 — P1 CommonDependency là capability engine, không phải output bắt buộc

P1-core giữ CommonDependency nhưng wording sửa thành:

```
CommonDependency capability engine
+ Specificity anti-hub
+ H_domain support

SHARED_ANCESTOR:
  enable only when directed hierarchy exists

SHARED_ACTIVE_PATH:
  enable only when active-path data exists

otherwise:
  ⊥ UNAVAILABLE
```

Không synthetic active path để “đủ feature”.

### 0A.3. Những gì KHÔNG đổi

Addendum D1 **không đổi**:
- derivation-group aggregation;
- Fit_k / Fit_g / MembershipSupport;
- WEAK vs INSUFFICIENT DATA;
- IDENTITY / CONTRASTIVE descriptors;
- G*_explain / G*_audit;
- H_domain hyperedge semantics;
- deterministic candidate cuts + balanced Φ;
- lineage / DATA_DRIFT vs CONFIG_DRIFT;
- Similar Chains cosine baseline;
- Evidence Coverage Attribution;
- Tier-1A / Tier-1B / Tier-2.


## 1. Bài toán & phạm vi

**Chu trình thực tế:** cứ mỗi ~1 phút, NocPro lấy toàn bộ alarm đang active tại thời điểm t:

```
A_t = {a1, a2, ..., an}
```

với n từ vài nghìn đến hàng chục nghìn; kiến trúc phải chịu được ~100k alarm. Chaining Engine hiện có (Rule-based và Louvain-based, dùng chung tầng Attribute) biến snapshot thành các chain:

```
A_t --f--> P_t = {C_t^1, C_t^2, ..., C_t^k}
```

Sau một phút, toàn bộ grouping được thực hiện lại trên snapshot mới A_{t+1}. Trong một phút: alarm cũ có thể vẫn active, alarm mới xuất hiện, alarm cũ clear.

**Vị trí module:** đứng SAU chaining, không tạo chain, không sửa thuật toán:

```
Active alarms → Existing NocPro Chaining → Chains/Groups
                        ↓
        ══════ ALARM CHAIN EXPLANATION ══════
                        ↓
            WHY? / AUDIT / EVOLUTION
                        ↓
                 Interactive UI
```

**Ba mục tiêu lõi:**
- **WHY** — Tại sao chain/member/pair này trông hợp lý? Evidence nào support?
- **AUDIT** — Chain có điểm đáng nghi không: weak member, redundant alarm, hai block bị over-merge, connector?
- **EVOLVE** — Chain thay đổi thế nào qua các chu kỳ 1 phút, và thay đổi do alarm lifecycle hay do grouping?

**Non-goals (nói rõ để không bị hỏi vặn):** không tự động kết luận root cause (chỉ có root-cause CANDIDATE ở P2 khi đủ dữ liệu định hướng); không thay thế/điều chỉnh chaining; không làm causal discovery đầy đủ; không phụ thuộc internals của Louvain (simiDict, A_ij, ΔQ, node movement) — nếu sau này có thì thêm adapter, không đổi khung.

## 2. Hai chế độ: Gray-box & Black-box

**Gray-box / Chaining-aware** — có (A_t, P_t, M_t), trong đó M_t là metadata NocPro cung cấp. Ví dụ chain 2214039 (58 alarms, 14:30:02→14:30:24):

```
Rule REMOTE_NODE:     34/58 connector, 6 extender
Rule REFERENCE_NODE:  58/58 connector
Rule DEFAULT:         18/58 connector
Merge: OR
Characteristics: 1653 pairs time<600s · 435 pairs ref=DEHL01
                 378 pairs ref=DEHT01 · 153 pairs same alarm_name
                 72 historical pairs ...
```

Gray-box biết "NocPro nói gì về chain này" nhưng **không giả định** những thứ chưa có: exact edge A_ij, modularity contribution, node movement của Louvain, exact pair tạo merge, exact semantics của connector/extender khi source chưa xác nhận. Gray-box adapter có thể ingest thêm cấu hình Attribute (`type/content/algorithmType/filterName/weight`), raw system score/veto và system pair-status nếu upstream thật sự cung cấp; các giá trị này vẫn là **SYSTEM_FACT**, không được ép vào normalized `s_k` của Evidence Engine.

**Black-box** — chỉ có (A_t, P_t) cộng context module tự lấy từ các nguồn upstream/operational: K_t = {topology, history, logs, resource, KEDB, ...}. Không biết thuật toán, rule, feature, threshold, similarity, objective. **External source không mặc định đồng nghĩa independent validation**: nếu `chaining_usage` chưa chứng minh `CONFIRMED_NOT_USED`, nguồn đó không được dùng để xác nhận NocPro đúng.

**Kỷ luật wording (giữ xuyên suốt mọi tầng, mọi câu chữ trên UI):**
- Black-box KHÔNG nói: "Model gom X vào C vì topology."
- Black-box nói: "Kết quả X thuộc C được topology, entity và history **hậu kiểm support mạnh**."

**Quan hệ hai mode:** E_gray = E(A_t, P_t, M_t, K_t); E_black = E(A_t, P_t, K_t). Mọi tính năng đều chạy được ở Black-box; Gray-box chỉ THÊM tầng system evidence và threshold sensitivity — đây là graceful degradation, không phải hai hệ riêng.

**UI tách hai box rõ ràng** (pattern tương đồng IBM CP4AIOps: side panel nêu grouping type kèm link tới policy definition):

```
SYSTEM-PROVIDED EVIDENCE          POST-HOC ANALYSIS
─────────────────────────         ─────────────────────────
REFERENCE_NODE rule: 58 conn.     Reference pattern: highly discriminative
REMOTE_NODE: 34 conn + 6 ext      Temporal: high coverage, low discrimination
Merge: OR                         Two dominant resource blocks detected
```

## 3. Kiến trúc tổng thể & mô hình thực thi phân tầng Tier-1A / Tier-1B / Tier-2

**Latency wording chuẩn (v2.1):** "Tier-1A precompute 10–30s mỗi snapshot (background); Tier-1B truy xuất tương tác + giải thích cục bộ P95 <5s khi mở chain; Tier-2 deep dive on-demand 5–30s." KHÔNG viết tắt thành "Tier 1 <5s" — gây hiểu nhầm toàn Tier 1 chạy dưới 5 giây.

```
              SNAPSHOT A_t
   (initial engineering stress target ~100k — mục 11)
                          │
                          ▼
              EXISTING NOCPRO CHAINING (không đụng)
                          │
                          ▼
               P_t (+ M_t nếu Gray-box)
                          │
╔═ TIER 1A — SNAPSHOT BACKGROUND (mỗi snapshot, 10–30s*) ══╗
║  Global indexes · counts · chain metadata                ║
║  Descriptor candidates (bounded) · Auto chain title      ║
║  Evolution lineage graph · Cache warm                    ║
╚══════════════════════════════════════════════════════════╝
                          │  user mở một chain
                          ▼
╔═ TIER 1B — FAST LOCAL (on chain open, P95 <5s) ═════════╗
║  Indexed/sufficient statistics · evidence cục bộ bounded ║
║  Member WHY · Pair WHY on-click · Contrastive top-3      ║
║  Membership/Redundancy · audit_graph=NOT_COMPUTED        ║
╚══════════════════════════════════════════════════════════╝
                          │  user bấm "Phân tích sâu"
                          ▼
╔═ TIER 2 — ON-DEMAND DEEP DIVE (per-chain, 5–30s, async) ═╗
║  G*_audit exact/compressed · STRUCTURAL role              ║
║  Structural Robustness (balanced cut)                    ║
║  Evidence Coverage Attribution (closed-form)             ║
║  Similar incidents (dedup theo evolving chain)           ║
║  Propagation hypothesis (data-gated) · KEDB grounding    ║
║  LLM narrative rendering (optional)                      ║
╚══════════════════════════════════════════════════════════╝
                          │
                          ▼
              EXPLANATION API → INTERACTIVE WEB UI

* mọi con số là design hypothesis chờ benchmark (mục 11)
```

**Nguyên tắc tầng (bất biến):**
1. Tier 1B không bao giờ chờ Tier 2 — UI luôn render được từ cache 1A + tính nhanh 1B.
2. Tier 2 luôn chạy **per-chain**, không bao giờ trên toàn snapshot.
3. Cache theo khóa (chain fingerprint, snapshot version, config version); bấm lại không tính lại.
4. Tier 2 async với progress indicator; user vẫn thao tác Tier-1B view trong lúc chờ.
5. Tier-1 statistical default dùng indexed/sufficient statistics; không có
   semantics-preserving provider thì channel = `⊥ UNAVAILABLE`, không silent
   fallback sang dense all-pairs.
6. Pairwise implementation giữ làm correctness oracle cho chain nhỏ và Pair WHY
   on-click; không phải production default path.

Sự phân chia 1A/1B giải quyết inconsistency của V2 (architecture nói "background mỗi snapshot" nhưng Evidence Engine nói "materialize lazy per-chain" — giờ 1A làm global/background, 1B làm local/lazy). Chi tiết engine: mục 4–8; đặc tả toán học: mục 4A–4B.

## 4. Evidence Engine — nền móng

**Hai cấu trúc normalized evidence + tầng system metadata (V2.3.1 + Addendum D1):**

```
K_pair — NORMALIZED ATOMIC PAIRWISE EVIDENCE CHANNELS
         (thuật toán Fit/consensus/G*/audit):
  { T_burst, T_delay,
    E_reference, E_device, E_card, E_site, E_remote,
    Dep_hop, Dep_upstream,
    H, S }

M_pair — PAIR-SCOPE SYSTEM METADATA (SYSTEM_FACT, Gray-box):
  exact-pair raw system score/veto/decision/evaluation status nếu upstream cung cấp.
  KHÔNG bắt buộc nằm trong [0,1], KHÔNG là player normalized của
  Fit/Agreement/G*_audit/Attribution.

M_chain_rule — CHAIN/RULE-SCOPE SYSTEM METADATA:
  rule, connector/extender, merge; luôn hiển thị riêng khỏi POST_HOC evidence.

M_attribute_config — ATTRIBUTE-CONFIG SYSTEM METADATA:
  type/content/algorithmType/filterName/weight; KHÔNG chứa raw pair score/veto.

M_chain_characteristic — AGGREGATE CHAIN SYSTEM METADATA:
  characteristic/value/threshold/pair_count/coverage_scope;
  KHÔNG tự sinh exact pair edges.

H_domain — FAILURE-DOMAIN HYPEREDGES (KHÔNG phải pairwise channel):
  mỗi h = { failure_domain_id, domain_type (SRLG/fiber/power/rack/
  site/service-instance/process/VM-host/config-change), member
  alarms/resources, source, Quality, provenance }
  Dùng cho: WHY chain · member explanation · cross-block explanation ·
  operational context. KHÔNG tham gia G* (không có s(i,j); không
  clique-project — trừ khi sau này có projection rule công khai riêng).

+ OPERATIONAL CONTEXT (context layer: maintenance/config change/ticket)
```

"View" (Temporal/Entity/Dependency...) chỉ là cách UI nhóm channel.

**Mỗi normalized channel k ∈ K_pair mang:** s_k⁺, s_k⁻ ∈ [0,1] (song song), availability ∈ {0,1}, derivation tag, provenance class, Quality_k [freshness, coverage, sample size, mapping confidence]. `M_pair/M_chain_rule/M_attribute_config` là SYSTEM_FACT adapter objects và **không bị ép** theo contract score [0,1].

**Provenance class (v2.3.1 — khớp đúng nguyên tắc 4 lớp):**

```
SYSTEM_FACT           metadata NocPro cung cấp (M_pair / M_chain_rule /
                      M_chain_characteristic / M_attribute_config)
POST_HOC              evidence tính từ raw alarm fields / derived
                      (same alarm_name, same device, same reference,
                      same burst, hop distance...) — KHÔNG được gọi
                      "independent": raw field có thể chính là feature
                      NocPro dùng để chaining
BEHAVIORAL            học từ output NocPro (grouping-history H,
                      threshold TEMPORAL_BEHAVIORAL)
EXTERNAL_OPERATIONAL  nguồn ngoài pipeline; subtype:
                      TOPOLOGY_EXTERNAL (inventory/NMS/export; tính độc lập với chaining
                      được xác định riêng bằng chaining_usage) ·
                      TICKET · OPERATOR_LABEL · MAINTENANCE ·
                      FAULT_INJECTION
```

Gán class: T_*/E_*/S = POST_HOC · Dep_* = EXTERNAL_OPERATIONAL với subtype=TOPOLOGY_EXTERNAL nếu topology từ inventory/NMS/export ngoài alarm pipeline, POST_HOC nếu suy từ chính alarm data · H = BEHAVIORAL · M_pair/M_chain_rule/M_chain_characteristic/M_attribute_config = SYSTEM_FACT · context/ticket = EXTERNAL_OPERATIONAL. `TOPOLOGY_EXTERNAL` là subtype, không phải provenance class.

**Addendum D1 — independence metadata:** provenance class không tự chứng minh nguồn độc lập với chaining. Source mang `source_kind`; validation còn resolve `chaining_usage ∈ {CONFIRMED_USED, CONFIRMED_NOT_USED, UNKNOWN}` theo `(source_id, source_version, chaining_config/run context)` và `quality_status ∈ {PASS, FAIL, UNKNOWN}` theo config version. `UNKNOWN` ở chaining usage hoặc Quality đều **không được VALIDATE**. `chaining_usage` không thay đổi Explain/Role/Audit mask.

**Provenance DAG — type discipline (v2.3.1):**

```
raw field "reference"
   ├─ E_reference           (PAIR evidence node)
   ├─ descriptor ref=DEHL01 (CHAIN-level node)
   ├─ M_chain_rule REFERENCE_NODE (CHAIN-level rule annotation node)
   ├─ M_chain_characteristic ref=DEHL01, pair_count=435 (CHAIN aggregate SYSTEM_FACT)
   └─ M_attribute_config TextEqual(NODE_REFERENCE) (SYSTEM_FACT)
Pair-level Agreement CHỈ lấy normalized pair-evidence nodes trong K_pair.
Chain-level WHY có agreement riêng của nó.
Chain-level descriptor KHÔNG BAO GIỜ là player trong pair consensus.
```

**Ba trạng thái giá trị:** SUPPORT / NEUTRAL (đã tính, không support) / ⊥ UNAVAILABLE — phân biệt NEUTRAL với UNAVAILABLE là bắt buộc (WEAK vs INSUFFICIENT DATA).

**Semantic:** structured fields trước; template normalization chỉ khi cần text phi cấu trúc. **Provenance:** Claim → Evidence (channel/hyperedge) → Source (+ config version + nhãn nguồn threshold). Đặc tả định lượng: 4A–4B.

## 4A. Đặc tả Evidence Model — view, edge, threshold

Mathematical contract — định nghĩa từng channel k ∈ K_pair (mục 4) và H_domain.

```
T_burst — SameBurst, CONTEXTUAL
  Burst segmentation bằng silent-gap/change-point chạy TRONG blocking
  context (region/site/resource neighborhood/service domain) — KHÔNG
  trên global stream (toàn quốc có thể không bao giờ có silent gap).
  s⁺ = 1 nếu cùng contextual burst. Class: POST_HOC.

T_delay — DelayCompatibility (v2.3.1: LOCAL MASS, không phải CDF)
  Δt CÓ HƯỚNG theo relation học được: Δt = t_B − t_A cho A→B.
  s⁺(Δt) = P_r(|T − Δt| ≤ h) / max_t P_r(|T − t| ≤ h)
  (local probability mass qua histogram/KDE/fitted likelihood;
   bandwidth h: config + sensitivity)
  LÝ DO (v2.3.1): 2·min(F_r, 1−F_r) SAI với distribution đa mode —
  bimodal {~2s, ~100s}: Δt=50s cho F≈0.5 → score 1.0 dù vùng đó gần
  như không xảy ra. CDF chỉ còn dùng để hỏi tail extremeness
  ("delay có cực đoan không"), không phải typicality.
  Kernel/density = model-selection bằng holdout. BACKOFF:
  (type,type) → (family,family) → (category,category).
  Threshold provenance: TEMPORAL_DOMAIN vs TEMPORAL_BEHAVIORAL
  (behavioral → class BEHAVIORAL, không dùng validate). Class: POST_HOC.

E_* — Entity typed channels (POST_HOC)
  E_reference, E_device, E_card, E_site boolean/ordinal riêng;
  E_remote là relation riêng ngoài containment scale.
  derivation tag = field gốc (mọi channel phái sinh reference cùng
  derivation group).

Dep_hop (P0) — hop trên topology có semantic relation_type phù hợp:
  s⁺ = 1/(1+d), edge ⟺ d ≤ D_max; PHYSICAL/LOGICAL/SERVICE không trộn.
  BẮT BUỘC alarm→resource mapping thành công; unmapped → ⊥.
  Class: EXTERNAL_OPERATIONAL, subtype=TOPOLOGY_EXTERNAL nếu topology
  từ inventory/NMS/export ngoài alarm pipeline; POST_HOC nếu suy từ alarm data.
  Validate chỉ khi source_kind/chaining_usage qua gate D1-1.

Dep_upstream — CommonDependency (P1, CAPABILITY-GATED)
  Ba mức semantics: SHARED_ANCESTOR < SHARED_ACTIVE_PATH <
  UNAVOIDABLE_DEPENDENCY (dominator — P2). Vì ECMP/multi-homing:
  ancestor chung ≠ failure dependency.
  SHARED_ANCESTOR chỉ bật khi có directed hierarchy hợp lệ;
  SHARED_ACTIVE_PATH chỉ bật khi có active-path semantics thật;
  thiếu capability → ⊥ UNAVAILABLE, không suy từ undirected adjacency.

  Dấu `<` biểu diễn **độ mạnh semantic của claim** (epistemic specificity của
  loại quan hệ), KHÔNG phải ràng buộc thứ tự numeric của CD. Một narrow
  ancestor hoàn toàn có thể có CD cao hơn một shared active-core-path
  (vd CD_ancestor=0.85 > CD_active_path=0.30) mà không mâu thuẫn gì — vì CD
  phụ thuộc scope specificity + distance của candidate u, không phụ thuộc
  cấp semantic. Nếu UI/ranking cần ưu tiên theo tier semantic, lưu riêng
  `dependency_semantic ∈ {SHARED_ANCESTOR, SHARED_ACTIVE_PATH,
  UNAVOIDABLE_DEPENDENCY}` tách khỏi `strength = CD`; không nhét semantic
  tier thành hidden multiplier vào CD.

  CD_s(i,j) = max_{u∈U^s_ij} Specificity_s(u)·exp(−(d_s(i,u)+d_s(j,u))/λ_dep)
  (s = capability đang xét: SHARED_ANCESTOR hay SHARED_ACTIVE_PATH; λ_dep là
   decay scale riêng của dependency — không dùng chung ký hiệu với λ_H của
   history reliability)

  **Scope-dependent Specificity.** Specificity(u) dùng một scope set phù hợp
  với dependency semantic đang xét, KHÔNG dùng một `Desc(u)` chung cho cả
  hai capability (semantic của "descendant" chỉ tự nhiên với hierarchy):

  ```
  Specificity_s(u) = log(1 + N_s/|Scope_s(u)|) / log(1 + N_s)   ∈ [0,1]
  ```

  - SHARED_ANCESTOR: `U^anc_ij = Anc(i) ∩ Anc(j)` trong directed hierarchy;
    `Scope_anc(u) = Descendants(u)`; `N_anc` = tổng resource trong hierarchy.
  - SHARED_ACTIVE_PATH: gọi `P_t(r)` là tập verified active path của resource
    `r` tại snapshot/path-context `t`.
    `U^path_ij = { u : ∃ p_i∈P_t(i), p_j∈P_t(j), u∈p_i∩p_j }`;
    `Scope_path,t(u) = { r : ∃ p∈P_t(r), u∈p }` — tập **distinct mapped
    resource** có active path đi qua `u`, KHÔNG đếm nhiều ECMP path của cùng
    một resource nhiều lần (đếm path thay vì resource sẽ để representation
    artifact thổi phồng specificity);
    `N_path,t = |{ r : P_t(r) available }|` — số resource có observation hợp
    lệ **trong path universe/context đó**, KHÔNG dùng N = toàn bộ resource
    inventory (nếu path coverage chỉ 10% mạng mà lấy N = cả mạng thì
    specificity bị thổi phồng giả).

  (v2.3.1: công thức cũ 1/log(1+|Desc|) vượt 1 khi |Desc|=1 — phá contract
   s⁺ ∈ [0,1]. Anti-hub: Core router tổ tiên nửa mạng, hoặc core node nằm
   trên active path của hàng chục nghìn resource, → Specificity thấp ở cả
   hai capability.)

  **Distance.** `d_anc(i,u)` = hop ngược lên hierarchy. `d_path(i,u)` = hop
  trên verified ORDERED active path; nếu một resource có nhiều active path
  hợp lệ do ECMP, `d_path(i,u) = min_{p∈P_t(i): u∈p} d_p(i,u)`.

  **Fail-closed riêng cho SHARED_ACTIVE_PATH.** Để tính CD theo nhánh này,
  source cần đủ: resource mapping + verified active-path membership +
  ORDERED path/hop distance + snapshot/path-scope. Nếu chỉ biết "A và B đều
  liên quan tới path X" mà không có thứ tự/hop, quan hệ có thể được report
  như metadata nhưng **normalized CD = ⊥**. KHÔNG lấy shortest path trên
  topology adjacency để thay cho active-path distance bị thiếu — làm vậy sẽ
  biến "observed active path" thành "possible graph path", đúng điều D1 cấm.

H_domain — Shared Failure Domain (P1) — KHÔNG phải pair channel (v2.3.1)
  Biểu diễn hyperedge theo mục 4: "SRLG-384 → {A1..A17}".
  Không có s(i,j); explain qua domain membership ("17/58 share
  SRLG-384"); không vào G*. Căn cứ: CoNEXT 2010 (Tar) — 71–82%
  event cùng fault ở node có quan hệ topology.

H — grouping-history (BEHAVIORAL)
  Episode-deduped per evolving-incident. Chỉ association dương mới tạo
  positive evidence:
    strength_H = 0, nếu support < s_min hoặc lift ≤ 1
    strength_H = min(1, log(lift)/log(L_cap)), nếu lift > 1
      (L_cap = P99 của lift quan sát trong trailing window — cap để
       chuẩn hóa strength về [0,1]; config + sensitivity)
    s⁺ = strength_H × reliability(s)
    reliability(s) = 1−exp(−s/λ_H)
      (λ_H riêng của history — không trùng ký hiệu với λ_dep)
  (P1: có thể thay reliability bằng lower-CI/Bayesian shrinkage).
  lift < 1 KHÔNG được biến thành positive support; nếu sau này dùng thì
  chỉ có thể đi sang behavioral negative evidence với nhãn rõ ràng.
  BACKOFF type→family→category + badge NEW_SIGNATURE.

S — semantic ordinal (POST_HOC): same alarm_name 1.0 > family 0.6 >
  category 0.3; edge ⟺ same family trở lên.

M_pair — pair-level system metadata (SYSTEM_FACT, Gray-box; ngoài normalized K_pair)
  Giữ raw system score/veto/decision nếu upstream resolve được EXACT pair.
  Raw score CÓ THỂ ngoài [0,1] (vd 2.0 hoặc veto −999999999), nên
  KHÔNG normalize rồi đưa vào Fit/Agreement/G*_audit/Attribution.
  system_pair_status ∈ {EVALUATED, NOT_EVALUATED, UNKNOWN};
  missing record mặc định = UNKNOWN, không mặc định NEUTRAL.
M_chain_rule — chain-level system annotation (SYSTEM_FACT)
  vd `REFERENCE_NODE: 58 connector`, merge OR.
  KHÔNG sinh pairwise channel, KHÔNG là player của pair Agreement/G*.
M_chain_characteristic — aggregate chain system metadata (SYSTEM_FACT)
  vd `ref=DEHL01: pair_count=435`, `time<600s: pair_count=1653`;
  mang `coverage_scope`, KHÔNG tự resolve exact pair.
M_attribute_config — rule/attribute configuration (SYSTEM_FACT)
  type · content · algorithmType · filterName · weight.
  `TimeWindow`, `HistorySimilarity`, `TopologySimilarity` của NocPro
  KHÔNG đồng nhất với T_burst/T_delay, H, Dep_* của module.
  UI luôn phân biệt `Detected from system metadata` vs `Inferred`.

OPERATIONAL CONTEXT — context layer (EXTERNAL_OPERATIONAL)
  maintenance window / config change / ticket. Vai trò: annotation
  (PLANNED_ACTIVITY) · nguồn s⁻ (strength phân bậc: ticket validated
  MẠNH HƠN heuristic "maintenance khác nhau") · expected-scope
  comparison (mục 6). KHÔNG auto-suppress audit.
```

**Chính sách threshold:** system-provided → data-driven percentile → documented default + sensitivity; config versioned; explanation ghi config version + nhãn nguồn.

**Chuẩn hóa:** transform đơn điệu riêng cho **normalized evidence channel trong K_pair** về [0,1]; không cộng trọng số ẩn — kết hợp cross-channel chỉ qua consensus/G* theo derivation group (4B). Raw SYSTEM_FACT score/veto của NocPro không đi qua bước chuẩn hóa này.

**Phạm vi tính toán:** materialize per-chain Tier 1B; bounded neighbor chỉ cho hiển thị; audit graph theo quy tắc 3-graph (mục 6).

## 4B. Đặc tả Evidence Model — chain fit, role, consensus, G*

**Chain fit per channel:**

```
D_k(x, C) = { y ∈ C\{x} : availability_k(x,y) = 1 }
Fit_k(x, C) = |{ y ∈ D_k(x,C) : s_k⁺(x,y) ≥ θ_k }| / |D_k(x,C)|
|D_k| = 0 → Fit_k = ⊥;  mọi Fit_k = ⊥ → INSUFFICIENT DATA
```

**Derivation-group aggregation (v2.3.1 FINAL — threshold ở CHANNEL trước, aggregate sau):**

```
DerivGroups(i,j): nhóm NORMALIZED PAIR-evidence channel trong K_pair theo derivation tag.
Chain-level descriptor, M_pair, M_chain_rule, M_chain_characteristic và M_attribute_config KHÔNG là player.

b_k(i,j) = 1[availability_k=1 ∧ s_k⁺(i,j) ≥ θ_k]
b_g(i,j) = max_{k∈g} b_k(i,j)

nếu b_g=1:
  s_g⁺(i,j) = max{ s_k⁺(i,j) : k∈g ∧ b_k=1 }
nếu b_g=0:
  s_g⁺(i,j) = 0

s_g⁻(i,j) = max{ s_k⁻(i,j) : k∈g ∧ availability_k=1 }
Fit_g(x,C) = max{ Fit_k(x,C) : k∈g, Fit_k ≠ ⊥ }
```

→ Không tồn tại một `θ_g` tùy ý: mỗi channel tự quyết định SUPPORT bằng `θ_k`, rồi group chỉ dedup representation. Ví dụ channel A `0.70<θ_A=0.80` và channel B `0.60≥θ_B=0.50` → group SUPPORT vì B support; không bị sai do lấy max score rồi so với một threshold group không xác định.

**Derivation-group homogeneity invariant.** Mỗi derivation group `g` SHALL đồng nhất về `provenance_class` và **eligibility signature** ở mức normalized evidence (`explain_eligible`, `role_eligible`, `audit_eligible`). Nếu các channel có cùng raw `derivation_tag` nhưng khác provenance class hoặc khác eligibility signature — ví dụ `Dep_*` từ external inventory so với `Dep_*` suy từ chính alarm data — chúng SHALL được tách thành các **effective derivation group** khác nhau.

Nhờ vậy `provenance(g)`, `audit_eligible(g)`, `role_eligible(g)` và `Agreement_external` là well-defined ở mức group, và

```
availability_g(i,j) = max_{k∈g} availability_k(i,j)
```

chỉ aggregate các channel có **cùng eligibility regime** — một channel không eligible không thể làm cả group trông available cho Audit/Role.

Effective group key theo nghĩa semantic (không bắt buộc implement literal tuple này):

```
effective_group_key = (
    derivation_tag,
    provenance_class,
    explain_eligible,
    role_eligible,
    audit_eligible
)
```

`source_kind` và `chaining_usage` **không** thuộc homogeneity key: theo D1 chúng chỉ thắt VALIDATE, không làm thay đổi Explain/Role/Audit eligibility. Do đó external topology có `chaining_usage=UNKNOWN` và `CONFIRMED_NOT_USED` vẫn thuộc **cùng** effective derivation group; khác biệt đó chỉ ảnh hưởng validation verdict.

**Eligibility mask — enforce ranh giới Explain / Role / Audit / Validate (V2.3.1 + D1):**

**Validation gate trước provenance mask:**

```
source_kind ∈ {REAL_LIVE, REAL_EXPORT_REPLAY} ?
      ↓ yes
chaining_usage = CONFIRMED_NOT_USED ?
      ↓ yes
provenance/subtype validate-eligible ?
      ↓ yes
quality_status = PASS ?
      ↓ yes
VALIDATE
```

`SYNTHETIC_TEST` / `BACKFILL` ⇒ Validate NO.  
`chaining_usage ∈ {UNKNOWN, CONFIRMED_USED}` ⇒ Validate NO.  
`quality_status ∈ {UNKNOWN, FAIL}` ⇒ Validate NO.

`chaining_usage` chỉ thắt **VALIDATE**; Explain/Role/Audit giữ nguyên provenance/type eligibility mask.

| Provenance / subtype | Explain | Role | Audit graph | Validate |
|---|---:|---:|---:|---:|
| POST_HOC (temporal/entity/semantic...) | ✅ | ✅ | ✅ | ❌ |
| EXTERNAL_OPERATIONAL / TOPOLOGY_EXTERNAL | ✅ | ✅ | ✅ | ✅ **chỉ sau source_kind + chaining_usage + quality_status gate** |
| SYSTEM_FACT | hiển thị riêng | ❌ mặc định | ❌ | ❌ |
| BEHAVIORAL (grouping-history/behavioral threshold) | ✅, gắn nhãn | ❌ mặc định | ❌ | ❌ |
| EXTERNAL_OPERATIONAL / TICKET, OPERATOR_LABEL, MAINTENANCE, FAULT_INJECTION | ✅ | ❌ | ❌ positive graph | ✅ **chỉ khi source_kind hợp lệ + CONFIRMED_NOT_USED + quality_status=PASS** |

`SYSTEM_FACT` và `BEHAVIORAL` không được làm G*_audit mạnh lên; ticket/fault-injection có thể tạo CONTRADICT/validation verdict nhưng không được biến thành positive structural edge. Eligibility là config-versioned nhưng default trên là baseline methodology.

**Scope của `chaining_usage`:** assessment được resolve cho source/version trong context của executed chaining configuration/run của chain/snapshot đang xét. Không gắn một giá trị USED/NOT_USED duy nhất cho toàn topology/history store khi các rule khác nhau có thể dùng nguồn khác nhau. Thiếu complete executed config ⇒ `UNKNOWN`.

**Consensus hai lớp (trên derivation groups):**

```
Agreement_explain(i,j)  = #EXPLAIN_ELIGIBLE groups có b_g=1
                          / #EXPLAIN_ELIGIBLE groups available
                          (POST_HOC + BEHAVIORAL; BEHAVIORAL gắn nhãn)
Agreement_external(i,j) = #EXTERNAL_OPERATIONAL groups có b_g=1
                          / #EXTERNAL_OPERATIONAL groups available
SYSTEM_FACT hiển thị riêng, không cộng vào Agreement_external.
LƯU Ý: Agreement_external là mức external support, **không tự động là validation**;
validation còn phải qua source_kind/chaining_usage/Quality gate D1-1.
UI: "Support 2/2 groups available · (2/5 possible) · External: 1/2
     · Contradict: 1"
```

**Combined graphs G* — TRÊN DERIVATION GROUPS, có eligibility rõ:**

```
G*_explain: dùng EXPLAIN_ELIGIBLE positive groups cho visualization.
G*_audit:   CHỈ dùng AUDIT_ELIGIBLE positive groups cho structural audit.

availability_g(i,j) = max_{k∈g} availability_k(i,j)
G_audit(i,j) = { g : audit_eligible(g)=1 ∧ availability_g(i,j)=1 }

w*_audit(i,j) = Σ_{g∈G_audit(i,j)} α_g·s_g⁺·b_g
                 / Σ_{g∈G_audit(i,j)} α_g
Audit edge ⟺ ≥ 2 DISTINCT AUDIT_ELIGIBLE derivation groups support.
Nếu không có audit-eligible group khả dụng (mẫu số = 0) → AUDIT_INSUFFICIENT_DATA, không dựng edge.
```

`G_audit(i,j)` được định nghĩa tường minh để mẫu số của `w*_audit` **không bao giờ** chứa group unavailable cho pair (i,j): eligibility (audit_eligible) và availability là hai điều kiện độc lập, phải thỏa cả hai. Baseline audit-eligible gồm POST_HOC và EXTERNAL_OPERATIONAL phù hợp; `SYSTEM_FACT` và `BEHAVIORAL` bị loại khỏi positive audit graph.

Quy tắc "≥ 2 DISTINCT AUDIT_ELIGIBLE derivation groups" là **chống single-view edge**, không phải tuyên bố hai nguồn độc lập về mặt vận hành: hai group đều có thể là POST_HOC. `distinct derivation ≠ independent validation source`. Tương ứng, `chaining_usage` **không** thay đổi Audit eligibility — nó chỉ quyết định một nguồn external có được dùng để VALIDATE NocPro hay không.

Derivation dedup áp dụng cả weight: nhiều channel cùng phái sinh từ `reference` chỉ đóng góp MỘT lần. `M_chain_rule/M_chain_characteristic/M_attribute_config` không phải pair player; `M_pair` là SYSTEM_FACT và mặc định không audit-eligible. `s⁻` không bao giờ cộng vào positive G*; H_domain không project vào G*.

**Contradiction weighting:** verdict cân theo s_g⁻ strength × provenance subtype × Quality — ticket validated riêng biệt MẠNH HƠN heuristic maintenance-khác-nhau. Không binary.

**MembershipSupport — scalar định nghĩa trên ROLE_ELIGIBLE groups:**

```
G_role(x,C) = derivation groups có role_eligible=true ∧ Fit_g ≠ ⊥
MembershipSupport(x,C) = (1/|G_role|) · Σ_{g∈G_role} Fit_g(x,C)
Vector [Fit_g] luôn giữ; scalar CHỈ dùng để ranking/role.
```

Default `ROLE_ELIGIBLE` gồm POST_HOC temporal/entity/semantic + external topology/dependency; loại SYSTEM_FACT, BEHAVIORAL, ticket/maintenance/fault-injection. Vì vậy CommonDependency/topology thật sự có thể ảnh hưởng member/weak analysis mà không làm lẫn validation evidence với model reasoning.

**Contrastive — common set (trên groups):**

```
G_common(x; C, C′) = groups available cho cả hai
Margin_common(x) = mean_{g∈G_common} [Fit_g(x,C) − Fit_g(x,C′)]
|G_common| < g_min → INSUFFICIENT CONTRASTIVE EVIDENCE
```

**Role — 3 trục, RULES ĐẦY ĐỦ (v2.3.1, self-contained — không còn "giữ v2.1"):**

```
MEMBERSHIP:
  GATE tiên quyết: AvailabilityCoverage ≥ c_min
    ∧ ≥ 2 DISTINCT COMPUTABLE ROLE_ELIGIBLE DERIVATION GROUPS   ← đổi chữ, tránh
      nhầm với class (entity + semantic là 2 groups hợp lệ)
    ∧ các group không-support phải NEUTRAL (≠ UNAVAILABLE)
  CORE ⟺ MembershipSupport ≥ S_min (floor tuyệt đối — chống "best
          of a bad chain") ∧ rank ∈ top-quantile của chain
          ∧ Representativeness ≥ r_min ∧ Margin_common > 0
  WEAK ⟺ [gate thỏa] ∧ MembershipSupport ∈ bottom-band
          ∧ Margin_common ≤ 0
  PERIPHERAL = còn lại (gate thỏa)
  Gate không thỏa → INSUFFICIENT DATA
  |C| < 8: bỏ quantile, chỉ dùng floor (S_min, S_weak)
STRUCTURAL: CONNECTOR ⟺ articulation/bridge trên audit graph
            ∧ support tới ≥ 2 block;  ngược lại NON_CONNECTOR
REDUNDANCY: NEAR_DUPLICATE_CANDIDATE ⟺ ∃y: same alarm_name ∧ same
            entity ∧ Δt nhỏ ∧ không thêm descriptor coverage mới;
            ngược lại UNIQUE
Representativeness(x,C) = tỉ lệ top-descriptor mà x thỏa, weighted
  theo precision. BridgeImpact(x) = articulation flag + mức giảm
  kết nối cross-block khi loại x (bounded).
```

**Evidence Strength — 4 dòng riêng, không gộp:**

`Source Quality` phục vụ cả hiển thị và validation gate. Validation dùng `quality_status ∈ {PASS, FAIL, UNKNOWN}` được tính theo subtype + `config_version`; thiếu/không đủ dữ liệu ⇒ `UNKNOWN`, fail closed.

```
Availability     (groups computable / possible)
Agreement        (explain riêng · external riêng)
Source Quality   (freshness / coverage / sample)
Contradiction    (count + strength + source class)
```

Claim-specific: mỗi claim kèm 4 dòng của riêng tập evidence tạo ra nó. Calibrated probability chỉ ở P2 sau operator labels.

## 5. Explanation Engine — 6 câu hỏi WHY

**WHY-1 — Tại sao chain này tồn tại?** Descriptor mining INSPIRED BY Cluster-Explorer (PVLDB 2025) — không chạy nguyên gFIM trong Tier 1.

**HAI LOẠI DESCRIPTOR — hai search objective riêng (v2.3.1):** một global floor duy nhất sẽ giết rule "globally common, locally discriminative" (DIAMETER: global precision 8% — fail floor; nhưng trong U_local: 95% — chính là câu trả lời cho "why C1 rather than C2").

```
IDENTITY descriptor    — "What defines this chain globally?"
  maximize Coverage  s.t.  Precision_global ≥ p_min
  tie-break: rule ngắn hơn > Precision_local cao hơn
CONTRASTIVE descriptor — "What distinguishes it from nearby chains?"
  maximize Coverage  s.t.  Precision_local ≥ p_local  (trên U_local)
Chung bitmap engine; redundancy filter chạy TRONG từng loại.
```

**Implementation P0 — bitmap-backed bounded subgroup discovery:**

```
B_p bitmap per predicate; B_r = AND các B_p; TP/FP bằng popcount.
Beam search: max depth 2–3, beam width K, top-K predicates.
REDUNDANCY FILTER: hai rule extent Jaccard ≥ 0.9 → giữ rule điểm cao.
U_local(C) — ĐỊNH NGHĨA CỨNG: top-k competing chains từ blocking
index (đúng tập candidate của contrastive).
Bitmap hybrid: dense → packed bitset; sparse → Roaring.
```

Citation đúng: SD-Map (PKDD 2006) = FP-tree; BSD (FLAIRS 2010) = vertical bitsets. Không claim latency trước benchmark (20k predicates ≈ 250MB dense → hybrid + top-K attributes). Full gFIM: offline/Tier-2/hot chains.

**Hệ metric descriptor:** Coverage/Recall · Precision_global · Precision_local · FPR · Lift · F1. Ví dụ mất cân bằng: 30 trong + 500 ngoài / 100k → Coverage 51.7%, FPR 0.5% (tưởng tốt), Precision_global 5.66% (tệ). Insight nền: time<600s (100%/94%) = phổ biến không đặc trưng; ref=DEHL01 (52%/2%) = discriminative.

**Worked example 2214039 (Golden Gray-box / two-block fixture, KHÔNG phải over-merge ground truth):** 1653=C(58,2) → characteristic `<600s` phủ toàn pair space của chain; 435=C(30,2), 378=C(28,2), 30+28=58 → aggregate counts nhất quán với hai block sạch 30/28 theo `node_reference`; 153=C(18,2) → nhất quán với block 18 alarm cùng `alarm_name`. Expected behavior: phát hiện/hiển thị two-block structure và tạo candidate cut theo entity/reference; không hard-code verdict “NocPro sai/over-merge” nếu chưa có operational ground truth. Nhãn phải tách `SYSTEM_FACT`, `Detected from raw data`, `Inferred from aggregate counts`.

**WHY-2 — pair:** bảng per-channel (UI nhóm theo view) + Supporting/Contradicting hai cột + agreement hai lớp dạng tử số (theo groups) + system fact riêng.

**WHY-3 — member:** Fit_g + MembershipSupport (4B) vs median chain; role 3 trục; top groups; closest members; NEW_SIGNATURE nếu backoff.

**WHY-4 — contrastive:** top-3 candidate; Margin_common trên G_common; |G_common| < g_min → INSUFFICIENT CONTRASTIVE EVIDENCE. Contrastive descriptors (ở trên) là ngôn ngữ trả lời chính.

**WHY-5 — suspicious:** WEAK theo gate 4B → REVIEW CANDIDATE (ưu tiên cao nếu kèm s⁻ mạnh); INSUFFICIENT DATA là nhãn riêng.

**WHY-6 — evolution:** mục 7 (drift 3 mức + DATA/CONFIG).

**Prototype & Criticism (P1-optional):** MMD-Critic (prototype + criticism = representative + atypical, không phải root cause/noise); tiền lệ production: Alert Storm ICSE-SEIP 2020 (representative alerts giảm >98% khối lượng review); tie-break severity.

**Auto chain title (P0):** từ top IDENTITY descriptor; fallback Chain ID khi precision thấp.

## 6. Audit Engine — cấu trúc & over-merge

Audit chạy trên multi-channel evidence (K_pair, group-level G*_audit / w*_audit — 4B) — không phải graph Louvain gốc.

**Quy tắc 3 loại graph:** STATISTICAL (full counts, không sparsify) · VISUALIZATION (top-K, chỉ UI) · AUDIT (|C| ≤ ngưỡng ~2k: full graph; lớn hơn: supernode theo hierarchy Region→Site→Device→Family→Instance hoặc sparsifier có guarantee). KHÔNG BAO GIỜ audit trên graph top-K — bridge/weak-cut có thể là artifact của pruning.

**Candidate cut generation — BẢNG TẤT ĐỊNH (v2.3.1, hết "nói bằng lời"):**

```
Entity (categorical)       → partition theo dominant predicate values
                             (nhóm theo reference/device/site value)
Dependency pair graph      → connected components sau ngưỡng θ_dep
                             (union-find trên supported edges)
Failure-domain H_domain    → domain membership sets (mỗi hyperedge
                             là một candidate block)
Descriptor                 → extents của top non-redundant IDENTITY
                             rules
Candidate cuts = các block trên + union/difference của chúng.
KHÔNG dùng thêm community-detection mới (không Louvain lần hai).
```

Với mỗi candidate S, đo **balanced conductance** trên AUDIT graph (w* group-level):

```
Φ(S) = Σ_{i∈S,j∉S} w*_audit,ij / min(Vol(S), Vol(S̄))
ràng buộc: min(|S|,|C\S|) ≥ max(ρ·|C|, 5)
```

"Spectral cut" CHỈ được gọi nếu thật sự implement normalized Laplacian + Fiedler + sweep (optional). Cách candidate-based tự trả lời "cut đến từ đâu": *"Entity đề xuất split A/B; Dependency đồng thuận; Φ = 0.04 < ngưỡng calibrated."*

**Calibration ε_Φ có điều kiện + FALLBACK (v2.3.1 — chống false precision):**

```
if bin(size × density × coverage) có ≥ n_min samples:
    ε_Φ = Q_0.05(Φ | bin)
elif coarser bin (chỉ size) đủ samples:
    ε_Φ = Q_0.05(Φ | size bin)
else:
    global weak baseline (và ghi rõ độ tin thấp)
```

(Vài trăm historical chains chia 3 chiều bin → 3–5 sample/bin → P5 vô nghĩa.) Accepted chains chỉ là weak baseline; bổ sung known over-merged + synthetic hard cases + operator labels.

**Small-chain policy:** |C| < 10 → ràng buộc hai phía ≥5 bất khả thi → skip balanced over-merge test, report "chain quá nhỏ để đánh giá over-merge" — không hiểu "không tìm thấy cut" là "stable".

**Over-merge = MULTI-EVIDENCE VERDICT:** StructuralSeparation (balanced low-Φ cut) + CrossEvidenceAgreement (theo derivation groups) + DescriptorSeparation (block A/B có IDENTITY pattern riêng) + SensitivityStability (cut ổn định qua dải threshold); s⁻ trên cross-block đẩy verdict theo strength × class × quality. Kết luận nêu channel/group drive. Không nói "NocPro sai" — nói "nên review".

**Maintenance & audit:** PLANNED_ACTIVITY annotate + expected-scope comparison ("41/58 inside, 17 outside → review") — KHÔNG suppress (maintenance cũng gây sự cố thật ngoài kế hoạch).

**Morphology — rule tất định:** STAR (1 hub degree ≥ h·(|C|−1), density leaves thấp) · PATH-LIKE (degree ≤2, diameter/|C| cao) · DENSE-BURST (density ≥ d_min, không có balanced cut Φ thấp) · TWO-BLOCK / MULTI-BLOCK (2 / ≥3 community intra cao-inter thấp) · FRAGILE-BRIDGE (∃ balanced cut Φ ≤ φ_max) · CORE-PERIPHERY (k-core đậm + vành đai degree thấp). Threshold trong config + sensitivity.

**Weak member:** label từ rule 3 trục 4B (kèm gate); bảng minh họa X vs median; 4 metric gốc click được. Evidence Strength: bản claim-specific 4 dòng (4B).

## 7. Evolution Engine — chain qua thời gian

Chuỗi P_t, P_{t+1}, ... — đo biến động THẬT trong production.

**Pipeline 6 bước (REASSIGNED SAU lineage):** NEW/CLEARED theo alarm ID → Active_both → lineage bipartite (trên Active_both) → correspondence evolving-chain → RETAINED/REASSIGNED (theo evolving chain, không theo chain ID thô — 123→984 cùng membership là CONTINUE) → events.

**Lineage edge + small-chain exception:**

```
Chuẩn: n_ij ≥ m_min (3) ∧ (containParent ≥ β_p ∨ containChild ≥ β_c)
EXCEPTION: min(|C_i|,|C_j|) < m_min → exact containment/Jaccard rule
Component ≥2 parent ∧ ≥2 children → RECOMBINATION (không ép sạch)
```

**Events + decomposition:** CONTINUE/GROW/SHRINK/SPLIT/MERGE/NEW/DISSOLVE/RECOMBINATION; mọi GROW/SHRINK/CONTINUE kèm 4 dòng `joined_new · joined_reassigned · left_cleared · left_reassigned` (+10 new −10 cleared → Δsize=0 nhưng turnover 20 alarm phải hiển thị).

**ID scheme:** `lineage_component_id` (component của episode DAG — dùng cho Similar Chains dedup) + `branch_id` (nhánh sau split) + `snapshot_chain_id` (ID thô của NocPro). Jaccard giữ làm edge weight + stability; persistence per alarm giữ (0.9 stable / 0.3 boundary).

**Explanation Drift — BA MỨC ĐÚNG TIER (v2.3.1):**

```
TIER-1A BASIC DRIFT (mỗi snapshot — chỉ dùng những gì 1A có):
  membership counts · descriptor changed · coverage/discrimination
  changed · lifecycle events
TIER-1B CACHED DRIFT: roles / evidence composition — CHỈ khi cả hai
  snapshot đã có 1B cache (operator đã từng mở chain; nếu chưa thì
  role cũ không tồn tại để diff)
TIER-2 DEEP DRIFT: over-merge/robustness/similar-incident — chỉ khi
  cả hai snapshot có Tier-2 cache

DATA_DRIFT vs CONFIG_DRIFT: descriptor đổi vì config v17→v18 →
UI nói "explanation changed because analysis configuration changed",
KHÔNG nói "incident behavior changed". (Config version nằm sẵn trong
provenance.)
```

**Flapping (P1-optional, kèm limitation):** alarm active↔clear ≥ x lần/cửa sổ W; chain split↔merge lặp; badge + chu kỳ. Limitation: snapshot 1 phút chỉ thấy snapshot-level oscillation — flapping đầy đủ cần raw lifecycle event stream. Tiền lệ: New Relic `isFlapping`, ServiceNow status flapping, Zabbix hysteresis. Flapping KHÔNG suy ra WEAK.

**Explanation History log (P1-optional):** append-only per evolving chain (timestamp, event kèm 4 dòng decomposition, system rule nếu Gray-box + tóm tắt post-hoc evidence). Positioning: ServiceNow CÓ auto work note ghi lý do gom (`evt_mgmt.alert_groups_reasoning.enable_worknotes`) → ta tương đương + mở rộng (xuyên split/merge, 2 tầng evidence, provenance) — không claim "vượt vì họ không có".

## 8. Tier 2 Deep Dive — phân xử 6 kỹ thuật sâu

Nguyên tắc: kỹ thuật chỉ được nhận khi (1) chạy được với dữ liệu THỰC TẾ, (2) per-chain trong 5–30s, (3) wording không overclaim.

| # | Kỹ thuật | Phán quyết | Dạng được nhận | Tier/P |
|---|---|---|---|---|
| 1 | Counterfactual Clustering | ✅ đổi tên + thuần hóa | Structural Robustness (candidate cuts + balanced Φ) | T2 / P1 |
| 2 | Propagation DAG | ⏸ hoãn có điều kiện | Propagation HYPOTHESIS | T2 / P2 |
| 3 | Historical Motifs | ✅ 2 mức | Similar Chains (P1) → full motif (P2) | T2 / P1 |
| 4 | Shapley | ✅ đổi tên + closed-form | Evidence Coverage Attribution (trên GROUPS) | T2 / P1-opt |
| 5 | Hawkes | 🔄 thay thế | Alarm-type relation graph offline (TempOpt-style) | offline / P2 |
| 6 | KEDB Synthesis | ✅ có điều kiện | Scenario matching + grounded recommendation | T2 / P2 |
| 7 | Blast Radius | ✅ đổi tên | Dependency Scope Overlap | T2 / P2 |

**1. Structural Robustness (P1).** Solver theo mục 6 (candidate table tất định → balanced Φ, ε_Φ conditional + fallback). Gray-box thêm threshold sensitivity. Claims chỉ về evidence graph — không nói "NocPro sẽ tách".

**2. Propagation Hypothesis DAG (P2, sau #3).** Topology có hướng (đúng relation_type) + temporal precedence + RWR; label "PROPAGATION HYPOTHESIS"; Groot/NetRCA là inspiration.

**3. Similar Chains (ưu tiên số 1 Tier 2) — BASELINE SPEC (v2.3.1):**

```
Fingerprint(C) = [ TF-IDF vector trên alarm_family ·
                   TF-IDF vector trên device_type ·
                   top IDENTITY descriptor predicates ·
                   size bin · duration bin ]
Similarity baseline: **cosine similarity** trên fingerprint đã chuẩn hóa
(TF-IDF + one-hot/binned features). Lý do: fingerprint lõi là TF-IDF,
cosine là baseline tự nhiên và deterministic. Weighted Jaccard chỉ là
phương án benchmark thay thế nếu data thật cho kết quả tốt hơn.
Dedup: theo lineage_component_id (exclude cùng evolving incident —
nếu không "chain giống nhất lúc 10:05 = chính nó lúc 10:04").
Mode riêng: "Previous states of this chain".
Nâng cấp graph motif CHỈ sau khi benchmark baseline này.
```

Kèm outcome: ticket? MTTR? cách xử lý? DejaVu/GRLIA là inspiration.

**4. Evidence Coverage Attribution (P1-optional) — TRÊN DERIVATION GROUPS (v2.3.1):**

```
v(S) = |{(i,j): ∃g∈S, b_g(i,j)=1}| / C(|C|,2)   (S ⊆ derivation groups)
φ_g = (1/C(|C|,2)) · Σ_{p: g support p} 1/g_p    (g_p = #groups
                                                  support pair p)
```

Players = DERIVATION GROUPS sau threshold/dedup (mặc định: EXPLAIN_ELIGIBLE groups — BEHAVIORAL gắn nhãn riêng trong waterfall, SYSTEM_FACT không tham gia; nhất quán với eligibility mask 4B), không phải channels — nếu reference sinh 3 channel còn topology 1 channel, chơi trên channel sẽ cho reference ~75% credit chỉ vì representation (artifact). UI drill-down trong group. **Scalability guard:** chain lớn KHÔNG materialize C(20k,2) ≈ 200M pairs — dùng inverted-index counts / sampling / supernode approximation; exact chỉ cho small/medium chain. Wording: "% evidence coverage", không phải "cohesion". Eval: deletion curve. Option: Connectivity Shapley (experimental).

**5. Hawkes → TempOpt-style (P2, offline).** Unsupervised alarm relation learning trên dữ liệu operator thật; topology trong formulation (Eq. 5) chưa benchmark; không claim robust-to-noise. Kết quả đổ vào channel H qua chuẩn reliability × strength.

**6. KEDB Grounded Synthesis (P2, data-gated).** Scenario matching + recommendation kèm evidence; narrative theo handler-per-type (RCACopilot).

**7. Dependency Scope Overlap (P2).** Descendant ≠ expected affected (một interface của AGG switch chỉ ảnh hưởng 8/100 descendants; redundancy làm 70 descendants im lặng). Khi chưa có fault mode: chỉ là overlap signal; chỉ khi có ExpectedAffectedObservable(S, fault mode f, active topology t) mới nâng lên "Blast-Radius Validation".

## 9. Interactive UI — Chain Explanation Workspace

UI là phần chính của sản phẩm, không phải phụ.

```
┌────────────────────────────────────────────────────────────┐
│ DEHL01/DEHT01 · DIAMETER · 22s          (Chain 2214039)    │
│ 58 alarms · Gray-box                                        │
│ [Why grouped?] [Structure] [Evolution] [Deep Dive ≈10s]    │
├───────────────────────────────┬────────────────────────────┤
│ Graph / Timeline              │ WHY PANEL                  │
│                               │ SYSTEM FACT                │
│  DEHL01        DEHT01         │ ✓ 1653 pairs <600s         │
│ ███████       ███████         │ ✓ ref counts 435 / 378     │
│                               │ ✓ 3 rules, merge OR        │
│ layer: T/E/Dep/H/S │ G*       │                            │
│                               │ POST-HOC                   │
│                               │ ✓ two reference blocks     │
│                               │ ✓ event span 22s           │
│                               │                            │
│                               │ DEPENDENCY                 │
│                               │ ⊥ current topoIP unmapped  │
├───────────────────────────────┴────────────────────────────┤
│ Overview│Why│Structure│Members│Evolution│History│Similar   │
└────────────────────────────────────────────────────────────┘
```

**Context-sensitive WHY (giữ):** chain → Why grouped? · alarm → Why here? · edge → Why A–B? · subcluster → Why blocks together? · weak member → Why suspicious? · timeline transition → Why did the chain change? **+ v2.2:** transition có thêm "Why did the EXPLANATION change?" (drift — mục 7).

**Quy ước hiển thị (v2.2):**
- **Supporting / Contradicting hai cột** — operator thấy cả hai phía, không chỉ evidence ủng hộ.
- **Layer switcher + hierarchical zoom:** xem từng layer hoặc G*_explain; structural verdict luôn dùng G*_audit riêng; chain lớn zoom theo Region→Site→Device→Family→Instance (12 sites → click DEHL01 → 18 devices → 58 alarms).
- **Failure-domain hiển thị dạng nhóm:** "17 alarms share SRLG-384" thay vì đống pair edges.
- **Source reliability line:** "Topology evidence HIGH · Source reliability LOW (snapshot 6h old)".
- **Hai màu history:** grouping-history (giải thích) ≠ operational evidence (kiểm định); threshold BEHAVIORAL gắn nhãn.
- **Pair agreement đủ tử số:** "Support 2/2 available · (2/5 possible) · Contradict 1".
- **Role 3 trục:** Membership · Structural · Redundancy — mỗi nhãn click ra metric gốc.
- **Badges:** NEW_SIGNATURE (history family-level only) · FLAPPING (+số chu kỳ) · PLANNED_ACTIVITY (+expected-scope comparison, không suppress audit).
- **Claim-specific strength** trên mỗi kết luận.

**8 UX pattern từ sản phẩm thực tế (giữ, mục 16):** grouping-type badge (ServiceNow) · why-panel + policy link (IBM) · correlation anatomy (Moogsoft) · auto title (BigPanda) · "Show reasoning" (BigPanda) · flapping badge (New Relic) · severity timeline zoom (Moogsoft) · auto work note (ServiceNow).

**Tier-2 async:** "Phân tích sâu (≈10s)" + progress; Tier-1B không bao giờ bị block. **Provenance mọi nơi:** mọi dòng click được → evidence gốc + config version + nhãn nguồn threshold.

## 10. Những thứ cố tình loại khỏi core

Loại khỏi core không phải vì dở, mà vì: không có model access phù hợp · dữ liệu hiện tại không support · latency · dễ overclaim · complexity không tương xứng contribution.

- **GNNExplainer / SubgraphX / InduCE:** cần model (GNN) access — ta không có model, chỉ có input/output.
- **Exact Shapley mức member/feature thô:** tổ hợp nổ; bản mức-view (mục 8.4) đã cho đúng giá trị cần.
- **PC/FCI causal discovery, Granger đầy đủ:** dữ liệu quan sát 1 phút không đủ giả định; nguy cơ claim causality sai rất cao.
- **Hawkes per-chain online:** đã thay bằng TempOpt-style offline (mục 8.5).
- **Rerun Louvain 100 lần / multi-gamma sweep:** không có quyền chạy lại model; Evolution Engine đo biến động THẬT tốt hơn.
- **MST = causal path, Centrality = root cause:** ngụy biện phổ biến, từ chối có chủ đích.
- **LLM làm nguồn reasoning:** LLM chỉ được dùng RENDER natural language từ structured explanation (P2), không bao giờ là nguồn suy luận.

**Adapter policy:** `NocPro Metadata Adapter` (M_chain_rule/M_chain_characteristic/M_attribute_config/exact M_pair nếu có) thuộc MVP/P0 Gray-box. `Louvain Internals Adapter` vẫn là P2/future: chỉ khi lấy được simiDict/A_ij/modularity trace/node movement thật mới enrich bằng exact edge weights/ΔQ; mọi engine phía trên không phải sửa.

## 11. Hiệu năng & thiết kế dữ liệu

**Quy mô mục tiêu (v2.1 — wording chuẩn):** "Initial engineering **stress design target**: 100k active alarms/snapshot. Capacity target cuối lấy từ **production P99 + safety margin** — đo trước khi cam kết." (Nếu P99 thật = 42k thì 100k rất hợp; nếu 180k thì phải nâng.)

**Cấm tuyệt đối O(N²) trên toàn snapshot** — C(100k,2) ≈ 5×10^9 pair.

**Chiến lược tính toán:** equality → hash group-by ~O(N); time → sort + sliding window O(N log N); topology → precomputed index theo relation_type; historical → precomputed offline (episode-deduped); deep graph analysis → chỉ per-chain (Tier 2). Không claim mọi channel đều O(N): invariant là **NO default dense pair scan**; complexity phụ thuộc provider/capability.

**Bounded computation (bắt buộc):** descriptor: rule ≤ 2–3, top-K values, attribute whitelist, chỉ delta chains; contrastive: top-3 candidate qua blocking index; pair detail: on-click. **Phân biệt rõ (v2.1):** bounded top-K chỉ áp cho VISUALIZATION; STATISTICAL tính trên exact indexed/sufficient counts đối với channel available; full/compressed AUDIT graph thuộc Tier 2 theo quy tắc mục 6 (không top-K).

**Mapping tầng (v2.1):** Tier 1A = global indexes + counts + descriptor candidates + lineage + cache (background, 10–30s*); Tier 1B = indexed statistics + local/bounded WHY + Membership/Redundancy khi mở chain, `audit_graph_mode=NOT_COMPUTED` (P95 <5s); Tier 2 = `G*_audit` exact/compressed + STRUCTURAL/deep dive (5–30s). (*hypothesis chờ benchmark.)

**Incremental snapshot indexing — hypothesis cần đo:** thiết kế hỗ trợ delta update (NEW/CLEARED); benefit phụ thuộc overlap thực tế. Việc đo bắt buộc: phân bố J(A_t, A_{t+1}) trên 1–4 tuần production. Median cao (giả thuyết >90%) → incremental giữ 1A ở đáy 10–30s; alarm flood kéo xuống ~50% → cần full-path đủ nhanh dự phòng.

**Reconciliation (thay "rebuild mỗi giờ"):** trigger có điều kiện, configurable — delta count vượt ngưỡng / cache consistency error / snapshot version gap / lịch off-peak.

**Caching:** Tier-1 summaries per chain; Tier-2 results theo (chain fingerprint, snapshot version, config version).


**Data-driven implementation notes (28/08/2026 — không đổi methodology):**
- Alarm export hiện có 8,714 records / 2,824 `chaining_id`; median chain size = 1, khoảng 73% chain là singleton ⇒ singleton là first-class production path, không phải edge case; API/UI phải trả explicit `NOT_APPLICABLE` cho pair/structural operations thay vì biến singleton thành WEAK/ERROR.
- Largest observed chain trong export hiện tại = 1,072 alarms ⇒ system pair coverage không được mặc định full khi upstream có `maxComparePerAlarm=1000`.
- `node_reference` fill ≈98% trong export hiện tại ⇒ Entity/reference là channel thực dụng cho P0.
- CSV có multiline content (26,508 physical lines nhưng 8,714 records) ⇒ ingestion phải dùng CSV parser chuẩn quoting/multiline.
- Có timestamp bẩn (future outlier 2098; một số `end_time < start_time`) ⇒ preserve raw + quality flag, không silently “sửa cho đúng”.
- `cah.chaining_explain` và `is_root_alarm` tồn tại trong schema export nhưng dataset hiện tại không có non-null value ⇒ chuẩn bị adapter SYSTEM_FACT optional, không mock-fill bằng LLM.
- topoIP có `update_time_vipa` ⇒ Source Quality/freshness có thể đo bằng data thật.
- Các số trên là quan sát từ export hiện có, **không phải production P99/capacity commitment**.

**SLO — design objectives, chưa phải cam kết:**

| Hạng mục | Target (hypothesis) | Trần |
|---|---|---|
| Tier 1A snapshot background | 10–30s | 120s (mentor) |
| Tier 1B on chain open | 1–2s | P95 < 5s |
| Tier 2 per chain | 5–15s | 30s |
| Chain cực lớn (>20k) | aggregate/supernode view | không all-pairs |

**Benchmark bắt buộc (v2.1 — thêm dimension, không chỉ N):** hai workload cùng 100k alarm nhưng "100k chains × 1" và "5 chains × 20k" khác hoàn toàn. Ma trận benchmark:

```
N_alarm ∈ {10k, 50k, 100k}
K = #chains · C_max = max chain size · C_p95
#attributes · topology mapping coverage
historical cache hit rate · concurrent UI users
Đo: P50/P95 latency từng API · throughput · MEMORY PEAK
```

**Dữ liệu cần lưu (định hướng schema):** snapshot metadata · alarm records · chain membership per snapshot · evolving-chain identity (lineage) · evidence layer indexes (topology có relation_type) · historical association store (episode-deduped, tách BEHAVIORAL / EXTERNAL_OPERATIONAL) · explanation cache 2 tier · explanation history log · operator feedback · threshold config versioned (kèm nhãn DOMAIN/BEHAVIORAL).

## 12. Explain – Validate – Verify

**EXPLAIN** — trả lời 6 WHY bằng: metadata NocPro (Gray-box) · descriptors · multi-view evidence · contrastive · prototype/criticism · structure · evolution. Nguồn history dùng ở đây: **grouping-history + threshold BEHAVIORAL** — giải thích behavioral consistency, không chứng minh đúng/sai.

**VALIDATE** — kiểm tra chain có phù hợp thực tế không bằng External Operational Evidence **đủ độc lập với chaining**.

```
EXTERNAL OPERATIONAL EVIDENCE / VALIDATION
  topology external (relation_type đúng loại)
  trouble ticket / incident record
  operator label
  maintenance record
  fault injection
```

**D1 independence rule:** external ≠ independent. Một nguồn chỉ được dùng cho validation khi:
`source_kind ∈ {REAL_LIVE, REAL_EXPORT_REPLAY}` + `chaining_usage = CONFIRMED_NOT_USED` + mapping/semantics hợp lệ + `quality_status = PASS`.
`SYNTHETIC_TEST`, `BACKFILL`, `chaining_usage=UNKNOWN/CONFIRMED_USED`, hoặc `quality_status=UNKNOWN/FAIL` ⇒ không validate.
`chaining_usage` được resolve theo source version + chaining configuration/run context, không gắn thô cho cả store.

Không bao giờ dùng grouping-history/threshold BEHAVIORAL để validate NocPro. NocPro `HistorySimilarity`, `TopologySimilarity`, `TimeWindow` nếu được cung cấp qua Gray-box vẫn là SYSTEM_FACT, không phải validation source. Validate nói về CHẤT LƯỢNG CHAIN.

**VERIFY** — kiểm định chính Explanation Module:
1. **Traceability:** mọi evidence trace về raw data; deterministic given (snapshot, config version).
2. **No-overclaim check:** wording Black-box đúng kỷ luật; "Detected" vs "Inferred" đúng chỗ; robustness claims chỉ về evidence graph; attribution gọi đúng tên "evidence coverage", không gọi "cohesion".
3. **Consistency:** topology/timestamp claim hợp lệ với nguồn; alarm→topology mapping fail-closed; capability relation đúng semantics; validation external qua `source_kind + chaining_usage + quality_status`; audit không chạy trên graph top-K và chỉ dùng `audit_eligible` derivation groups trong G*_audit.
4. **Stability:** hai snapshot gần giống nhau không cho explanation dao động vô lý.
5. **Config provenance:** mọi explanation ghi threshold config version + nhãn nguồn (DOMAIN/BEHAVIORAL).
6. **Performance:** đạt SLO mục 11 sau khi benchmark chốt số.

Verify nói về CHẤT LƯỢNG GIẢI THÍCH.

**Nguyên tắc bốn lớp (trục xuyên suốt của toàn hệ):**

```
System Fact ≠ Post-hoc Evidence ≠ Behavior Learned From NocPro
           ≠ External Operational Validation
```

Giữ tách biệt từ DB schema → algorithm → API → UI wording → evaluation.

## 13. Kế hoạch Evaluation

Trả lời trước câu phản biện "làm sao biết explanation đúng?":

| Đối tượng | Metric / cách đánh giá (v2.3.1 FINAL) |
|---|---|
| Chain descriptor | coverage/recall, Precision_global, Precision_local (trên U_local cứng), FPR, lift, F1; redundancy filter hoạt động (không show 2 rule extent trùng ≥0.9); bitmap đối chiếu brute-force mẫu nhỏ |
| Temporal kernel | model-selection bằng holdout log-likelihood/calibration; **directed Δt**: kiểm tra relation A→B không match nhầm B→A; backoff đúng mức |
| Historical association | sanity: `lift≤1` hoặc `support<s_min` phải cho `s_H⁺=0`; episode dedup chống storm inflation; backoff type→family→category đúng mức |
| **Consensus dedup (v2.3)** | sanity: inject nhiều channel cùng derivation `reference` → Agreement_explain chỉ tăng tối đa MỘT derivation-group; Agreement_external chỉ tăng khi xuất hiện thêm external operational derivation-group thật sự |
| **Contrastive fairness (v2.3)** | case alternative chỉ có 1 channel available không được "thắng" nhờ mean cao; |G_common| < g_min → INSUFFICIENT CONTRASTIVE EVIDENCE đúng lúc |
| **Eligibility mask (v2.3.1 FINAL)** | sanity: inject SYSTEM_FACT/BEHAVIORAL support mạnh vào một pair → w*_audit, over-merge verdict và Agreement_external KHÔNG đổi; chỉ Agreement_explain (có nhãn BEHAVIORAL) thay đổi; mẫu số audit = 0 → AUDIT_INSUFFICIENT_DATA, không dựng edge |
| **Data/Integration independence D1** | `SYNTHETIC_TEST/BACKFILL` → validation NO; `REAL_LIVE/REAL_EXPORT_REPLAY` mới được qua gate; `chaining_usage=UNKNOWN/CONFIRMED_USED` hoặc `quality_status=UNKNOWN/FAIL` → KHÔNG tạo validation verdict; usage phải resolve theo source version + chaining config/run context |
| **System Attribute adapter D1** | raw score 2.0 / veto −999999999 giữ nguyên SYSTEM_FACT; không map vào `s_k`; NocPro TimeWindow/HistorySimilarity/TopologySimilarity không collapse vào T/H/Dep của module |
| **System pair availability D1** | missing M_pair mặc định `UNKNOWN→⊥`, không NEUTRAL; `NOT_EVALUATED→⊥`; FULL_PAIR_SPACE chỉ gắn khi có chứng cứ coverage đầy đủ theo characteristic/attribute |
| **Topology mapping/capability D1** | unmapped resource (vd DEHL01/DEHT01 với topoIP hiện tại) → Dep_* = ⊥; undirected adjacency không được bật SHARED_ACTIVE_PATH/dominator; mapping confidence/freshness được trace |
| **Golden 2214039** | detect two reference blocks/candidate cut và separation descriptors; KHÔNG hard-code `overmerge=true` nếu chưa có operator/ticket/fault-injection ground truth |
| **Singleton path** | `|C|=1`: Chain/System Fact/descriptor/evolution vẫn chạy; Pair WHY, pair-Fit, connector, over-merge = NOT_APPLICABLE; singleton không được gắn WEAK chỉ vì pair evidence = ⊥ |
| Behavioral surrogate | P/R/F1 lớp sameChain + PR-AUC, balanced sampling, snapshot chưa train |
| Weak/noise detection | hard negatives + **gating v2.3**: alarm chỉ có Temporal + others UNAVAILABLE phải ra INSUFFICIENT DATA (không phải WEAK); others NEUTRAL mới ra WEAK → Precision@k |
| Over-merge detection | plausible merges → detection rate; **ε_Φ conditional theo size/density/coverage bins (v2.3)**; solver: candidate cuts từ layers được log lại (audit được nguồn cut); small-chain (<10) skip đúng policy |
| Dependency channels | ablation: bật/tắt CommonDependency + failure domain → Precision@k weak-member, detection rate over-merge; Specificity anti-hub: Core router chung nửa mạng không thổi phồng CD |
| Evolution | lifecycle + lineage (split/merge/recombination) synthetic ground truth; REASSIGNED chỉ khi đổi evolving chain; **small-chain lineage exception hoạt động; joined/left decomposition đúng khi Δsize=0 nhưng turnover lớn (v2.3)** |
| Explanation Drift | synthetic descriptor shift → phát hiện đúng thời điểm/loại; **CONFIG_DRIFT: đổi config version không được báo "incident behavior changed" (v2.3)** |
| Contradiction channel | precision của s⁻ flags trên labeled cases; weighting theo source class (ticket > heuristic maintenance) |
| Evidence Coverage Attribution | deletion curve vs random/reverse; closed-form đối chiếu brute-force 2^G mẫu nhỏ |
| Structural robustness | cut tách audit graph + balance + minimality; cut không đổi khi bật/tắt top-K visualization |
| Sensitivity analysis | quét dải toàn bộ threshold (θ_k, D_max, β, m_min, W_T, S_min, r_min, ρ, ε_Φ, λ_H, λ_dep, bandwidth h của T_delay, Specificity params, c_min, g_min): role/over-merge/lineage/margin ổn định qua dải |
| Operational validity | ticket full partition → ARI/NMI; partial → pairwise P/R + B-Cubed + purity/coverage; ticket/operator = weak reference; fault injection gần strong; Dependency Scope Overlap chỉ là signal khi chưa có fault mode |
| UI usefulness | task-based study + questionnaire Hoffman et al. |
| Performance | ma trận mục 11 (N × K × C_max × C_p95 × attributes × concurrency); P50/P95, throughput, memory peak (gồm bitmap store); J(A_t,A_{t+1}) 1–4 tuần |

Bốn trục: algorithmic + system performance + UI/human + robustness của chính giải thích.

## 14. Scope MVP / P0 / P1 / P2

**Nguyên tắc scope:** MVP + P0-complete đã tự đứng thành một đồ án hoàn chỉnh (descriptor, pair/member WHY, weak, evolution, contrastive, burst, structural, performance/UI). **P1-CORE MINIMUM BAR (v2.3.1 — commitment thật khi một người/một kỳ): 3+1 mục.** Mọi thứ khác là stretch — hoàn toàn có thể bỏ mà không làm bài yếu.

**MVP (demo tối thiểu hoàn chỉnh):**
- **Gray-box NocPro Metadata Adapter:** ingest rule/merge/connector-extender/Attribute config/aggregate characteristics và exact `M_pair` nếu upstream có; **không yêu cầu** simiDict/A_ij/ΔQ; render System Fact box
- Descriptor bitmap bounded: IDENTITY descriptors + coverage/precision/FPR/lift
- Pair & Member WHY (Fit_g theo derivation groups — 4B)
- Weak member (gate availability + floor)
- **Singleton first-class path (`|C|=1`):** Chain overview/System Fact/descriptor/evolution vẫn chạy; Pair WHY/pair-based Fit/connector/over-merge = `NOT_APPLICABLE`; không gắn WEAK chỉ vì pair evidence unavailable
- Evolution: lifecycle → lineage bipartite (small-chain exception) → RETAINED/REASSIGNED
- Auto chain title · UI + provenance · Tier-1 cache

**P0-complete (= MVP +):**
- Contrastive top-3 với Margin_common + CONTRASTIVE descriptors
- Multi-channel evidence + layer switcher · contextual burst (cơ bản)
- Basic structural audit on-demand ở Tier 2 (components/bridge, 3-graph rule)
- Joined/left decomposition trong events
- Incremental indexing + đo overlap production · benchmark ma trận + perf

**P1-CORE (minimum bar — 3+1):**
1. **CommonDependency capability engine + Specificity normalized + Shared Failure Domain (H_domain, explain-only):** SHARED_ANCESTOR chỉ khi có directed hierarchy hợp lệ; SHARED_ACTIVE_PATH chỉ khi có active-path semantics; thiếu capability → `⊥ UNAVAILABLE` (không synthetic output để đủ feature)
2. **Over-merge multi-evidence verdict** (candidate-cut table + balanced Φ trên G*_audit + ε_Φ conditional/fallback + small-chain policy + claim-specific strength; reuse derivation/eligibility infrastructure đã có từ MVP/P0)
3. **Similar Chains** (fingerprint baseline spec + dedup lineage_component_id)
4. **Explanation Drift** (Tier-1A basic — rẻ, giá trị riêng)

**P1-OPTIONAL (stretch, mỗi mục tự đứng):**
- Operational Context Layer đầy đủ (annotate + expected-scope)
- Evidence Coverage Attribution (group-level, guard) · Connectivity Shapley (exp.)
- Prototype & criticism · Morphology (rule tất định)
- Full temporal model-selection + local-mass F_r per relation
- Contradiction channel đầy đủ (s⁻ theo nguồn) · Cold-start backoff + NEW_SIGNATURE
- Source Quality display · Hierarchical coarsening UI zoom
- Flapping · Explanation History log · Persistence/stability chi tiết
- Behavioral surrogate · Operator feedback capture · 1B cached drift / robustness threshold-sensitivity

**P2 (extension có điều kiện dữ liệu):**
- KEDB scenario matching + grounded recommendation · Propagation hypothesis DAG
- Dependency Scope Overlap (→ Blast-Radius Validation chỉ khi có fault mode + active topology)
- UNAVOIDABLE_DEPENDENCY (dominator) · Full motif + MTTR · Root-cause candidate
- Ticket alignment / fault injection · Under-merge · TempOpt-style relation graph (offline)
- Rule simulation preview · LLM narrative rendering (chỉ render) · Louvain internals adapter · Calibrated confidence (sau operator labels)

## 15. Contribution, tên đề tài & pitch 30 giây

**Contribution (không claim phát minh clustering hay XAI mới — claim đúng chỗ mạnh):** một **operational framework** giải thích alarm chaining hậu xử lý dưới điều kiện partial observability — hoạt động ở cả Gray-box và Black-box, kết hợp system metadata với multi-view evidence có đặc tả toán học đầy đủ (mục 4A–4B), giải thích ở cấp chain/member/pair, audit cấu trúc, theo dõi evolution trên chuỗi snapshot production thật, thực thi phân tầng 1A/1B/2, hiện thực thành UI tương tác provenance-first chạy được ở quy mô mạng lớn.

**5 điểm contribution:**
1. Multi-level WHY explanation (chain / member / pair / contrastive / structural / temporal)
2. Gray-box + Black-box graceful degradation với kỷ luật wording 4 lớp (System Fact ≠ Post-hoc Evidence ≠ Learned Behavior ≠ External Operational Validation)
3. Dynamic chain evolution explanation với lineage bipartite trên production stream thật
4. Tiered execution: 1A precompute → 1B interactive <5s → Tier-2 deep dive 5–30s
5. Interactive, scalable, provenance-first operator-facing system

**Tên đề tài (chốt, không đưa Louvain vào tên):**
- Tiếng Việt: **"Xây dựng module giải thích tương tác và kiểm định kết quả xâu chuỗi cảnh báo trong NocPro 5"**
- English (SE): *Design and Development of an Interactive Alarm Chain Explanation and Validation Module for NocPro 5*
- English (paper): *A Dual-Mode Gray-Box and Black-Box Framework for Interactive Alarm Chain Explanation and Validation*

**Pitch 30 giây (v2.1 — đã sửa wording "counterfactual" và latency):** "NocPro mỗi phút lấy toàn bộ alarm active và gom thành các chain. Module của em đứng sau quá trình này để giải thích kết quả mà không thay đổi thuật toán chaining. Khi NocPro cung cấp metadata như rule, connector/extender, merge, module chạy Gray-box và kết hợp thông tin đó với phân tích hậu kiểm; khi chỉ có input/output, module chạy Black-box với các bằng chứng hậu kiểm đa kênh: thời gian, resource, topology, lịch sử, ngữ nghĩa — mỗi loại là một lớp evidence riêng có công thức, ngưỡng và nguồn gốc rõ ràng; riêng lớp kiểm định vận hành (ticket, fault injection, topology **được chứng minh không tham gia chaining**) được tách hẳn khỏi phần giải thích để không tự xác nhận vòng tròn. Hệ thống trả lời tương tác: tại sao chain hình thành, tại sao một alarm nằm trong chain, tại sao hai alarm liên quan, alarm nào weak, chain có over-merge không, và chain thay đổi thế nào giữa các chu kỳ một phút. Hệ thống chạy phân tầng: tầng nền precompute 10–30 giây mỗi snapshot, truy xuất tương tác dưới 5 giây, và phân tích sâu on-demand 5–30 giây khi operator bấm — gồm **structural robustness trên evidence graph, attribution theo lớp evidence, so khớp sự cố lịch sử và đối chiếu KEDB**. Tất cả kết luận đều truy vết được về dữ liệu gốc và phiên bản cấu hình đã dùng."

## 16. Tài liệu tham khảo (đã kiểm chứng)

**Ghi chú kiểm chứng:** v2 (27/08): ServiceNow/Cluster-Explorer/TempOpt xác minh lại trực tiếp. v2.2 (27/08): thêm SD-Map, BSD, Leskovec, JNCA 2012, CoNEXT 2010 (2 mục cuối verify trực tiếp bằng nguồn gốc). **"CORIA TNSM 2023": KHÔNG xác minh được — không cite.**

**Papers — nền tảng trực tiếp:**
1. Ofek & Somech, *Explaining Black-Box Clustering Pipelines With Cluster-Explorer*, **PVLDB 18(5):1495–1508, 2025, doi:10.14778/3718057.3718075** (cite bản published). PDF: https://www.vldb.org/pvldb/vol18/p1495-somech.pdf · github.com/analysis-bots/cluster-explorer — objective descriptor mining. Runtime tham chiếu: avg 55.8s/dataset → căn cứ bounded/bitmap mining.
2. Moshkovitz et al., *Explainable k-Means and k-Medians*, ICML 2020 · Frost et al., *ExKMC*, arXiv 2020 — option threshold-tree.
3. Kim, Khanna, Koyejo, *MMD-Critic*, NeurIPS 2016 — prototype & criticism.
4. Koutra et al., *VOG*, SDM 2014 — morphology vocabulary.
5. Zhao et al., *Understanding and Handling Alert Storm*, ICSE-SEIP 2020. https://dl.acm.org/doi/10.1145/3377813.3381363 — representative alerts >98%.
6. Sadler, Greene, Archambault, *Towards explainable community finding*, Applied Network Science 2022 — member explanation.

**Papers — subgroup discovery & graph theory (v2.2):**
7. Atzmueller & Puppe, *SD-Map — A Fast Algorithm for Exhaustive Subgroup Discovery*, PKDD 2006 — **FP-tree based** (không phải bitmap; citation đúng cho dòng SD).
8. Lemmerich, Rohlfs & Atzmueller, *Fast Discovery of Relevant Subgroup Patterns* (**BSD**), FLAIRS 2010 — **vertical bitsets + logical AND** — cơ sở đúng cho bitmap execution của descriptor mining.
9. Leskovec, Lang, Dasgupta, Mahoney, *Statistical Properties of Community Structure in Large Social and Information Networks*, WWW 2008 (bản journal: *Community Structure in Large Networks*, Internet Mathematics, 2009) — nền tảng conductance/NCP. **Chỉ là graph-theoretic foundation — không phải bằng chứng "conductance detect alarm over-merge".**

**Papers — telecom alarm correlation (v2.2, thay CORIA):**
10. *Inference of Network Anomaly Propagation Using Spatio-Temporal Correlation*, Journal of Network and Computer Applications 35(6):1781–1792, 11/2012 — alarm correlation spatial+temporal+topology, suy propagation path (đã verify title/venue/pages).
11. Wang, Srivatsa, Agrawal, Liu, *Spatio-temporal Patterns in Network Events* (Tar), CoNEXT 2010, doi:10.1145/1921168.1921172 — **71–82% event của cùng fault nằm ở node có quan hệ topology** (support trực tiếp cho Dependency view).
12. Li, Yang, Chen, *Alarm reduction and root cause inference based on association mining in communication network*, Frontiers in Computer Science 2023, doi:10.3389/fcomp.2023.1211739 — **>95% alarm cùng propagation trong 1 phút; segmentation threshold thực nghiệm** → căn cứ adaptive temporal (không phải power-law).
13. Fournier-Viger et al., *Discovering Alarm Correlation Rules for Network Fault Management*, AIOps workshop 2020 — dynamic attributed graph + ACOR, topology-aware association (tham khảo cho Historical + Dependency).

**Papers — Tier 2 & mở rộng (giữ):**
14. DejaVu, ESEC/FSE 2022 · 15. GRLIA, ASE 2021 · 16. Groot, ASE 2021 · 17. NetRCA, ICASSP 2022 · 18. Prado-Romero et al., Graph CF Survey, ACM CSUR 2023 · 19. TempOpt, INDICON 2024 (+arXiv 2508.08814; phạm vi claim: topology trong formulation Eq.5 chưa benchmark) · 20. Xu et al., Hawkes-Granger, ICML 2016 · 21. RCACopilot, EuroSys 2024 · 22. Xpert, arXiv 2023 · 23. Liu et al., Alert Suppression Active Learning, arXiv 2023 · 24. Hoffman et al., Metrics for XAI, arXiv 2018.

**Sản phẩm (docs chính thức, giữ v2):**
- IBM CP4AIOps (grouping + side panel + policy link): ibm.com/docs/en/cloud-paks/cloud-pak-aiops
- ServiceNow Event Management — 9 loại grouping + **auto work note ghi lý do gom** (`evt_mgmt.alert_groups_reasoning.enable_worknotes`): servicenow.com/docs Alert-Groups + community xác nhận property
- BigPanda (correlation patterns + auto title + AI Analysis): docs.bigpanda.io
- Moogsoft (Situation Room correlation anatomy): docs.moogsoft.com
- New Relic (Decisions + `isFlapping` + flapping effectiveness): docs.newrelic.com
- Datadog (Event Correlation, config-based): docs.datadoghq.com
- Zabbix (hysteresis): zabbix.com/documentation
