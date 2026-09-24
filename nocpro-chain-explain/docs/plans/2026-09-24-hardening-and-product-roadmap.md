# Hindsight Hardening and Product Roadmap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read this master document and the relevant child plan completely before implementation.

**Goal:** Sửa toàn bộ các vấn đề trong review ngày 2026-09-24, thống nhất tính mới/cũ của kết quả, chứng minh hiệu năng mở chain đã xử lý, rồi bổ sung truy xuất evidence, cập nhật chủ động và giải thích thay đổi giữa snapshot.

**Architecture:** Giữ deterministic analysis/persisted artifacts là nguồn sự thật; UI và LLM chỉ đọc projection có identity tương thích. Sửa cục bộ các lỗi đã tái hiện trước; chia các cải tiến thành các commit độc lập, có regression test và feature flag khi thay đổi đường vận hành. Không viết lại hệ thống, không duy trì hai engine làm cùng một việc sau chuyển đổi.

**Tech Stack:** Python 3.12, FastAPI/asyncio, SQLAlchemy/Alembic/PostgreSQL, aiokafka, React 19/TypeScript/Vite, pytest/Vitest/Playwright; dependency mới chỉ khi thật sự cần và phải khóa trong lockfile.

## Global Constraints

- Đây là tài liệu kế hoạch, không phải bằng chứng đã implement hoặc nghiệm thu.
- Baseline checkout: `/home/vqt/UET/Project/hindsight`, branch `feat/fix-bugs`, commit `b939e81`. An earlier draft named a different branch; the verified execution checkout is this branch. Repo ứng dụng: `nocpro-chain-explain`; sibling simulator: `nocpro-mock`.
- Mọi đường dẫn tương đối trong các child plan tính từ `nocpro-chain-explain/`, trừ khi ghi rõ root/sibling.
- Không sửa/xóa thay đổi sẵn có của người dùng; kiểm tra `git status` và `git diff` trước mọi task. Nếu HEAD khác baseline, đối chiếu symbol thay vì tin line number.
- **Ngoài phạm vi:** thêm xác thực/phân quyền cho API sửa/reset/calibrate cấu hình, ingest, chọn snapshot, tạo job. Đây là nợ bảo mật đã được người dùng yêu cầu hoãn, không được gọi là production-ready bên ngoài vì bỏ qua nó.
- Giữ `Timeline & Evolution`; không hồi sinh trang Attribute Explorer và standalone Multi-Chain Timeline đã bỏ.
- Giữ All Chains: toàn bộ chain, số sao, lọc sao và sort; không tự thêm lại ô tìm kiếm.
- Không coi adjacency/path là bằng chứng nhân quả hoặc root cause. Không lấy đường UI tự vẽ làm evidence nếu chưa có artifact backend tương ứng.
- Giữ fail-closed, `UNAVAILABLE`/`NOT_EVALUATED`/`NOT_APPLICABLE` khác nhau; không giả AI output bằng deterministic fallback.
- Không sửa test để bỏ identity/fingerprint checks. Không xóa test đỏ chỉ để CI xanh.
- Không restart deployment, migrate database đang dùng, replay Kafka vào topic thật hoặc chạy benchmark có mutation trên dữ liệu người dùng nếu chưa được cho phép. Chỉ dùng acceptance stack riêng.
- Không đưa secrets, raw alarm payload hoặc nguyên prompt vào log/telemetry/tài liệu.
- Các ngưỡng hiệu năng và readiness mới bên dưới là **đề xuất thiết kế để triển khai**, chưa phải số đo/chứng minh từ production.
- Kế hoạch này không tự authorize commit/push/deploy của agent thực hiện. Commit cục bộ theo từng task khi phiên implement được người dùng cho phép; không tự push.

---

## 1. Tài liệu cần đọc và thứ tự thực hiện

| Phần | Tài liệu | Deliverable |
|---|---|---|
| A | [01 — Correctness, identity, quality](2026-09-24-01-correctness-identity-quality.md) | Test baseline, restart, Kafka poison key, cancellation, freshness, điểm sao |
| B | [02 — Evidence and performance](2026-09-24-02-evidence-performance.md) | Evidence drill-down dùng chung, benchmark đọc kết quả đã lưu, traces, tối ưu và lint |
| C | [03 — Live updates and evolution](2026-09-24-03-live-evolution.md) | Event journal/SSE, client refresh thống nhất, snapshot change explanations |
| D | [04 — Acceptance and cleanup](2026-09-24-04-acceptance-cleanup.md) | PostgreSQL/Kafka/browser acceptance, CI, dọn code cũ, rollout/rollback và bàn giao |

