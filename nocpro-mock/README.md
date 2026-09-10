# NocPro Mock (`nocpro-mock`)

`nocpro-mock` chịu trách nhiệm nạp dữ liệu xuất thô (raw CSV/exports), chuẩn hóa theo **Input Contract v1**, duy trì provenance rõ ràng, cắt lát chuỗi diễn tiến thời gian (Time-Window Sequence Slicer), và xuất bản dữ liệu sang Apache Kafka cho hệ thống giải thích `nocpro-chain-explain`.

> [!IMPORTANT]
> `nocpro-mock` không tự triển khai logic suy luận giải thích (Explain) hay kiểm định cấu trúc (Structural Audit). Mọi tương tác dữ liệu sang `nocpro-chain-explain` đều thông qua **Apache Kafka streaming** thuần túy (`nocpro.topology.v1` và `nocpro.snapshot.v1`).

---

## Kiến trúc thành phần

```text
datasets/raw (alarm_data.csv, alarmIP.csv, alarmIT.csv, topoIP.csv, topoIT/)
                       |
     +-----------------+-----------------+
     |                                   |
     v                                   v
[Loaders & Normalization]        [DatasetIndexer (SQLite)]
 - AlarmCsvLoader                 - Composite SHA-256 Fingerprint
 - TopoIPLoader / TopoITLoader    - Cursor-based Pagination
 - ResourceMapper (IP/IT)         - Facet Aggregation & FTS5
     |                                   |
     +-----------------+-----------------+
                       |
                       v
            [Replay & Sequence Slicer]
             - Sliding Window Slicing (IP & IT)
             - Snapshot Slimming Invariant (nodes=(), edges=())
             - Canonical TopologyRef Attachment
                       |
        +--------------+--------------+
        |                             |
        v                             v
[Kafka Topology Publisher]     [Kafka Snapshot Publisher]
 - Topic: nocpro.topology.v1    - Topic: nocpro.snapshot.v1
 - Zstandard chunking (2MB)     - Zstandard chunking (2MB)
 - Barrier: TOPOLOGY_COMPLETE   - Barrier: SNAPSHOT_COMPLETE
```

### 1. Loaders & Normalization
- **Bảo toàn giá trị gốc (Raw Fidelity)**: Dữ liệu bẩn hoặc sai định dạng được gắn cờ (flagged), không tự ý sửa đổi ngầm.
- **Resource Mapping**:
  - `IP_NETWORK`: Ánh xạ chính xác dựa trên `device_code` và `topoIP.csv` (`PHYSICAL_ADJACENCY`, undirected, không có hướng).
  - `IT_SERVICES`: Ánh xạ fail-closed an toàn; alias mapping chỉ phục vụ tra cứu điều hướng (`SOURCE_RELATION`), không tự thăng hạng thành quan hệ phụ thuộc nghiệp vụ.

### 2. Dataset Indexer (`nocpro_mock.storage.dataset_indexer`)
- Đánh chỉ mục SQLite không phụ thuộc thư viện ngoài (dùng Python standard library `sqlite3`).
- Hỗ trợ phân trang bằng cursor an toàn (`encode_cursor`/`decode_cursor`), tổng hợp facets (`severities`, `mapping_statuses`), và tìm kiếm toàn văn FTS5.
- Composite SHA-256 fingerprinting đảm bảo cache chỉ được tái sử dụng khi file nguồn chưa bị thay đổi.

### 3. Background Job Manager (`nocpro_mock.jobs.job_manager`)
- Điều phối các tác vụ nền (cắt lát sliding sequence, streaming Kafka) qua ThreadPoolExecutor.
- Bắn sự kiện tiến trình real-time qua Server-Sent Events (SSE) `/api/jobs/<job_id>/events`.

### 4. Sequence Slicer (`nocpro_mock.replay.sequence_slicer`)
- Cắt chuỗi snapshot trượt theo cửa sổ thời gian (`window_minutes`, `step_minutes`).
- Hỗ trợ cả hai bộ dữ liệu: `IP_NETWORK` (với `topoIP.csv`) và `IT_SERVICES` (với `topoIT`).
- **Snapshot Slimming Invariant**: Snapshot alarm chỉ mang `topology_ref` (`profile_id`, `topology_version`) và `mappings`, để trống `nodes=()` và `edges=()`. Explain API sẽ hydrate topology từ PostgreSQL materialized graph.

---

## Giao diện Web Mock Studio (Port 8085)

Khởi động server Mock Studio:
```bash
nocpro-mock ui --host 0.0.0.0 --port 8085
```
Trong môi trường production qua Web Gateway Nginx, giao diện được truy cập tại: `http://localhost:3000/mock-studio/`.

### 3 màn hình nghiệp vụ chính:
1. **Dataset & Alarm Explorer (`#screen-explorer`)**:
   - Chọn và duyệt qua các dataset: `alarm_data.csv`, `alarmIP.csv`, `alarmIT.csv`.
   - Bộ lọc chi tiết: Severity, Mapping Status, Start Time, End Time, và ô tìm kiếm FTS5.
   - Drawer xem chi tiết 96 cột thuộc tính thô của alarm.
2. **Source Topology Inspector (`#screen-topology`)**:
   - Hiển thị thông số canonical chính xác tương thích 100% với Kafka payload:
     - **IP Network**: 99,780 nodes, 110,916 edges, 0 aliases.
     - **IT Services**: 128,322 nodes, 218,635 edges, 111,472 aliases.
   - Cây điều hướng phân cấp (Hierarchy Tree Projection) có giới hạn độ sâu và số con.
3. **Sequence Slicer & Kafka Studio (`#screen-studio`)**:
   - Cắt chuỗi snapshot theo tham số cửa sổ thời gian.
   - Chọn snapshot đơn lẻ và publish tức thời sang Kafka (`Publish 1 Snapshot`).
   - Điều khiển stream liên tục có khoảng trễ (Paced Stream) với các nút Pause, Resume, Stop.
   - Console terminal hiển thị log truyền tin thời gian thực.

---

## Dòng lệnh CLI (`nocpro-mock`)

| Lệnh | Mục đích | Ví dụ |
| --- | --- | --- |
| `profile` | Thống kê cấu trúc file CSV thô | `nocpro-mock profile alarm datasets/raw/alarm/alarm_data.csv` |
| `replay` | Sinh snapshot package trực tiếp | `nocpro-mock replay --alarm-csv datasets/raw/alarm/alarm_data.csv --out snapshot.json` |
| `golden` | Xuất snapshot chuẩn Golden 2214039 | `nocpro-mock golden --out golden.json` |
| `topology-tree` | Xuất cây navigation dạng JSON | `nocpro-mock topology-tree --profile IP_NETWORK --max-depth 2` |
| `slice-sequence` | Cắt chuỗi snapshot trượt theo thời gian | `nocpro-mock slice-sequence --output-dir .cache/sequences/seq1 --snapshots 5` |
| `publish-topology` | Bắn toàn bộ topology đồ thị vào Kafka | `nocpro-mock publish-topology --kafka-bootstrap localhost:9092 --profile ALL` |
| `ui` | Chạy Web Studio & API server | `nocpro-mock ui --port 8085` |

---

## Kiểm thử

Chạy toàn bộ test suites của `nocpro-mock`:

```bash
# Chạy các unit test nhanh (235 tests)
pytest -v -m "not realdata"

# Chạy các test yêu cầu file dữ liệu thực tế (17 tests)
pytest -v -m "realdata"

# Chạy kiểm thử Web UI & API endpoints
pytest -v tests/test_ui.py
```
