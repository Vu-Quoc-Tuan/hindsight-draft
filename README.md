# Hindsight

Hindsight giải thích, kiểm định và đề xuất cải thiện các alarm chain do NocPro
cung cấp. Hệ thống phân biệt rõ dữ liệu nguồn, bằng chứng hậu kiểm và kết quả do
NocPro quan sát được; nó không giả định rằng evidence hậu kiểm chính là lý do
nội bộ của thuật toán chaining.

## Thành phần

```text
real exports / observed fixtures / synthetic scenarios
                         |
                         v
                   nocpro-mock
              replay + normalization
                         |
                 Input Contract v1
                         |
                         v
              nocpro-chain-explain
       Tier-1 explain -> Tier-2 audit/review
                         |
                 FastAPI + React UI
```

- `nocpro-mock`: đọc export, bảo toàn raw value, normalize sang contract và tạo
  fixture synthetic có provenance rõ ràng. Nó không triển khai Explain/Audit.
- `nocpro-chain-explain`: ingest snapshot, tính evidence/role/descriptor,
  lineage/Evolution, Similar Chains, Structural Audit và Counterfactual Review.
- `services/web`: giao diện React. Dữ liệu phân tích chuẩn phải đến từ Explain
  API; mock UI chỉ phục vụ replay và topology navigation.

## Đọc gì

- [Methodology](nocpro-chain-explain/docs/METHODOLOGY.md): quy tắc evidence,
  công thức và ranh giới diễn giải.
- [Current status](nocpro-chain-explain/docs/CURRENT_STATUS.md): chức năng đã
  implement, mức kiểm chứng và các blocker hiện tại.
- [Data sources](nocpro-chain-explain/docs/DATA_SOURCES.md): nguồn real,
  replay/synthetic, topology, taxonomy và giới hạn dữ liệu.
- [ADR index](nocpro-chain-explain/docs/adr/README.md): 33 quyết định kiến trúc
  và methodology đã được chấp nhận.

## Yêu cầu

- Python 3.12 cho `nocpro-chain-explain`; Python 3.11+ cho `nocpro-mock`.
- `uv`, Node.js 20+, `pnpm`, GNU Make.
- Docker + Docker Compose cho stack Kafka/PostgreSQL và acceptance đầy đủ.

## Chạy local

```bash
make install
make dev
```

| Service | URL | Local mode |
| --- | --- | --- |
| React UI | `http://127.0.0.1:5173` | Vite, proxy `/api` sang port 8000 |
| Explain API | `http://127.0.0.1:8000` | in-memory preset, không Kafka |
| OpenAPI | `http://127.0.0.1:8000/docs` | tài liệu FastAPI sinh tự động |
| Mock UI/API | `http://127.0.0.1:8085` | catalog, replay và topology navigation |

Có thể chạy riêng bằng `make dev-api`, `make dev-web` hoặc `make dev-mock`.

Local mode là đường phát triển nhanh, không tương đương stack đầy đủ:

- không có `DATABASE_URL`, nên không có PostgreSQL coordinator/persistence;
- không consume Kafka;
- auto-seed một snapshot preset;
- không tự tạo historical corpus hoặc production calibration;
- các capability cần lịch sử, taxonomy hoặc persisted artifact có thể trả
  `UNAVAILABLE`.

## Chạy stack container

```bash
make prod
make status
make logs
make down
```

Stack Compose gồm PostgreSQL, migration, Kafka, API, web và mock UI. Producer
replay là profile riêng; việc container đang `Up` chỉ chứng minh process sống,
không chứng minh snapshot đã READY hay một capability đã production-validated.

Các cổng mặc định:

| Service | Port |
| --- | ---: |
| Web | 3000 |
| API | 8000 |
| Mock UI | 8085 |
| Kafka host listener | 9092 |
| PostgreSQL | 5432 |

## Kiểm thử

```bash
make test          # tập kiểm tra phát triển nhanh
make test-full     # toàn bộ pytest + Vitest; không tự bật mọi external E2E
make lint          # frontend lint
```

Các kiểm tra chi tiết:

```bash
cd nocpro-chain-explain
uv run pytest -q
uv run pytest -q tests/spec_sanity

cd services/web
pnpm test
pnpm lint
pnpm build
```

`tests/e2e/run_acceptance.sh` chủ động tạo Docker resources và chạy Chromium;
chỉ chạy khi cần acceptance đầy đủ. Test synthetic hoặc derived replay không
được dùng để tuyên bố production validity.

## Quy tắc an toàn về sự thật

- `READY`: có implementation path, không có nghĩa đã calibration/validation
  trên production.
- `SUPPORT`, `NEUTRAL` và `UNAVAILABLE` là ba trạng thái khác nhau.
- Không chuyển raw NocPro score, TimeWindow, HistorySimilarity hoặc
  TopologySimilarity thành evidence hậu kiểm có semantics khác.
- Không dense-fallback toàn bộ pair space khi exact indexed path không tồn tại.
- LLM chỉ viết narrative dựa trên facts đã kiểm chứng; không tạo score, role,
  audit verdict hoặc recommendation truth.
- Counterfactual là proposal-only; không tự sửa partition của NocPro.

Xem [Current status](nocpro-chain-explain/docs/CURRENT_STATUS.md) trước khi dựa
vào một màn hình hoặc endpoint cụ thể.
