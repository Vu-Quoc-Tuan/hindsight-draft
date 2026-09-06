# Lộ trình Kỹ thuật: Kênh Trễ Thời Gian ($T_{delay}$) & Xử Lý Topology Đa Chiều (Bidirectional)

Tài liệu này ghi lại chi tiết kiến trúc, nguyên nhân thiết kế, các giải pháp kỹ thuật thực tế đã triển khai và **hướng dẫn lộ trình tương lai** cho 2 bài toán cốt lõi trong hệ thống phân tích chuỗi cảnh báo NocPro:
1. **Kênh trễ thời gian $T_{delay}$**: Từ mô hình Machine Learning / KDE lý thuyết đến giải thuật Cửa sổ trượt (Sliding Window) thực tế.
2. **Quan hệ Topology Đa chiều / 2 chiều (Bidirectional)**: Chuyển đổi từ giả định đồ thị có hướng (DAG) sang mạng viễn thông & CNTT thực tế.

---

## 1. Bản đồ Dữ liệu Đầu vào Thực tế (3 Bộ Dữ Liệu)

Dự án tiếp nhận và vận hành trên 3 nguồn dữ liệu chính từ Viettel / NocPro:

1. **Dữ liệu Cảnh báo (Alarms)**:
   - `nocpro-mock/datasets/raw/alarm/alarmIP.csv` (282 MB): Tập cảnh báo quy mô lớn từ mạng IP và truyền dẫn di động.
   - `nocpro-mock/datasets/raw/alarm/alarmIT.csv` (365 MB): Tập cảnh báo hạ tầng CNTT, dịch vụ phần mềm, máy chủ.
   - `nocpro-mock/datasets/raw/alarm/alarm_data.csv` (10 MB): Tập trích xuất mẫu tích hợp sẵn thời gian bắt đầu (`cah.start_time`), kết thúc (`end_time`), thiết bị (`device_code`), vị trí (`location_code`).
2. **Dữ liệu Topo Mạng IP (`topoIP.csv`)**:
   - `nocpro-mock/datasets/raw/topo/topoIP.csv` (30 MB, hơn 200.000 dòng): Liên kết vật lý và giao diện mạng giữa các thiết bị mạng IP viễn thông (`SITE_ROUTER`, `AGG_DISTRICT`, `GPON_OLT`...). 
   - **Đặc thù kỹ thuật**: Là liên kết mạng ngang hàng, mang tính vô hướng (`directed: False`).
3. **Dữ liệu Topo Hạ tầng CNTT (`topoIT/`)**:
   - `nocpro-mock/datasets/raw/topo/topoIT/`: Gồm 4 bảng liên kết thực thể dịch vụ:
     - `service_module_server.csv` (21 MB): Liên kết giữa Dịch vụ $\leftrightarrow$ Module $\leftrightarrow$ Máy chủ.
     - `database.csv` (0.8 MB): Danh mục cơ sở dữ liệu.
     - `module_database.csv` (1.2 MB): Quan hệ Module truy vấn Database nào.
     - `storage.csv` (1.8 MB): Hạ tầng lưu trữ gắn với máy chủ.

---

## 2. Kênh Trễ Thời Gian ($T_{delay}$)

### 2.1. Thiết kế Mô hình Machine Learning Ban Đầu (Lý thuyết Luận án / Paper)
Trong thiết kế ban đầu (`services/analysis-worker/temporal_delay/model.py`), kênh $T_{delay}$ được mô hình hóa thành một bài toán học máy phi tuyến:
1. **Công thức tích phân mật độ cục bộ**:
   $$s^+(\Delta t) = \frac{P_r(|T - \Delta t| \le h)}{\max_t P_r(|T - t| \le h)}$$
   Hàm mật độ xác suất $P_r$ được ước lượng bằng **Gaussian Kernel Density Estimation (KDE)** hoặc Histogram với băng thông $h$.
2. **Cơ chế hoạt động**:
   - Cần một bộ dữ liệu lịch sử nhiều tháng để học phân phối thời gian trễ giữa từng cặp sự kiện $(E_A, E_B)$.
   - Đóng băng kết quả học máy thành một artifact mô hình: `FrozenDelayModel`.
   - Khi chạy thực tế, ánh xạ cảnh báo qua cây phân cấp `HistoricalTaxonomy` (`alarm_family` $\to$ `alarm_type`) để tra cứu hàm mật độ.

### 2.2. Lý do Tạm thời Bỏ Mô hình ML trong Giai đoạn này
1. **Thiếu tập dữ liệu huấn luyện lịch sử (Training Corpus)**:
   - Dữ liệu hiện có là file xuất tĩnh, chưa có pipeline huấn luyện mô hình trễ riêng biệt cho từng cặp sự kiện viễn thông Viettel.