Dependency:

```text
A0 baseline ─┬─ A1 restore ─────────┐
            ├─ A2 Kafka ──────────┤
            ├─ A3 executor ───────┼─ A4 identity ─ A5 quality ─ B1 evidence
            └────────────────────┘          └── B2 measurement ─ B3 optimize
                                             └─ C1 journal ─ C2 SSE ─ C3 UI
                                  A5 + B1 ───── C4 evolution
             All changed surfaces ─ D1 integration ─ D2 CI/cleanup ─ D3 rollout
```

Run A tasks before enabling B/C features. A1/A2/A3 có thể phân công độc lập, nhưng A1/A3 cùng sửa `workspace.py` phải ghép tuần tự. A4 là owner của shared identity; các task khác không tự tạo comparator riêng. C1 là owner của migration mới; D1 không tạo migration cạnh tranh.

Mỗi task: viết regression test → xác nhận đỏ vì lý do mong đợi → implement tối thiểu → chạy focused tests → review diff → commit nhỏ (nếu được phép) → ghi kết quả. Chưa đạt gate thì không đánh dấu checkbox complete.

## 2. Coverage của toàn bộ review

| Review/request | Task | Điều kiện đóng |
|---|---|---|
| StoredDeepDiveJob không có audit_artifact | A1 | Restart materializes compatible persisted results, không resubmit vô ích |
| Key Kafka UTF-8 sai không vào DLQ | A2 | DLQ-before-commit; record sau tiếp tục; DLQ failure không commit |
| Cancellation block event loop | A3 | Heartbeat không phải chờ blocking callable; concurrency vẫn bounded sau cancellation |
| Reconciliation chấp nhận Review config cũ | A4 | Cùng compatibility contract khi đọc, chạy lại, persist và cache |
| Thiếu evidence vẫn 4 sao | A5 | Readiness độc lập score; không đủ dữ liệu không vào “Ổn” |
| 4 backend + 1 frontend test đỏ, 5 lint warnings | A0, B3 | Tests xanh, không weakening checks, warning causes xử lý |
| Chain đã chạy xong mở nhanh | B2, B3 | Read-only warm path có p50/p95, không submit job khi mở |
| WHY/Overview/graph dùng cùng evidence | B1 | Cùng evidence ID + identity; path 3–4 hop hiển thị đúng bounds/semantics |
| Snapshot cập nhật động | C1–C3 | Commit trước event; reconnect/reset; REST luôn authoritative |
| Timeline & Evolution có giá trị | C4 | Change facts, comparability, split/merge rõ provenance |
| Code thừa/trùng sau migration | D2 | Consumers chuyển xong mới xóa implementation cũ; giữ thuật toán khác mục đích |
| PostgreSQL/Kafka/browser còn chưa kiểm chứng | D1 | Artifacts kiểm thử thật hoặc ghi BLOCKED rõ lý do |
| Auth deferred | Global constraints, D3 | Ghi nợ bảo mật, không âm thầm implement/claim external production readiness |

## 3. Baseline evidence — không được gọi là kết quả mới

Review trước khi viết plan: backend `1120 passed, 4 failed, 5 skipped, 23 deselected`; frontend `114 passed, 1 failed`; mock `258 passed`; frontend build pass; lint 0 errors/5 warnings. Backend exclusion: `not postgres and not docker and not e2e and not kafka`. Các con số này không thay thế lượt kiểm thử của agent implement.

Bốn backend failures: hai fixture artifact v1 sai shape/fingerprint; một test kỳ vọng v2 dù code tạo v3; một test kỳ vọng giữ cache snapshot trước. Frontend failure: fixture thiếu `identity.chain_id`. Bốn lỗi runtime và vấn đề quality trong review có repro riêng, chưa được khóa đầy đủ bởi suite hiện hành.

## 4. Quyết định thiết kế chung

