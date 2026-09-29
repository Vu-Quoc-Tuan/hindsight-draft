# Các năng lực topology có hướng được tạm gỡ

Ngày rà soát: 2026-09-28; đối chiếu lại số liệu source ngày 2026-09-29. Phạm vi kiểm tra là source và các replay preset trong repo; chưa kiểm chứng một nguồn topology vận hành bên ngoài repo.

## Vì sao gỡ

Tên gọi chính xác là **topology dependency có hướng đã được xác minh**, không
phải causal graph tự học từ chuỗi quan sát. Các tính toán trước đây cần những
quan hệ dependency có hướng đủ semantics/provenance hoặc record active path có
thứ tự. Riêng active path không nhất thiết được biểu diễn bằng causal graph.
Việc thiếu các input đó trong replay thật là lý do hoãn runtime; nó không chứng
minh rằng một causal graph là điều kiện bắt buộc cho toàn bộ Hindsight.

Ba preset thực `real_alarm_20260907_demo`, `real_alarm_ip_demo` và `real_alarm_it_demo` không có cạnh `LOGICAL_DEPENDENCY` có hướng hoặc bản ghi `active_paths`. Preset IP có cạnh `IP_ADJACENCY` vô hướng; preset IT có quan hệ phục vụ điều hướng, chưa được xác nhận là quan hệ phụ thuộc. Các snapshot synthetic temporal có cạnh logic và active path, nhưng không bật điều kiện `p2_eligible`/`VERIFIED_DEPENDENCY` mà Tier-2 P2 yêu cầu.

Bốn bảng topoIT thực được `ITTopologyLoader` chuẩn hóa thành 218.635 cạnh
`SOURCE_RELATION` chưa xác minh dependency; con số này là cạnh sau chuẩn hóa,
không phải tổng số dòng CSV (xem [Data Sources](DATA_SOURCES.md) để biết cách
đếm và số record bị bỏ do thiếu endpoint). Projection IT
`real_alarm_it_demo@5` của Explain có 3.814 node và 5.603 cạnh dưới tên quan hệ
nguồn; đây là vùng hai hop quanh resource
được map, giữ các đường nguồn dài tối đa bốn hop giữa chúng. Các loại gồm
`SERVICE_HAS_MODULE`, `MODULE_HAS_INSTANCE`, `MODULE_LINKS_DATABASE`,
`DATABASE_LINKS_SERVICE`, `DATABASE_LINKS_INSTANCE` và `INSTANCE_LINKS_STORAGE`.
Projection chọn hai hop quanh alarm resources được map; nó không phải toàn bộ
đồ thị topoIT. Không loại cạnh nào được coi là `SERVICE_DEPENDS_ON` hay causal
dependency. Alarm mapping theo field nguồn topoIT được gắn
`STRUCTURED_FIELD_UNIQUE`, không phải `VERIFIED_ALIAS`; trạng thái này không
được resolver `Dep_hop` hoặc explicit failure-domain chấp nhận. Local dev đã
chọn `@5` ngày 2026-09-29; snapshot `@1`–`@4` trong DB không tự được viết lại.
Review Learn có thể học lựa chọn gộp/tách của operator khi có nhãn phù hợp,
nhưng không biến các nhãn đó thành topology dependency đã xác minh hoặc tự bật
lại các module đã gỡ.

Khi chạy trực tiếp một chain có ít nhất hai alarm ở bốn preset trên, cả Dominator, Propagation và Dependency Scope đều trả `UNAVAILABLE`. Hai kênh pairwise `DepUpstreamAncestor` và `DepUpstreamActivePath` cũng đều `UNAVAILABLE` ở ba preset thực. Đây là **thiếu dữ liệu/capability phù hợp**, không phải bằng chứng rằng thuật toán không chạy được với input hợp lệ. Các test synthetic trước đây kiểm tra được phần code đó; chúng không chứng minh nó hữu dụng với dữ liệu vận hành hiện có.

## Phạm vi gỡ và phần giữ lại