2. **Chất lượng dữ liệu thực tế (Data Quality)**:
   - Cột `alarm_type_name` trong `alarm_data.csv` bị NULL đa số dòng; cột `alarm_family` không có sẵn trong bảng. Do đó, hàm `HistoricalTaxonomy` không phân giải được danh mục, khiến tra cứu mô hình bị lỗi `TAXONOMY_UNAVAILABLE`.
3. **Điểm nghẽn thuật toán $O(N^2)$**:
   - Mỗi cặp sự kiện có phân phối KDE riêng, không thể gom nhóm chỉ mục tuyến tính $O(N)$. Tác giả cấm $O(N^2)$ trên chuỗi lớn nhưng chưa giải được toán $O(N)$, dẫn đến việc gán cứng `UNAVAILABLE` trên toàn chuỗi.

---

### 2.3. Hướng dẫn Kích hoạt lại Mô hình ML sau này (Khi có đủ Dữ liệu)

Khi dự án được cấp đầy đủ dữ liệu lịch sử và muốn quay lại kích hoạt mô hình ML/KDE, hãy làm theo các bước sau:

1. **Chuẩn bị Dữ liệu Huấn luyện**:
   - Trích xuất lịch sử cảnh báo tối thiểu 3 đến 6 tháng liên tục.
   - Chuẩn hóa cột `alarm_family` (ví dụ: Nguồn điện, Truyền dẫn, Vô tuyến, BSS, Core...) và `alarm_type`.
