# Current Status

Snapshot tài liệu: **2026-09-08**, branch `feat/code_ui`, bao gồm cả source đang
thay đổi nhưng chưa commit trong worktree. File này mô tả trạng thái quan sát
được; nó không tự biến một capability thành production-ready.

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
| Tier-1B indexed chain analysis, Fit/Role/Descriptor | Implemented | Unit + synthetic; large-chain anti-dense regression | Chỉ đúng trên evidence khả dụng |
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
| Directed P2 topology hypotheses | Implemented cho compatible inputs | Unit + synthetic Docker | Real IP/IT sources hiện không đủ semantics |
| Assistant/Advisor | Bounded read-only tools, grounded rendering và deterministic fallback implemented | Unit/API/UI; fallback acceptance được ghi nhận | Live provider browser acceptance của loop mới chưa được ghi nhận |

Các acceptance count/timing chi tiết cũ không được coi là current run. Git history
và test artifacts là nguồn để truy lại phép đo theo ngày.

## Những điểm UI hiện chưa phản ánh đúng backend

### Chain WHY

`ChainScopeView.tsx` hiện còn nhiều presentation-side derived/default values.
Riêng Temporal Delay:

- `Resolved Pairs` được ước lượng bằng `totalAlarms * 0.586`;
- `Known Delay: 120ms - 450ms` là chuỗi cố định;
- status strip ghi `Available` không dựa trên model availability;
- `PARTIAL` và contribution `+0.065` là cố định;
- mẫu số dùng số alarm thay vì total pair count.

Các giá trị đó không phải output của frozen `T_delay` model và không được dùng
làm evidence. Chain view còn các fallback/ước lượng tương tự cho temporal span,
burst, chassis, historical confidence và topology mapping; cần audit riêng
trước khi coi màn hình là data-truth.

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

Local `make dev` hiện:

- chạy in-memory, không truyền `DATABASE_URL`;
- không tạo repository/coordinator để load historical packages và persist model;
- auto-seed một snapshot preset thay vì verified history;
- không attach authoritative taxonomy source trong normal runtime;
- dùng `calibrated.yaml`, nhưng phần `temporal.delay` vẫn thiếu các trường
  training/fallback mà E2E config có.

Vì vậy Pair WHY phải trả unavailable khi model/taxonomy/relation không tồn tại.
Đồng thời Chain WHY chưa consume Pair/model statistics, nên train thành công
cũng chưa tự sửa các số hardcode trên card.

## Calibration Status & Prerequisites

`config/thresholds/calibrated.yaml` đã được chuẩn hoá với `counterfactual.calibration_status: SYNTHETIC_ONLY`.
Pipeline hiệu chuẩn (`calibrate_thresholds.py`) bảo đảm rằng khi chỉ có `0` snapshots, `0` chains hoặc
dữ liệu hoàn toàn là synthetic, trạng thái hệ thống không thể tự nhận là `PRODUCTION_CALIBRATED`.

Để đạt được `PRODUCTION_CALIBRATED`:
- Cần tối thiểu chuỗi production snapshots liên tục với $\ge 10$ chains và $\ge 10$ samples cho mỗi core parameter;
- Các chain $\ge 10$ và $\le 200$ members được tính conductance thực tế (`MAX_AUDIT_CALIBRATION_MEMBERS = 200`);
- Counterfactual recommendations yêu cầu tập nhãn hiệu chỉnh từ operator (ground truth split/merge/move/remove) trước khi tháo bỏ nhãn `SYNTHETIC_ONLY`.

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

