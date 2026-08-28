# nocpro-mock — Upstream Replay, Normalization & Scenario Simulator

`nocpro-mock` là upstream simulator dành cho `nocpro-chain-explain`.

Nó **không** implement WHY / Fit / Role / Audit / Evolution của hệ Explain và **không** cố clone đầy đủ NocPro/Louvain. Mục tiêu là biến các export/tài liệu hiện có thành input có kiểm soát, deterministic và đúng provenance cho hệ downstream.

## Vai trò chính

```text
REAL EXPORTS / OBSERVED FIXTURES / SYNTHETIC SCENARIOS
                       │
                       ▼
                 nocpro-mock
        ┌──────────────┼───────────────┐
        │ replay       │ normalize     │ scenario injection
        └──────────────┴───────────────┘
                       │
          versioned Input Contract
                       │
                       ▼
             nocpro-chain-explain
```

`nocpro-mock` phải ưu tiên theo thứ tự:

1. **Replay dữ liệu đã quan sát thật**.
2. **Normalize mà không làm mất raw value**.
3. **Giữ Golden fixture bất biến**.
4. **Chỉ synthetic/mock phần thiếu trong scenario riêng**, có `source_kind=SYNTHETIC_TEST`.
5. **Fail closed** khi mapping/semantics không đủ.

## Nguồn hiện đã xác minh

- `alarm_data(1).csv`
  - 8,714 records
  - 96 columns
  - 2,824 `chaining_id`
  - median chain size = 1
  - 2,072 singleton chains ≈ 73.37%
  - max observed chain size = 1,072 (`chaining_id=6907125`)
  - `node_reference` non-null ≈ 98.06%
  - 26,508 physical text lines → CSV có multiline content
  - có dirty timestamps, gồm 2 start-time records năm 2098 và nhiều trường hợp `end_time < start_time`
  - có columns `cah.chaining_explain`, `is_root_alarm`, nhưng export hiện tại không có non-null values ở hai cột này

- `topoIP-8zjkidh613ffzdck7jca5j6bdc.csv`
  - 201,977 relation rows
  - 16 columns
  - ~90.39% source-side `network_class_name = SITE_ROUTER`
  - dạng device-port ↔ device-port
  - có `update_time_vipa` để đo freshness
  - không có `DEHL01`, `DEHT01`, `HLC9102DEA01`, `HHT9603DEA01`
  - không có field xác nhận routing direction / active path / dependency direction

- `BaoCao_Attribute_Louvain_Chaining.docx`
  - NocPro có Attribute types Expression / Algorithm / TimeWindow / HistorySimilarity / TopologySimilarity
  - TimeWindow có veto `-999999999`
  - raw system scores có thể ngoài [0,1], ví dụ 2.0
  - Attribute Engine tạo `simiDict` pair → score vector
  - có TimeWindow early-break và `maxComparePerAlarm=1000`
  - tài liệu không cung cấp exact `A_ij`, ΔQ, node movement

- Golden case `2214039`
  - 58 alarms, 22s
  - 3 rules, merge OR
  - 1653 pair `<600s`
  - 435 pair `node_reference=DEHL01`
  - 378 pair `node_reference=DEHT01`
  - 153 pair same `alarm_name`
  - 72 historical pairs
  - dùng làm **Golden Gray-box / two-block fixture**, không dùng làm ground-truth `overmerge=true`

- `topoIT-*.zip` và `alarm-*.zip`
  - magic bytes là 7z dù extension `.zip`
  - chưa coi full archive schema/content là verified trong bộ docs này
  - hình topology IT quan sát được cho thấy service/application/server/device nhiều tầng, nhưng **không đủ bằng chứng để freeze directed SERVICE dependency**

## Bắt đầu implementation

Đọc theo thứ tự:

1. `IMPLEMENTATION_BRIEF_FOR_AI.md`
2. `docs/01-boundary-and-responsibilities.md`
3. `docs/02-source-data-catalog.md`
4. `docs/03-data-classification-and-provenance.md`
5. `docs/04-canonical-output-model.md`
6. `docs/07-synthetic-augmentation-policy.md`
7. `docs/11-golden-chain-2214039.md`
8. `docs/13-testing.md`

## Không được làm

- Không import code nội bộ của `nocpro-chain-explain`.
- Không normalize raw NocPro score `2.0` hay veto `-999999999` thành `s_k`.
- Không lấy `72 historical pairs` của NocPro làm `H.support`.
- Không coi NocPro TimeWindow là `T_burst` / `T_delay`.
- Không coi NocPro TopologySimilarity là `Dep_hop`.
- Không prefix/fuzzy-map `DEHL01`/`DEHT01` sang topoIP cho có topology.
- Không suy `SHARED_ACTIVE_PATH` từ undirected adjacency.
- Không gắn synthetic data thành real validation.
- Không tự fill `cah.chaining_explain` / `is_root_alarm` bằng LLM.
- Không biến missing system pair metadata thành NEUTRAL.
