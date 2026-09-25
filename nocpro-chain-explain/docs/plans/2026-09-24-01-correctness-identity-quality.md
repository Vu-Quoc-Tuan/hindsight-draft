# Correctness, Identity and Quality — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking. Read the master plan first.

**Goal:** Đóng năm finding review mà không làm yếu evidence gates và thống nhất semantics cho consumers.

**Architecture:** Sửa adapters tại boundary RAM/persistence và Kafka; chuyển blocking work sang pool có lifecycle; dùng một identity comparator thuần, adapters theo artifact; readiness gate đứng trước công thức sao.

**Tech Stack:** Python 3.12/asyncio/FastAPI, pytest, React/TypeScript/Vitest.

## Global Constraints

Áp dụng toàn bộ Global Constraints của [master](2026-09-24-hardening-and-product-roadmap.md). Chỉ thêm module nhỏ theo responsibility; không tách toàn bộ `workspace.py`/`routes.py` trong một commit refactor lớn.

## Task 0: A0 — Khóa baseline và sửa test expectations đã lỗi thời

**Files:** modify `tests/test_api.py`, `tests/test_audit_artifact.py`, `tests/test_tier2_jobs.py`, `tests/test_tier1b_cache_wiring.py`, `services/web/src/components/ExplainClarityComparisonModal.test.tsx`.

**Interfaces:** Không thay public API. Chỉ fixture/contracts; validation production giữ nguyên.

- [ ] Chạy suite theo master; lưu command, HEAD, failures; không mặc định số test giống baseline.
- [ ] Sửa fixture v1 bằng cách bỏ cả `visualization` và `topology_version` trước hash; giữ negative test sửa payload sau hash bị từ chối:

```python
payload["artifact_version"] = "review-audit-v1"
for key in ("visualization", "topology_version", "artifact_fingerprint"):
    payload.pop(key, None)
encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
payload["artifact_fingerprint"] = sha256(encoded.encode()).hexdigest()
```

- [ ] Test default worker dùng `AUDIT_ARTIFACT_VERSION` từ `tier2.audit_artifact`; vẫn assert exact mode, artifact identity và listener chỉ nhận một artifact.
- [ ] Test snapshot version collision giữ `first is not second`/2 calls; assert cache hiện hành chỉ chứa version đang active nếu đó vẫn là policy được `activate_snapshot` triển khai. Thêm test quay về snapshot cũ không dùng kết quả sai version; không chỉ xóa assertion.
- [ ] Frontend fixture thêm `identity.chain_id` đúng chain. Thêm fixture khác chain và assert bị reject (không hiện nút/đề xuất của chain khác).
- [ ] Chạy:

```bash
PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/python -m pytest -q tests/test_api.py tests/test_audit_artifact.py tests/test_tier2_jobs.py tests/test_tier1b_cache_wiring.py
```

Từ `services/web`: `pnpm test -- src/components/ExplainClarityComparisonModal.test.tsx`. Expected 0 failures; nếu còn lỗi runtime phải báo, không sửa expectations cho phù hợp lỗi.

- [ ] Commit boundary: `test: align artifact and identity fixtures with current contracts`.

## Task 1: A1 — Khôi phục persisted Deep Dive/Audit an toàn

**Files:** modify `services/api/nocpro_api/workspace.py` (`_materialize_chain_quality`, `_materialize_persisted_chain_quality_if_available`); inspect `persistence/repository.py:StoredDeepDiveJob`, `cohesion_advisor.py:extract_cohesion_context`; extend `tests/test_automatic_quality_pipeline.py`.

**Consumes:** Review view compatible theo snapshot/config/topology; `latest_deep_dive` và `latest_audit_visualization` hiện tại.
**Produces:** Một quality assessment/projection current từ persisted artifacts; không chạy lại Deep Dive nếu đã có compatible success.

- [ ] Viết test dùng **actual StoredDeepDiveJob**, không fake có sẵn `audit_artifact`. Giả lập restart: job managers rỗng, DB chứa Deep Dive/Review successful, quality row thiếu, Audit compatible lưu riêng. Assert materialization ghi đúng một quality row, không submit job.
- [ ] Viết thêm: thiếu Audit → explicit no-data; Audit khác config/topology → không dùng; Deep Dive FAILED → không treat completed; gọi reconciliation lần hai → không duplicate.
- [ ] Run test mới trước sửa, expected AttributeError tại direct access.
- [ ] Thay direct attribute access; giữ exact-compatible fallback, không gọi audit “latest” không identity:

```python
deep_dive_analysis = deep_dive_view.result if deep_dive_view is not None else None
audit_artifact = getattr(deep_dive_view, "audit_artifact", None)
if audit_artifact is None and self.repository is not None:
    audit_lookup = await self.latest_audit_visualization(chain_id)
    audit_artifact = audit_lookup.audit_artifact
```

Đây là success-path fragment: giữ phân biệt repository error và no-compatible-artifact trong code xung quanh. Không nuốt mọi DB outage như “P2 chưa chạy”; không persist terminal UNAVAILABLE vì transient DB failure. `extract_cohesion_context` đã hydrate dict qua `hydrate_persisted_deep_dive`; không thêm hydrator thứ hai.

- [ ] Trong test persist callback, assert identity trước/sau await không đổi; nếu snapshot/config đổi giữa lookup và persist, bỏ publication cũ và để scheduler chạy identity mới.
- [ ] Run `pytest -q tests/test_automatic_quality_pipeline.py tests/test_cohesion_narrative.py` với PYTHONPATH master. Expected 0 failures, no `AttributeError`.
- [ ] Commit: `fix: restore quality from compatible persisted artifacts`.

## Task 2: A2 — Kafka poison key, DLQ và replay

**Files:** modify `services/api/nocpro_api/kafka_topology_consumer.py`; inspect `kafka_consumer.py`; extend `tests/test_kafka_topology_consumer.py` (reuse `_service`, `_message`).

**Consumes:** raw Kafka key/value + topic/partition/offset.
**Produces:** Valid event processed/deduplicated then offset committed, hoặc invalid event DLQ acknowledged rồi commit. Transient failure không commit.

- [ ] Thêm test executable tối thiểu:

```python
def test_invalid_utf8_key_routes_to_dlq_before_commit():
    service, consumer, dlq = _service()
    asyncio.run(service.process_message(_message(b"\xff", b"{}")))
    assert len(dlq.messages) == 1
    assert len(consumer.commits) == 1
```

Thêm fake recording ordered actions, assert `send_ack` trước `commit`; DLQ send raise → commits rỗng. Raw key diagnostic dùng replacement/base64 có giới hạn, không lỗi decode lần hai.

- [ ] Run test mới, expected UnicodeDecodeError trước sửa.
- [ ] Decode có nhánh fail-closed trước parse payload:

```python
try:
    key_str = message.key.decode("utf-8") if message.key else None
except UnicodeDecodeError:
    await self._publish_dlq(message, "Invalid UTF-8 message key")
    await self._commit(message)
    return
```

- [ ] Kiểm tra consumer sibling chỉ sửa cùng class lỗi nếu có repro; không refactor cả Kafka transport. Giữ transient backoff/cancellation propagation.
- [ ] Test batch có poison record + record hợp lệ sau nó; duplicate/replay sau DB commit-before-offset không duplicate topology. Test DLQ outage recovery và stop consumer không nuốt CancelledError.
- [ ] Run `pytest -q tests/test_kafka_topology_consumer.py`. Kafka thật/restart nằm D1, unit pass không chứng minh delivery end-to-end.
- [ ] Commit: `fix: dead-letter invalid topology message keys safely`.

## Task 3: A3 — Bounded offload, cancellation-safe lifecycle

**Files:** create `services/api/nocpro_api/blocking_work.py`, `tests/test_blocking_work.py`; modify `routes.py:_run_grounded_provider/_run_blocking`, `workspace.py:_compute_snapshot_offloaded/close`, `app.py:lifespan`; inspect `grounded_llm.py` transport timeouts.

**Public contract (new):**

```python
class BlockingWorkBusy(RuntimeError):
    pass

class BlockingWorkClosed(RuntimeError):
    pass

# Implement in blocking_work.py, annotate generically with TypeVar T.
# BlockingWorkPool(max_workers: int, max_outstanding: int)
# async run(function, /, *args, admission_timeout: float = 0.25, **kwargs) -> T
# async aclose(grace_seconds: float = 5.0) -> None
```

Owner: một pool API reads + một pool provider theo Workspace/app lifespan, không pool/request. Defaults proposed: reads 4 workers/8 outstanding, provider 2 workers/4 outstanding; env `NOCPRO_READ_WORKERS`, `NOCPRO_READ_MAX_OUTSTANDING`, `NOCPRO_PROVIDER_WORKERS`, `NOCPRO_PROVIDER_MAX_OUTSTANDING`. Validate positive + outstanding >= workers. Worker compute pool hiện có không bị thay tùy tiện.