2. **Chạy Script Huấn luyện Offline**:
   - Module [`temporal_delay/bootstrap.py`](file:///home/vqt/UET/Project/hindsight/nocpro-chain-explain/services/analysis-worker/temporal_delay/bootstrap.py) đã được viết sẵn:
     ```python
     from temporal_delay.bootstrap import train_delay_model
     # Huấn luyện từ danh sách DelayObservation lịch sử
     model = train_delay_model(observations, config)
     # Xuất ra model JSON versioned
     ```
3. **Nạp Mô hình vào Runtime**:
   - Đặt file mô hình vào thư mục cấu hình (ví dụ `config/models/delay_model_v1.json`).
   - Khai báo đường dẫn trong `analysis_config.yaml` tại mục `temporal.delay.model_path`.
   - Kết nối `HistoricalTaxonomy` với bảng tra cứu họ cảnh báo đã chuẩn hóa.

---

### 2.4. Giải pháp Độ gần Thời gian Cục bộ (Symmetric Temporal Proximity Fallback)

Để cung cấp thông tin tương quan thời gian khi chưa có mô hình học máy phân phối trễ:

1. **Bản chất Thuật toán**:
   - Đây là giải pháp **đo độ gần thời gian đối xứng (Symmetric Temporal Proximity)**:
     $$|t_j - t_i| \le W \quad (W = 900\text{s} = 15\text{ phút})$$
   - **Phân biệt ngữ nghĩa**: Khác với kênh $T_{delay}$ có hướng ($A \to B$) dựa trên phân phối xác suất đã học từ lịch sử, Cửa sổ trượt là heuristic đo cụm thời gian đối xứng (nếu $A$ gần $B$ thì $B$ cũng gần $A$). Hai cảnh báo nổ cùng lúc ($t_A = t_B$) được xem là cùng cụm thời gian nhưng không xác định được chiều phụ thuộc.
2. **Khống chế Độ phức tạp ($O(N)$ Bounded)**:
   - Với chuỗi nhỏ ($N \le 200$): Tính toán pairwise trực tiếp, giới hạn trần `max_window_peers = 100`.
   - Với chuỗi lớn ($N > 200$): Sắp xếp cảnh báo $O(N \log N)$, dùng `bisect` tìm khoảng $[t_i - W, t_i + W]$ và chặn trần tối đa 100 peers lân cận. Điều này triệt tiêu hoàn toàn nguy cơ suy biến $O(N^2)$ ngay cả khi gặp bão cảnh báo (alarm storm) tập trung trong cùng một cửa sổ ngắn.
3. **Trạng thái Tích hợp Runtime**:
   - Runtime mặc định (Tier-1B / Audit) tiếp tục duy trì trạng thái fail-closed `UNAVAILABLE` cho $T_{delay}$ chuẩn để bảo vệ tính toàn vẹn của kênh học máy có hướng, chỉ kích hoạt khi được cấu hình rõ ràng tham số cửa sổ trượt hoặc khi có mô hình phân phối trễ chính thức.

---

## 3. Xử lý Topology Mạng Viễn thông và Nguyên tắc Bất biến Nhân quả (ADR Invariants)

### 3.1. Nghịch lý của Giả định Đồ thị Có Hướng Tĩnh (DAG)
- Thuật toán Dominator Tree và Random Walk with Restart (RWR) ban đầu (`services/analysis-worker/tier2/topology_hypotheses/dominator.py`) yêu cầu:
  ```python
  ELIGIBLE_RELATION_TYPES = frozenset({"LOGICAL_DEPENDENCY", "SERVICE_DEPENDS_ON"})
  # Bắt buộc: edge.get("directed") is True và không có chu trình (cycle)
  ```
- **Thực tế hạ tầng viễn thông**:
  - File `topoIP.csv` phản ánh liên kết mạng IP vật lý giữa các Router (`SITE_ROUTER`) và Switch (`AGG_DISTRICT`).
  - Đường truyền mạng IP là song công (full-duplex): Router A nối với Router B là liên kết 2 chiều. Bản thân topo IP vật lý là đồ thị vô hướng, không thể tự gán nhãn "cha/con" tĩnh.

### 3.2. Nguyên tắc Bất biến về Nhân quả và Hướng Lan truyền (ADR Compliance)

Để đảm bảo tính chính xác và tuân thủ các quyết định kiến trúc đã đóng băng (ADR):

1. **Thứ tự thời gian KHÔNG đồng nghĩa với quan hệ nhân quả (`Temporal Order ≠ Causality`)**:
   > [!WARNING]
   > Thiết bị $A$ nổ cảnh báo trước $B$ ($t_A < t_B$) và có liên kết topo với $B$ **TUYỆT ĐỐI KHÔNG ĐỦ** để kết luận $A$ gây ra $B$ hay $A$ là Root Cause.
   > Trong mạng thực tế: Một trạm con mất nguồn hoặc mất cáp quang nhánh có thể phát hiện sự cố và gửi cảnh báo về máy chủ trước khi Router trung tâm ghi nhận timeout phiên BGP. Nếu vội vã suy diễn $t_A < t_B$ thành nguyên nhân gốc sẽ dẫn đến kết luận sai lệch nghiêm trọng trong vận hành NOC.
2. **Liên kết IP vô hướng KHÔNG PHẢI là quan hệ phụ thuộc (`IP Adjacency ≠ Operational Dependency`)**:
   - Hai thiết bị kề nhau về mặt IP vật lý chỉ mang tính chất **gợi ý tương quan không gian (Spatial Correlation Hint)**, không chứng minh được sự cố lan truyền theo hướng nào nếu không có luồng định tuyến (routing path) hoặc cấu hình dịch vụ cụ thể.
3. **Lộ trình Kích hoạt P2 Propagation Chuẩn mực**:
   - **Tầng Dịch vụ CNTT (`topoIT`)**: Sử dụng bảng `service_module_server.csv` và `module_database.csv` nơi có quan hệ phụ thuộc có hướng tự nhiên ($\text{Module} \to \text{Database}$).
   - **Ánh xạ Dịch vụ Viễn thông**: Bổ sung bảng ánh xạ luồng dịch vụ (Service Tree / E2E Circuit) có hướng rõ ràng giữa trạm phát sóng $\to$ mạng truyền dẫn $\to$ mạng lõi (Core Network). Khi có đồ thị phụ thuộc nghiệp vụ có hướng này, các thuật toán Dominator Tree và P2 Blast Radius mới có cơ sở toán học vững chắc để xác định Root Cause.

---

## 4. Bảng Đối Chiếu Nhanh (Cheat Sheet)

| Thành phần | Thiết kế Ban đầu (Academic) | Heuristic / Trạng thái Hiện tại | Yêu cầu để Kích hoạt Chuẩn mực |
| :--- | :--- | :--- | :--- |
| **Kênh $T_{delay}$ có hướng** | Mô hình xác suất KDE/Histogram có hướng ($A \to B$). | `UNAVAILABLE` trong Tier-1B runtime mặc định. | Cần tập dữ liệu lịch sử chuẩn hóa (`HistoricalTaxonomy`) để huấn luyện mô hình phân phối trễ đóng băng. |
| **Temporal Proximity** | Không có (chỉ có $T_{burst}$ hoặc $T_{delay}$). | Cửa sổ trượt đối xứng ($|t_j - t_i| \le W$), chặn trần 100 peers. | Cung cấp độ gần thời gian đối xứng cục bộ; phân biệt rõ với mô hình trễ có hướng. |
| **Topology IP** | Chỉ nhận `directed: True`, bỏ qua toàn bộ `topoIP.csv`. | Giữ vô hướng; coi là tương quan không gian (spatial hint). | Không suy diễn $t_A < t_B$ thành Root Cause; cần đồ thị phụ thuộc dịch vụ (Service Graph) có hướng. |
| **Dữ liệu IT (`topoIT`)** | Bị bỏ qua, chưa có adapter nối `alarmIT`. | Đã có dữ liệu gốc trong repo (`service_module_server.csv`). | Viết adapter chuẩn hóa quan hệ $\text{Module} \to \text{DB}$ để làm đồ thị phụ thuộc DAG chuẩn. |
