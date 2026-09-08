# Hindsight: Tài Liệu Tích Hợp Giao Diện (UI) & Backend Engine

> **Mục đích:** Tài liệu này ghi lại toàn bộ kết quả kiểm toán kỹ thuật (Technical Audit), phân tích khoảng cách dữ liệu giữa Frontend và Backend, cùng các quyết định thiết kế (Design Decisions) và lộ trình triển khai cụ thể để đưa hệ thống từ trạng thái **"Presentation Shell" (Bản Mockup động)** thành **"Production-Grade Integration" (Tích hợp trung thực 100% với dữ liệu và thuật toán thật)**.

---

## 1. Bối cảnh & Thực trạng Codebase (Audit Findings)

Giao diện người dùng trên nhánh `feat/code_ui` đã hoàn thiện rất tốt về mặt bố cục, màu sắc và độ mượt mà theo phong cách **Viettel Dark NOC**. Tuy nhiên, về mặt tích hợp dữ liệu, UI hiện đang trộn lẫn giữa 3 loại:
1. **Dữ liệu API thật:** `GET /chains` (danh sách chuỗi), `POST /assistant/query` (trợ lý AI), `GET /evolution` (Lineage DAG), `CounterfactualReview` component.
2. **Dữ liệu giả lập / Hard-code:** Biểu đồ mạng SVG, Fiedler vector $\lambda_2$, Conductance $\Phi$, 4 thẻ KPI Review, kịch bản sự cố S100 $\to$ S102 trên Timeline.
3. **Thao tác chỉ chạy Local (RAM trình duyệt):** Phê duyệt / ký duyệt chỉ `setState` và `console.log`; menu chọn Snapshot trên Header chỉ đổi state giao diện chứ chưa nạp snapshot từ PostgreSQL.

---

## 2. Các vấn đề P1 cần khắc phục

### 2.1. `effectiveAnalysis` giả lập tự động (`App.tsx:235`)
- **Hiện tượng:** Khi `analysis` chưa tải xong, chưa chọn chuỗi hoặc API lỗi, UI tự đắp vào một object giả gồm 58 cảnh báo (`ALM-47933128...`), các role cố định (`CORE_ROOT`, `PERIPHERAL`) và support `0.88 / 0.28`.
- **Hệ quả:** Các màn con (WHY, Audit, Review, Evolution) đều nhận dữ liệu giả này, gây hiểu lầm là backend đã phân tích xong.
- **Giải pháp:** Khi đang tải hoặc không có dữ liệu thật, giao diện phải hiển thị trạng thái `Loading...` hoặc `Data Unavailable`, tuyệt đối không tự sinh object giả.

### 2.2. Lỗi Cache State khi chuyển đổi chuỗi (`App.tsx:71`)
- **Hiện tượng:** `analysisState` chỉ cache theo `snapshotKey` mà không kiểm tra `chainId`.
- **Hệ quả:** Khi đổi từ chuỗi A sang chuỗi B trong cùng snapshot, trong lúc chờ API trả về chuỗi B, giao diện vẫn hiển thị dữ liệu của chuỗi A. Nếu tải B thất bại, dữ liệu A bị giữ lại vĩnh viễn dưới nhãn chuỗi B.
- **Giải pháp:** Khóa cache context theo bộ ba `snapshot_id:snapshot_version:chain_id:config_version`.

### 2.3. Các chỉ số tự tính bằng công thức toán nội suy
- **Chains Explorer (`ChainsExplorerView.tsx:10`):** Conductance đang tự tính bằng phép chia lấy dư từ số lượng cảnh báo `0.05 + ((member_count * 7) % 60) / 100`.
- **Multi-Chain Timeline (`MultiChainTimelineView.tsx:36`):** Tọa độ bắt đầu `startOffsetPct`, thời lượng `durationPct`, tốc độ đỉnh `peakRate` (`member_count / 6.2`) và tên thiết bị `DEH-NODE-${idx}` đều là công thức tự sinh.
- **Compare Chains (`CompareChainsView.tsx:324`):** Khẳng định chuỗi A là nguyên nhân gốc của chuỗi B (`delay +1.82s`) bằng một câu văn tĩnh.

