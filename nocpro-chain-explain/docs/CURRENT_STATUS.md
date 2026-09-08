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
| Real topology navigation | Implemented | Source loader/resolver + recorded Chromium navigation | Navigation không cấp dependency semantics |
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

## Verification gần nhất trong phiên review

Các kiểm tra targeted đã được ghi nhận trước đợt docs consolidation:

- backend targeted config + local Evolution tests: pass;
- frontend Validation/Counterfactual component tests: pass;
- frontend lint: exit 0 nhưng còn warnings;
- browser E2E hiện tại: chưa chạy vì không có browser connection;
- live dev services tại lần kiểm tra cuối: không còn process chạy.

Sau mỗi thay đổi implementation, phải refresh file này từ source/test/runtime;
không copy trạng thái cũ như một khẳng định hiện tại.