- [ ] Test dùng `threading.Event` để giữ worker, không phụ thuộc race sleep: task đã vào worker → cancel coroutine → heartbeat và cancelled task hoàn tất **trước** release worker. Finally luôn release để test không treo.
- [ ] Test concurrency với max_workers=1/outstanding=1: cancel caller trong khi callable vẫn chạy; second admission bị `BlockingWorkBusy`, không mở thêm slot. Worker xong mới release slot. Test exception propagation, close/reject new work và ContextVar propagation.
- [ ] Implement algorithm trong `run`: acquire bounded admission → `copy_context().run` trong executor submit → giữ concurrent future trong registry → completion callback schedule slot release bằng `loop.call_soon_threadsafe` → await wrapped future có shield. Khi caller cancel: propagate; không synchronous shutdown và không release capacity sớm. Nếu submit fail, release ngay. Callback sau loop close không crash/log secrets.

```python
# Core waiting rule; executor and admission live on the pool, not this request.
future = executor.submit(contextvars.copy_context().run, call)
# Register completion callback BEFORE waiting; callback owns capacity release.
return await asyncio.shield(asyncio.wrap_future(future))
```

- [ ] `aclose`: reject submissions, cancel chưa start, async wait bounded grace, `shutdown(wait=False, cancel_futures=True)`; document Python threads cannot be force-killed. Provider socket timeouts vẫn bắt buộc; CPU workload không có hard kill guarantee.
- [ ] Route Busy → controlled 503 + `Retry-After`, giữ error contract; timeout provider trả trạng thái explicit hiện có, không dùng fallback AI prose. Không giữ global workspace mutation lock quanh provider network I/O.
- [ ] Workspace tests không chạy FastAPI lifespan phải close pool qua owner API; tránh dùng pool asyncio-bound qua nhiều `asyncio.run` loops. Pool instantiated lazily per owner loop; phát hiện cross-loop reuse thay vì silent corruption.
- [ ] Run `pytest -q tests/test_blocking_work.py tests/test_grounded_llm.py tests/test_api.py`. Thêm ASGI cancellation test + D1 health probe concurrent slow provider stub.
- [ ] Xóa hai per-request executor implementations sau khi tất cả call sites chuyển sang pool; giữ một wrapper mỏng nếu phục vụ import compatibility, không giữ execution logic cũ.
- [ ] Commit: `fix: bound blocking work without blocking request cancellation`.

## Task 4: A4 — Shared analysis identity và freshness end-to-end

**Files:** create `libs/contracts/analysis_identity.py`, `tests/test_analysis_identity.py`, `services/web/src/analysisIdentity.ts`, `services/web/src/analysisIdentity.test.ts`; modify `quality_freshness.py`, `workspace.py`, `quality_background.py`, `routes.py`, `schemas.py`, `services/analysis-worker/tier2/counterfactual/jobs.py` only at adapters if necessary; frontend `types.ts`, `reviewJobCache.ts`, `CounterfactualReview.tsx`, `App.tsx`, `api.ts`; tests `test_quality_freshness.py`, `test_automatic_quality_pipeline.py`, `CounterfactualReview.test.tsx`; create `reviewJobCache.test.ts` if absent.

**Dependency:** A1/A3 merged. No import from libs into API-specific constants; shared module must not import `cohesion_advisor`.

**New shared envelope:** immutable dataclass, explicit `identity_version='analysis-identity-v1'`:

```python
@dataclass(frozen=True)
class AnalysisIdentity:
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    topology_version: str | None
    analysis_config_version: str
    review_config_version: str | None
    pipeline_version: str
    input_fingerprint: str
```

`topology_version=None` trong valid envelope nghĩa confirmed no topology, không nghĩa unknown. Unknown/legacy thiếu field → adapter trả `IDENTITY_INCOMPLETE`, không tạo valid envelope. `input_fingerprint` là canonical chain/source fingerprint hiện có, không hash toàn snapshot trong mỗi GET. Các artifact vẫn giữ artifact-specific cache/audit/narrative fingerprint; không rename ReviewIdentity hiện tại một cách phá dữ liệu cũ.

**Comparator:** `identity_mismatch(actual: AnalysisIdentity, expected: AnalysisIdentity) -> str | None`; compare từng field theo thứ tự snapshot ID/version, chain, topology, analysis config, review config, pipeline, input fingerprint. Reason enum strings `SNAPSHOT_MISMATCH`, `VERSION_MISMATCH`, `CHAIN_MISMATCH`, `TOPOLOGY_MISMATCH`, `CONFIG_MISMATCH`, `REVIEW_CONFIG_MISMATCH`, `PIPELINE_STALE`, `FINGERPRINT_MISMATCH`.