---

## 3. Phân tích chi tiết 6 hạng mục còn thiếu & Quyết định thiết kế

### 3.1. Conductance ($\Phi$ - Độ dẫn cắt) trên danh sách Chains Explorer
- **Bản chất toán học & viễn thông:**
  - Conductance $\Phi(S)$ đo lường tỷ lệ liên kết thoát ra ngoài cụm so với thể tích nội bộ.
  - $\Phi$ thấp ($\Phi < 0.1 - 0.2$) là dấu hiệu của **Gom nhầm (Over-merging)**: hai sự cố độc lập xảy ra đồng thời bị thuật toán gom cụm gộp chung thành một chuỗi khổng lồ. Vết cắt có $\Phi$ nhỏ nhất (Cheeger cut) là vị trí vàng để tách chuỗi.
- **Đánh giá nhu cầu:**
  - Trong chi tiết 1 chuỗi: **CỰC KỲ CẦN THIẾT** (Backend **ĐÃ TÍNH** trong `conductance.py`).
  - Trên danh sách tổng 2,824 chuỗi: **KHÔNG CẦN THIẾT**. Tính ma trận Laplacian cho 3,000 chuỗi sẽ làm treo hệ thống và vi phạm ADR-0014/0015 (cấm $O(N^2)$ ở snapshot level).
- **Quyết định & Công sức:**
  - **Quyết định:** Bỏ cột Conductance tự tính trên bảng tổng quan Chains Explorer. Chỉ hiển thị các thông tin cơ bản (`Chain ID`, `Size`, `Title`). Cột phân tích lát cắt sẽ để nhãn `Audit on Demand` (bấm vào mới tính).
  - **Công sức:** ~15 phút (chỉ sửa Frontend).

---

### 3.2. Tọa độ & Thanh Gantt trên Timeline liên chuỗi
- **Bản chất:** Trục thời gian thể hiện khoảng thời gian nổ cảnh báo của các chuỗi sự cố chạy song song, giúp kỹ sư nhận diện bão cảnh báo dồn dập.
- **Đánh giá nhu cầu:** **RẤT CẦN THIẾT** cho giám sát NOC trực quan.
- **Quyết định & Công sức:**
  - **Quyết định:** Backend đã có `canonical_start_time` của từng cảnh báo. Backend chỉ cần bổ sung trả về `start_time = min(alarms)` và `end_time = max(alarms)` cho từng chuỗi. Frontend sẽ đặt thanh Gantt lên thước đo thời gian thật dựa trên 2 mốc này, xóa bỏ hoàn toàn công thức chia lấy dư `% 65`.
  - **Công sức:** ~2 - 3 giờ làm việc (1h Backend + 1.5h Frontend).

---

### 3.3. So sánh 2 chuỗi (Compare Chains) — *Quyết định dứt khoát*
- **Quyết định chính thức:** **ĐỒNG Ý BỎ HOÀN TOÀN CAUSAL CLAIM (Không khẳng định quan hệ nhân quả liên chuỗi).**
- **CÁC NỘI DUNG PHẢI XÓA BỎ:**
  - ❌ `"A is upstream root cause of B"`
  - ❌ `"delay = +1.82s"`
  - ❌ `"shared transit link = DEH-GW01::HundredGigE0/0/0/2"`