1. **Không gom mọi thuật toán topology thành một thuật toán bất chấp nghĩa.** Chia sẻ mapping/identity/evidence path; giữ graph layout và directed dependency policy riêng. UI không tự tính lại đường để đưa vào WHY/AI.
2. **Không thêm ranking/causal model mới trong đợt này.** Readiness, evidence provenance, latency và data freshness có giá trị trước.
3. **Đánh giá readiness trước score.** Điểm sao là heuristic grouping robustness, không phải xác suất đúng và không phải confidence của LLM.
4. **Identity envelope dùng chung, fingerprint theo artifact.** Không ép hash Deep Dive phải bằng hash narrative; phần artifact-specific phải được tên hóa và kiểm tra ở đúng adapter.
5. **SSE là invalidation, không phải analysis engine.** Event chỉ báo tài nguyên thay đổi; client đọc lại REST, không tự cộng/trừ counter để tạo nguồn sự thật thứ hai.
6. **Evolution dùng lineage hiện tại.** Không ghép lịch sử chỉ vì trùng chain ID; không re-run analysis khi người dùng đọc diff.
7. **Compatibility có thời hạn rõ.** Legacy artifacts đọc được qua adapter đã xác minh, nhưng missing identity không được mặc định “current”. Sau cutover, xóa parser/cache fallback không còn consumer và không còn dữ liệu hỗ trợ.

## 5. Lệnh chuẩn

Từ `nocpro-chain-explain/` (không copy secrets từ `.env` vào báo cáo):

```bash
PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/python -m pytest -q -m 'not postgres and not docker and not e2e and not kafka' --disable-warnings
```

Tests app có thể load `.env`; unit CI phải đặt `DATABASE_URL=''`, `TEST_DATABASE_URL=''`, `AI_API_KEY=''`, `AI_BASE_URL=''`, `AI_MODEL=''`, `KAFKA_ENABLED=false`, `AUTO_SEED_DEFAULT_SNAPSHOT=false`, `AUTO_CALIBRATE_ON_STARTUP=false` trước khi import app. Không chỉ `unset DATABASE_URL`: dotenv có thể nạp lại. Tests provider tự monkeypatch fake config/transport. Không dùng credentials thật cho unit suite.

Từ `services/web/`:

```bash
pnpm test
pnpm build
pnpm lint
```

Từ `../nocpro-mock/`: `.venv/bin/python -m pytest -q`. Nếu thiếu venv, dùng environment đã được repo hướng dẫn; không tự cài/upgrade toàn hệ thống.

## 6. Research dùng cho thiết kế

- [Python 3.12 asyncio cancellation](https://docs.python.org/3.12/library/asyncio-task.html#task-cancellation): cancellation phải được propagate; hủy coroutine không đồng nghĩa dừng synchronous thread. Áp dụng A3.
- [Python executor shutdown](https://docs.python.org/3.12/library/concurrent.futures.html#concurrent.futures.Executor.shutdown): context manager đợi worker; không đóng pool theo từng async request. Áp dụng A3.
- [Apache Kafka delivery semantics](https://kafka.apache.org/41/design/design/): commit offset và side effects cần xử lý replay/idempotency; không claim exactly-once giữa Kafka và DB chỉ vì có commit. Áp dụng A2/D1.
- [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/): spans theo request/job để phân biệt thời gian queue, DB và compute. Áp dụng B2.
- [MDN SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events): event ID, reconnect, heartbeat; thiết kế một connection/tab, replay/reset có giới hạn. Áp dụng C1–C3.

Các lựa chọn cụ thể về ngưỡng, schema, endpoint và task trong plan là đề xuất cho repo này, không phải nội dung được các nguồn trên chứng nhận.

## 7. Prompt bàn giao cho model thực hiện

```text
Đọc AGENTS.md và docs/plans/2026-09-24-hardening-and-product-roadmap.md,
sau đó đọc trọn child plan của phase đang triển khai. Xác minh HEAD/worktree.
Implement task-by-task theo dependency; không chỉ sửa test để xanh.
Giữ deferred API authorization ngoài scope, giữ Timeline & Evolution và All Chains.
Mỗi task báo files changed, regression proof, command/exit code và remaining limits.
Không tự deploy/migrate/restart stack đang dùng; integration chỉ trong stack riêng.
Không giữ hai implementation sau cutover. Không claim complete nếu runtime gate chưa đạt.
Bắt đầu A0; hoàn tất A trước khi enable B/C. Nếu contract thực tế khác plan, ghi rõ
bằng chứng và cập nhật plan có kiểm soát; không âm thầm bỏ yêu cầu.
```

## 8. Handoff checklist

- [ ] Đã đọc cả master + child plan, xác định scope được phép implement trong phiên mới.
- [ ] Có baseline fresh và không mất user changes.
- [ ] Mỗi lỗi có regression test thực sự tái hiện trước sửa.
- [ ] Mọi feature có API/schema, failure mode, tests và cleanup gate.
- [ ] D1–D3 được chạy hoặc đánh dấu BLOCKED bằng chứng cụ thể; không đổi thành PASS.
- [ ] Báo cáo cuối nêu rõ chưa fix API authorization và các giới hạn production.