- [ ] Viết parameterized tests thay từng field; cùng topology nhưng config cũ phải mismatch; None vs version phải mismatch; missing fields must never match. JSON round-trip giữ strings, không coerce snapshot version thành number.
- [ ] Repro scheduler: repository chưa có current quality, current Deep Dive SUCCEEDED, Review SUCCEEDED old analysis/review config. Assert submit Review mới một lần; lần sau current queued → không submit duplicate. Test cả topology/config đổi giữa await.
- [ ] Derive expected Review identity bằng `await Workspace._review_context(chain_id)`, lấy identity thứ tư trong tuple; dùng `review_jobs.latest_compatible(expected_identity)` thay snapshot-only `latest_for_chain` tại reconciliation. `_review_context` đã gọi canonical `review_identity` và kiểm tra Audit fingerprint; không tự dựng review version từ chuỗi tùy ý. Nếu việc dựng context lặp analysis trên warm path, reuse compatible Tier1B/Audit artifacts, không bỏ identity checks để tăng tốc.
- [ ] Thêm adapters `analysis_identity_from_projection(payload)` và `analysis_identity_from_review(identity, *, pipeline_version, input_fingerprint)` trong API boundary, return typed result/reason. Định nghĩa canonical projection identity một lần khi materialize, public JSON ở `analysis_identity`.
- [ ] Dùng same expected context cho portfolio, chain overview, persisted-row validity, background publication và narrative cache. CAS/recheck generation trước persist để kết quả cũ không overwrite current.
- [ ] Frontend cache key: serialized full envelope + resource kind + artifact revision; thay key snapshot/topology/chain-only. `ArtifactRevision = {resource_kind: string, fingerprint: string}` dùng fingerprint của Review/Audit hiện có, hoặc canonical content hash của projection không bao gồm timestamp/log/progress metadata. Cùng source identity nhưng evidence artifact mới phải có revision mới. Xuất expected revision trong resource summary/response và chỉ đọc cache khi cả identity/revision được xác minh; thiếu expected full identity/revision → lấy REST trước. Version prefix `nocpro_review_v2_`; legacy prefix bỏ qua và dọn riêng prefix app, không clear sessionStorage toàn bộ.
- [ ] Khi đổi config/topology: invalidate review/overview/topology-derived caches đúng scope; response generation cũ về trễ bị discard. Injected `initialJob` phải qua cùng matcher, không bypass.
- [ ] Legacy persisted artifact: validate old fingerprint bằng schema cũ trước. Identity thiếu chỉ được enrich từ canonical columns đã xác minh cùng row/chain, không gắn active config/topology lên artifact cũ. Không chứng minh được → stale/recompute. Bump projection schema và cache namespace; không rehash/sửa lịch sử audit artifact.
- [ ] Additive rollout API trước frontend; chain summary/overview xuất identity, không ép snapshot-summary aggregate giả một chain ID. Snapshot summary xuất snapshot/config/topology context riêng, không cast thành chain identity.
- [ ] Run `pytest -q tests/test_analysis_identity.py tests/test_quality_freshness.py tests/test_automatic_quality_pipeline.py tests/test_snapshot_quality_summary.py`; web `pnpm test -- src/analysisIdentity.test.ts src/reviewJobCache.test.ts src/CounterfactualReview.test.tsx`.
- [ ] Commit boundaries: shared envelope/adapters; scheduler/persist gates; frontend cache migration. Xóa local duplicate comparator sau khi tests chứng minh parity.

## Task 5: A5 — Evidence readiness trước quality score

**Files:** create `services/api/nocpro_api/quality_readiness.py`, `tests/test_quality_readiness.py`, `services/web/src/views/SnapshotsPortfolioView.test.tsx`; modify `cohesion_advisor.py:build_chain_quality_assessment/extract_cohesion_context`, `schemas.py`, `routes.py` summary projection, `services/web/src/types.ts`, `services/web/src/views/SnapshotsPortfolioView.tsx`, `services/web/src/views/AllChainsView.tsx`, `services/web/src/components/ChainOverviewPreview.tsx`; extend `tests/test_cohesion_narrative.py`, `tests/test_snapshot_quality_summary.py`.

**Policy selected for implementation:** role evidence đủ coverage >=0.5 và có ít nhất một evidence family independent khác đã thực sự evaluated: topology connectivity hoặc structural audit. Role coverage/member consistency cùng family `membership`; audit/overmerge cùng family `structural`; device mapping readiness **không** là independent evidence family. Counterfactual readiness cung cấp trạng thái riêng, không double-count cùng structural inputs.

**New contract:**