- **Lý do:** Dự án Hindsight tập trung giải thích nguyên nhân gốc nội tại bên trong một chuỗi (In-chain Root Cause & Fission). Hệ thống hiện tại **không có contract về Cross-chain Causal Inference**. Không cần nghiên cứu Granger Causality làm phình to phạm vi dự án; đơn giản là **không khẳng định causality**.
- **Quy cách Compare v1 chuẩn (Chỉ dùng dữ liệu thật):**
  - Chain ID (A vs B)
  - Title & Descriptor thật (nếu response có)
  - Member count (Số lượng cảnh báo thật)
  - Trạng thái Singleton (Đơn lẻ hay đa cảnh báo)
  - Mốc thời gian bắt đầu / kết thúc / thời lượng (nếu có)
  - Trạng thái Audit riêng của từng chuỗi nếu đã persisted
  - Bảng so sánh danh sách cảnh báo thật của chuỗi A và chuỗi B.
- **Công sức:** ~30 - 45 phút (chỉ sửa Frontend).

---

### 3.4. Tọa độ (x, y) vẽ biểu đồ mạng động Audit SVG
- **Bản chất:** Tọa độ hiển thị các cảnh báo (nodes) và quan hệ liên kết (edges) trên mặt phẳng 2D sao cho trực quan, không bị đè chữ.
- **Đánh giá nhu cầu:** **CẦN THIẾT** cho màn hình giải thích cấu trúc chuỗi (Audit Structure View).
- **Quy tắc kiến trúc:** Backend KHÔNG BAO GIỜ nên tính tọa độ pixel $(x, y)$. Backend chỉ cần cung cấp danh sách đỉnh $V$ và cạnh $E$ kèm trọng số $w$ (Backend đã có sẵn trong `AuditGraph`). Việc dàn layout là trách nhiệm của Frontend.
- **Giải pháp & Công sức:**
  - **Giải pháp:** Sử dụng thư viện bố trí lực chuẩn `d3-force` trên Frontend. Khi nhận danh sách node và edge thật từ backend, `d3.forceSimulation()` sẽ tự động bung các điểm nốt ra thành đồ thị mạng động theo đúng dữ liệu của chuỗi đang xem.
  - **Công sức:** ~3 - 4 giờ làm việc trên Frontend.

---

### 3.5. Quy trình Ký duyệt (Validation Protocol): Consensus 2/2, SHA-256 Ledger, Rollback 30p
- **Bản chất:** Mô phỏng quy trình ký số 2 người (Shift Lead + Specialist), sổ cái chống giả mạo và tự động hoàn tác cấu hình mạng.
- **Đánh giá nhu cầu:** **KHÔNG CẦN THIẾT VÀ SAI PHẠM VI (Out of Scope)**.
  - Hindsight là hệ thống **AI Phân tích & Hỗ trợ ra quyết định (Explainability & Decision Support)**, KHÔNG PHẢI là hệ thống can thiệp cấu hình mạng (Provisioning / SDN Controller).
  - Hệ thống không có quyền đăng nhập vào Router mạng thật để rollback cấu hình mạng.
- **Quyết định & Công sức:**
  - **Quyết định:** Chuyển màn này về đúng bản chất: **"Ghi nhận phản hồi ca trực (Operator Feedback)"**.
  - Kỹ sư xem phương án tách chuỗi $\to$ Bấm "Đồng ý (APPROVED)" hoặc "Từ chối (REJECTED)" kèm lý do $\to$ Gọi API `POST /api/v1/review-jobs/{job_id}/feedback` đã có sẵn trong backend để lưu vào database làm tư liệu huấn luyện lại AI.
  - Bỏ các nhãn giả lập về SHA-256 Ledger và Rollback SLA 30 phút.
  - **Công sức:** ~1 - 2 giờ làm việc.

---

### 3.6. Chọn Snapshot động từ PostgreSQL trên Header
- **Bản chất:** Cho phép chọn giữa các tập cảnh báo khác nhau (`IP_NETWORK`, `IT_SERVICES`, `ALARM_ONLY`, các mốc ngày khác nhau) trực tiếp từ database.
- **Đánh giá nhu cầu:** **RẤT CẦN THIẾT** để demo đa kịch bản mà không cần khởi động lại dev server.
- **Giải pháp & Công sức:**
  - *Backend:* Bổ sung 2 endpoint đơn giản:
    1. `GET /api/v1/snapshots`: Quét danh sách các snapshot có trong database / fixtures.
    2. `POST /api/v1/snapshots/switch?snapshot_id=...`: Gọi `workspace.ingest_snapshot()` nạp dữ liệu snapshot đó vào bộ nhớ.
  - *Frontend:* Khi bấm chọn trên menu Header $\to$ gọi API switch $\to$ tự động reload lại danh sách chuỗi.
  - **Công sức:** ~2 - 3 giờ làm việc.