| Phần | Input bắt buộc trước đây | Quyết định |
| --- | --- | --- |
| Tier-2 Dominator | Đồ thị dependency có hướng, `p2_eligible=true`, `dependency_semantics=VERIFIED_DEPENDENCY`, provenance và mapping đầy đủ | Gỡ phép tính và đường API/UI của giả thuyết này |
| Tier-2 Propagation RWR | Cùng đồ thị đủ điều kiện, mapping, timestamp, cấu hình và DAG hợp lệ | Gỡ phép tính và đường API/UI của giả thuyết này |
| Tier-2 Dependency Scope | Dominator witness hợp lệ và giới hạn materialization | Gỡ cùng Dominator |
| Pair `DepUpstreamAncestor` | Cạnh `LOGICAL_DEPENDENCY` có hướng, source/version và mapping | Gỡ provider và thống kê indexed tương ứng |
| Pair `DepUpstreamActivePath` | Bản ghi active path có thứ tự, source/version và mapping; **không bắt buộc đồ thị nhân quả** | Gỡ vì nguồn real hiện không có bản ghi này |

`Dep_hop` trên IP adjacency vô hướng, `G*_audit`/conductance trên graph bằng chứng alarm, topology navigation, failure-domain capability và các kênh Entity/Semantic/Temporal/Historical không phụ thuộc vào đồ thị nhân quả và được giữ. Metadata topology đã lưu (`relation_type`, `directed`, `dependency_semantics`, `p2_eligible`, source/version) được giữ như dữ liệu thụ động để không phá hợp đồng ingest/DB và có thể dùng khi đánh giá nguồn mới; không có analyzer P2 nào tiêu thụ chúng sau đợt gỡ này.

Gỡ code cũng gỡ những test chỉ kiểm tra module đã gỡ. Những test bảo vệ `Dep_hop`, Audit vô hướng và ranh giới không suy diễn dependency từ navigation phải còn. Rà AST test trong repo tại thời điểm này không tìm thấy hai hàm test có body giống hệt nhau; không xóa test khác chỉ vì tên hoặc fixture trông giống.

## Khi nào cân nhắc thêm lại

1. **Chứng minh input trước.** Lấy mẫu dữ liệu thực có nguồn, phiên bản và provenance ổn định. Domain expert xác nhận ý nghĩa và chiều của từng loại cạnh dependency; không đổi nhãn `IP_ADJACENCY` hoặc IT `SOURCE_RELATION` thành dependency chỉ dựa vào hình dạng đồ thị. Với active path, cần record đường đi có thứ tự, thời hạn hiệu lực và mapping tới alarm/resource.
2. **Đo khả dụng trên dữ liệu thật.** Báo số chain/pair có đầy đủ mapping, nguồn và thời gian; phân biệt không áp dụng, thiếu dữ liệu và dữ liệu mâu thuẫn. Ít nhất một replay đã kiểm duyệt phải tạo kết quả `AVAILABLE` và có thể truy vết tới record nguồn. Không dùng synthetic pass làm tiêu chí duy nhất.
3. **Khôi phục có chọn lọc từ lịch sử Git.** Phiên bản trước khi gỡ nằm ở commit `4b01e2d4079d3ae8e0838c5ae446dcc43db5082a`. Các module cũ ở `services/analysis-worker/tier2/topology_hypotheses/`, `channels/common_dependency.py` và `channels/dep_upstream_index.py` chỉ là tham chiếu thiết kế; kiểm tra lại contract/config hiện hành trước khi chuyển code. Không khôi phục nguyên API hoặc toàn bộ module nếu chỉ một capability có dữ liệu.
4. **Nối lại từng đường tiêu thụ.** Pair provider phải có cùng kết quả ở evaluator thường và indexed, derivation/provenance/eligibility rõ ràng, và không biến `UNAVAILABLE` thành `NEUTRAL`. Tier-2 cần schema/version API, serializer, cache identity, UI wording và log trạng thái tương ứng. Các giả thuyết có hướng không tự trở thành trọng số Audit, Role hoặc kết luận root cause.
5. **Kiểm định trước khi bật.** Dùng test fail-closed cho sai semantics/source/mapping, test trên replay thực đã kiểm duyệt, rồi đánh giá kết quả với nhãn outcome phù hợp. Ghi version và migration nếu thay đổi API/DB. Chỉ bật tính năng khi nguồn dữ liệu, chất lượng và cách người vận hành dùng kết quả đã được chấp nhận.

Việc gỡ này không khẳng định không bao giờ cần dependency graph. Nó chỉ loại các phép tính chưa có input đủ điều kiện khỏi đường chạy hiện tại; nguồn topology mới có thể thay đổi quyết định đó.