```python
@dataclass(frozen=True)
class QualityReadiness:
    status: Literal["READY", "PARTIAL", "INSUFFICIENT", "NOT_APPLICABLE"]
    observed_families: tuple[str, ...]
    missing_reasons: tuple[str, ...]
    evaluated_pair_count: int
    eligible_pair_count: int
```

`evaluate_quality_readiness(*, alarm_count, evaluated_members, topology_status, evaluated_pair_count, eligible_pair_count, mapped_device_count, total_device_count, audit_status, audit_complete, review_status) -> QualityReadiness` is pure. Các argument số là int nonnegative; invalid/inconsistent counts trả contract error tại boundary, không clamp âm cho im lặng.

Rules:

| Điều kiện | readiness | quality status/stars |
|---|---|---|
| <=1 alarm | NOT_APPLICABLE | NOT_APPLICABLE/null |
| role coverage <0.5 hoặc không có independent evaluated family | INSUFFICIENT | UNAVAILABLE/null |
| Có đủ families nhưng topology dùng để chấm bị thiếu mapping/bounded coverage, Audit incomplete hoặc Review chưa hoàn tất | PARTIAL | UNAVAILABLE/null; optional numeric score chỉ trong diagnostics, không public stars |
| Evidence dùng để chấm complete, Review evaluation completed, không required-source outage | READY | EVALUATED/1..5 |

“Complete” cho topology: valid mapping cho all relevant devices và every eligible pair assessed dưới declared relation/hop policy, không lấy display-path truncation làm analysis truncation. Assessed không có path trong bound là measured bounded result, **không** khẳng định disconnected toàn graph. Structural exact Audit có thể là independent family đủ dù topology absent; UI phải ghi rõ không dùng topology. Review hoàn tất với zero eligible proposals là completed nếu engine nói evaluation completed; NOT_EVALUATED/transport UNAVAILABLE không được giả completed.

Đây là policy bảo thủ được chọn để tránh “Ổn” khi evaluation chưa xong. Nếu chủ sản phẩm muốn stars sơ bộ, phải mở contract/status riêng và approval; không lén cho PARTIAL vào EVALUATED.

- [ ] Reproduce 4 CORE, 0/2 mapped, no connectivity/Audit/Review → assert stars None, status UNAVAILABLE, reason `INSUFFICIENT_INDEPENDENT_EVIDENCE`.
- [ ] Table tests: measured zero vs unknown; audit-only independent support; structural family not double-counted; truncation; all singleton; reviewed zero recommendations; negative/overcount; exact threshold .30/.50/.70/.85 bằng boundary inputs.
- [ ] Tách readiness helper khỏi score weights. Giữ weights/thresholds hiện tại cho READY để cô lập policy change; bỏ unknown dimension khỏi denominator, measured zero vẫn có weight. Nếu không đủ inputs thì không tính rating. Không biến heuristic thành probability.
- [ ] Response thêm `readiness`, `reason_codes`, `evidence_coverage` và named policy version `quality-readiness-v1`; bump `DETERMINISTIC_QUALITY_V3` → `DETERMINISTIC_QUALITY_V4` và `CHAIN_OVERVIEW_V3` → `CHAIN_OVERVIEW_V4` (nếu chưa được task trước bump thì làm tại đây; không bump hai lần trong cùng rollout). Cached 4-star cũ không còn current. Preserve old rows as stale until replaced; không bulk delete database. Backfill chạy có giới hạn concurrency; transient DB error retry, missing-input terminal UNAVAILABLE chỉ được dùng lại cho đến khi dependency revision thay đổi.
- [ ] Summary accounting: eligible = sturdy + review + evaluating + unevaluated + unavailable; singleton separate. UNAVAILABLE completed analysis vẫn tính processing progress, không healthy. Snapshot classification giữ priority Cần xem > Đang đánh giá > Chưa đủ dữ liệu > Ổn. Missing catalog summary là unavailable/error, không giả healthy. Empty denominator →0, không NaN; percent trên distinct snapshot identity, không tổng số chains.
- [ ] Dùng một `processingProgress` helper hiện có cho tất cả progress consumers, không tạo lại công thức. Test 0 snapshot, one healthy/one unavailable, update topology makes old quality stale, finite percentages/count partition; rounded percentage tolerance rõ.
- [ ] UI: một thẻ “Chưa đủ dữ liệu để chấm” kèm reason/missing source; không ba cột UNAVAILABLE, không stars 0 cho missing data. All Chains giữ filter chưa chấm.
- [ ] Run `pytest -q tests/test_quality_readiness.py tests/test_cohesion_narrative.py tests/test_snapshot_quality_summary.py tests/test_automatic_quality_pipeline.py`; web full tests/build. Commit: readiness policy; projection/summary consumers; regression UI.