---

## 4. Các điểm Backend ĐÃ CÓ cần cắm dây (Quick Wins)

1. **Đường cong Attribution & Chỉ số AUC:**
   - Đọc từ Tier-2 job result (`/jobs/{job_id}`): `primary.auc`, `reverse.auc`, `random.mean_auc`.
   - Xóa bỏ các số hardcode `0.184 / 0.512 / 0.824` trong `AuditStructureView.tsx`.
2. **4 Thẻ KPI trên Recommendations:**
   - Lấy từ `review.result` thật: Đếm số lượng candidate `split / move / remove / merge`, lấy conductance before/after thật từ Pareto solver.
   - Xóa bỏ số hardcode `+0.142 ΔQ` và `99.4% Noise`.
3. **Phân tích Cặp cảnh báo (Pair WHY):**
   - Kích hoạt gọi hàm `api.pairWhy(chainId, alarmA, alarmB)` khi người dùng chọn xem cặp cảnh báo trong `ChainDetailView.tsx`.
4. **Tránh tự bịa số `membership_support`:**
   - Trong `ChainDetailView.tsx:554`, đổi `m.membership_support ?? (isWeak ? 0.28 : 0.88)` thành `m.membership_support != null ? m.membership_support.toFixed(2) : 'N/A'`.
5. **Dọn dẹp Footer:**
   - Ẩn nhãn `STREAM SYNCED` khi trạng thái là `Demo Mode (API Offline)`.

---

## 5. Lộ trình Triển khai (Checklist Ưu Tiên)

- [ ] **Giai đoạn 1: Dọn dẹp & Trung thực hóa dữ liệu (Data Truth Clean-up)**
  - [ ] Xóa bỏ toàn bộ causal claim trong `CompareChainsView.tsx` (`+1.82s`, root cause, transit link).
  - [ ] Bỏ công thức modulo `% 60` tính Conductance trong `ChainsExplorerView.tsx`.
  - [ ] Sửa fallback `membership_support ?? 0.88` thành `N/A` trong `ChainDetailView.tsx`.
  - [ ] Sửa logic cache trong `App.tsx` (kiểm tra cả `chainId` và `snapshotKey`).
- [ ] **Giai đoạn 2: Cắm dây các tính năng Backend đã có sẵn (Wiring)**
  - [ ] Nối `OperatorValidationModal.tsx` vào `api.submitReviewFeedback()`.
  - [ ] Nối 4 thẻ KPI trong `RecommendationsView.tsx` vào kết quả `latestReview`.
  - [ ] Nối các giá trị AUC thật vào `AuditStructureView.tsx`.
  - [ ] Kích hoạt `api.pairWhy` khi chuyển tab Pair trong `ChainDetailView.tsx`.
- [ ] **Giai đoạn 3: Hoàn thiện trực quan hóa (Visualization & Timeline)**
  - [ ] Backend trả về `min_start_time` và `max_start_time` của chuỗi.
  - [ ] Frontend vẽ thanh Gantt Timeline từ mốc thời gian thật.
  - [ ] Frontend dùng `d3-force` dựng đồ thị mạng động từ `AuditGraph` thay cho SVG tĩnh.
- [ ] **Giai đoạn 4: Chuyển đổi Snapshot động (Dynamic Switching)**
  - [ ] Backend thêm endpoint `GET /api/v1/snapshots` và `POST /api/v1/snapshots/switch`.
  - [ ] Frontend kết nối bộ chọn Header để switch snapshot runtime.
