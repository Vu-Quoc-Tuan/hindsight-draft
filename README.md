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

Hindsight áp dụng mô hình **"Infra in Docker, Apps on Host"**: PostgreSQL và Kafka chạy trong Docker (bind an toàn vào `127.0.0.1`), trong khi FastAPI backend, Mock server và React web chạy trực tiếp trên host để hỗ trợ hot-reload/HMR nhanh nhất.

```bash
make install
make dev
```

Lệnh `make dev` sẽ tự động khởi động infra (`make dev-infra`) rồi chạy đồng thời 3 service trên host:

| Service | URL | Chế độ |
| --- | --- | --- |
| Explain Studio | `http://127.0.0.1:5173/` | Vite dev server, proxy `/api` (8000) & `/mock-studio` (8085) |
| Mock Studio | `http://127.0.0.1:5173/mock-studio/` | Unified dev UI (proxied qua Vite từ daemon 8085) |
| Explain API (Internal) | `http://127.0.0.1:8000` | Auto-reload, kết nối PostgreSQL & Kafka, Topology API (`/api/v1/topology/*`) |
| OpenAPI Docs | `http://127.0.0.1:8000/docs` | Swagger/OpenAPI |
| Mock Daemon (Internal) | *Internal port 8085* | Backend xử lý Mock Studio, không truy cập trực tiếp |

- `make dev-infra`: Chỉ khởi động PostgreSQL và Kafka trong Docker (tự động seed topology vào Kafka).
- `make dev-infra-down`: Dừng infra Docker.
- `make dev-no-kafka`: Chế độ offline không cần Docker/Kafka (chạy hoàn toàn in-memory với presets).
- `make publish-topology`: Bắn initial topology (IP và IT) sang topic Kafka `nocpro.topology.v1`.
- Có thể chạy riêng lẻ: `make dev-api`, `make dev-web` hoặc `make dev-mock`.

## Chạy stack container (Production)

Trong production, hệ thống sử dụng **Unified Web Gateway** qua Nginx: **chỉ có cổng 3000 được public ra ngoài**, các service nội bộ (API, PostgreSQL, Kafka) hoàn toàn ẩn sau Docker network. Giao tiếp dữ liệu giữa `nocpro-mock` và `nocpro-chain-explain` hoàn toàn 100% qua Kafka streaming (`nocpro.topology.v1` và `nocpro.snapshot.v1`). HTTP `/mock-studio/` là kênh operator/browser điều khiển trực tiếp Mock Studio và không phải kênh truyền dữ liệu sang Explain; các request legacy direct `/mock-api/` bị chặn 404 hoàn toàn.

```bash
make prod
make status
make logs
make down
```

Các cổng trong Production:

| Service | Cổng Public | Ranh giới an toàn |
| --- | ---: | --- |
| Web Gateway (Nginx) | **3000** | Cổng duy nhất public. Phục vụ Web UI (`/`), proxy API (`/api`), và proxy Mock Studio operator console (`/mock-studio/`) |
| Explain API | *Internal* (8000) | Không public ra host. Chỉ nhận request từ Gateway |
| Mock Studio UI | *Internal* (8085) | Không public trực tiếp ra host. Chỉ nhận request từ Gateway qua `/mock-studio/` |
| PostgreSQL | *Internal* (5432) | Không public ra host. Lưu trữ snapshot, materialized topology graph, audit và feedback |
| Kafka Broker | *Internal* (19092) | Không public ra host. Broker nội bộ điều phối snapshot & topology streaming |
| Topology Seed | *Internal* (Run once) | Container seed publish initial topology graphs sang Kafka lúc khởi động |


> **Lưu ý**: Để truy cập trực tiếp các cổng PostgreSQL (`5432`) hoặc Kafka (`9092`) từ máy dev/test, sử dụng file override: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`.

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
