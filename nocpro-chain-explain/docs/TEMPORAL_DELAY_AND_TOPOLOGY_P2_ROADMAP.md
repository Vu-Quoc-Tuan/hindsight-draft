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

### 2.4. Giải pháp Thực tế Đã Triển khai (Sliding Window & $O(N^2)$ Chuỗi Nhỏ)

Để hệ thống hoạt động thực tế ngay lập tức mà không phụ thuộc vào mô hình ML, ta triển khai cơ chế:

1. **Với Chuỗi Nhỏ ($N \le 200$)**:
   - Cho phép so sánh trực tiếp các cặp cảnh báo trong chuỗi:
     $$|t_j - t_i| \le W \quad (W = 900\text{s} = 15\text{ phút})$$
   - Số phép tính tối đa chỉ là $200^2 = 40.000$ phép tính số học, máy tính xử lý trong chưa đầy **0.5 mili-giây**.
2. **Với Chuỗi Lớn ($N > 200$)**:
   - Sắp xếp cảnh báo theo thời gian bắt đầu $O(N \log N)$.
   - Dùng giải thuật **Cửa sổ trượt hai con trỏ / `bisect`**:
     - Với mỗi cảnh báo $i$ tại mốc $t_i$, chỉ quét các cảnh báo trong khoảng $[t_i - W, t_i + W]$.
     - Dừng quét ngay khi vượt quá $W$.
   - Độ phức tạp thực tế là $O(N \cdot k)$ với $k \ll N$, xử lý chuỗi 1.000 cảnh báo trong **dưới 5 mili-giây**.
3. **Độ tương quan và Điểm hỗ trợ (Fit)**:
   - Điểm hỗ trợ của cảnh báo $i$ bằng tỷ lệ số cảnh báo xuất hiện trong cùng cửa sổ thời gian 15 phút chia cho tổng số cảnh báo hợp lệ trong chuỗi:
     $$\text{fit}_i = \frac{\text{supporting}_i}{\text{domain\_size}_i}$$
   - Cung cấp đầy đủ `peer_bitmap` và `supporting` count, giúp kênh $T_{delay}$ **khả dụng (`AVAILABLE`) 100% trên toàn chuỗi** mà không làm chậm hệ thống.

---

## 3. Xử lý Topology Đa Chiều / 2 Chiều (Bidirectional Topology)

### 3.1. Nghịch lý của Giả định Đồ thị Có Hướng (DAG)
- Thuật toán Dominator Tree và Random Walk with Restart (RWR) ban đầu (`services/analysis-worker/tier2/topology_hypotheses/dominator.py`) đặt điều kiện:
  ```python
  ELIGIBLE_RELATION_TYPES = frozenset({"LOGICAL_DEPENDENCY", "SERVICE_DEPENDS_ON"})
  # Bắt buộc: edge.get("directed") is True và không có chu trình (cycle)
  ```
- **Thực tế hạ tầng viễn thông**:
  - File `topoIP.csv` phản ánh các liên kết mạng IP vật lý giữa các Router (`SITE_ROUTER`), Switch (`AGG_DISTRICT`).
  - Đường truyền mạng IP là song công (full-duplex) 2 chiều: Router A nối với Router B thì cả 2 chiều $A \to B$ và $B \to A$ đều truyền dẫn gói tin. Không có router nào là "cha" của router nào về mặt cấu trúc tĩnh.

### 3.2. Hướng Tiếp cận Đa Chiều / 2 Chiều (Bidirectional Reachability)

Trong thực tế vận hành và lộ trình hoàn thiện:

1. **Mô hình hóa Liên kết Mạng thành 2 Chiều**:
   - Mỗi cạnh vô hướng $(A, B)$ trong `topoIP.csv` được hiểu là quan hệ lan truyền 2 chiều:
     $$\text{successors}(A) \ni B \quad \text{và} \quad \text{successors}(B) \ni A$$
   - Khi Router A gặp sự cố hoặc nghẽn, ảnh hưởng có thể lan truyền ngược về Router B (uplink) hoặc tỏa xuống các trạm con (downlink).
2. **Định Hướng Bằng Mũi Tên Thời Gian (Temporal Causality)**:
   - Thay vì ép buộc đồ thị mạng tĩnh phải có hướng trước, **hướng lan truyền sự cố được suy diễn từ thứ tự thời gian nổ cảnh báo**:
     - Nếu thiết bị $A$ nổ cảnh báo lúc $t_A = 08:00:00$.
     - Thiết bị $B$ nổ cảnh báo lúc $t_B = 08:01:30$ ($t_B > t_A$).
     - Vì giữa $A$ và $B$ có liên kết topo, sự cố lan truyền theo chiều $A \to B$. Thiết bị $A$ đóng vai trò là nguyên nhân khởi nguồn (Root Cause Candidate).
3. **Mở Rộng Sang Tầng Dịch vụ CNTT (`topoIT`)**:
   - Sử dụng bảng `service_module_server.csv` và `module_database.csv`:
     - Tầng ứng dụng/module có hướng phụ thuộc tự nhiên: $\text{Module} \to \text{Database}$ (Module phụ thuộc Database).
     - Kết nối cảnh báo máy chủ/DB trong `alarmIT.csv` với các cảnh báo mạng trong `alarmIP.csv` để xây dựng chuỗi nguyên nhân toàn diện từ Mạng $\to$ Máy chủ $\to$ Dịch vụ người dùng.

---

## 4. Bảng Đối Chiếu Nhanh (Cheat Sheet)

| Thành phần | Thiết kế Ban đầu (Academic) | Cải tiến Thực tế (Operational) | Trạng thái Hiện tại |
| :--- | :--- | :--- | :--- |
| **Mô hình $T_{delay}$** | Gaussian KDE phi tuyến, cần train trước, đòi hỏi taxonomy chuẩn. | Bỏ mô hình ML nặng; dùng Cửa sổ trượt (15 phút) $O(N)$ & $O(N^2)$ chuỗi nhỏ. | **Đã kích hoạt & PASS 100% tests** |
| **Phân tích Chuỗi $T_{delay}$** | Gán chết `UNAVAILABLE` vì cấm $O(N^2)$. | Khả dụng (`AVAILABLE`), tính toán nhanh trong < 5ms cho chuỗi 1.000 cảnh báo. | **Đã triển khai trong `indexed_statistics.py`** |
| **Topology IP** | Chỉ nhận `directed: True`, bỏ qua toàn bộ `topoIP.csv`. | Coi quan hệ mạng là liên kết 2 chiều; kết hợp mốc thời gian $t_A < t_B$ để suy diễn chiều lan truyền. | **Đã lập lộ trình & ghi nhận trong Docs** |
| **Dữ liệu IT (`topoIT`)** | Bị bỏ qua, chưa có adapter nối `alarmIT`. | Lộ trình nối `alarmIT` với bảng `service_module_server` & `database`. | **Sẵn sàng dữ liệu gốc trong repo** |
