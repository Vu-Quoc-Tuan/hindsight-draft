# Live Updates and Evolution Explanations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking. Read the master and A4/A5/B1 contracts first.

**Goal:** Snapshot/chain state cập nhật chủ động và người dùng biết điều gì thay đổi giữa các snapshot mà không tạo reasoning pipeline thứ hai.

**Architecture:** Durable event journal chỉ invalidates REST resources sau commit; một SSE connection/tab, reset/reconcile bằng REST. Evolution tiếp tục dựa trên lineage DAG hiện có; diff facts đọc immutable inputs và quality receipts, không đoán root cause hoặc recompute score ở GET.

**Tech Stack:** PostgreSQL/SQLAlchemy/Alembic, FastAPI StreamingResponse, browser EventSource, React, pytest/Playwright.

## Global Constraints

Kế thừa master. `NOCPRO_LIVE_UPDATES_ENABLED=false` và `NOCPRO_EVOLUTION_CHANGES_ENABLED=false` mặc định khi code mới merge, bật sau D1. Không thêm Redis, broker khác hoặc Kafka topic riêng chỉ cho UI.

Phương án journal/SSE hỗ trợ các API process đọc chung event stream, **không** biến global active Workspace của ứng dụng thành hệ thống multi-user/multi-worker an toàn. Những giới hạn selection hiện hữu phải được ghi rõ; test tập trung vào event correctness, không claim deployment topology mới.

## Task 9: C1 — Durable invalidation journal có commit ordering

**Files:** create `services/api/nocpro_api/persistence/change_journal.py`, `tests/test_change_journal.py`, `tests/test_change_journal_postgres.py`; modify `persistence/models.py`, `persistence/repository.py` persist quality/snapshot terminal methods, `persistence/topology_repository.py` committed topology activation; create `migrations/versions/0021_change_event_journal.py` **only if next Alembic revision still follows 0020**. Recheck heads; revision id/down_revision phải nối head thực tế, không duplicate.

**Tables:**

```text
change_event_clock(singleton_id PK=1, epoch UUID NOT NULL, revision BIGINT NOT NULL)
change_events(epoch UUID, revision BIGINT, event_type VARCHAR,
              snapshot_id TEXT NULL, snapshot_version TEXT NULL,
              chain_id TEXT NULL, topology_version TEXT NULL,
              identity_digest TEXT NULL, invalidates JSONB NOT NULL,
              created_at TIMESTAMPTZ NOT NULL,
              PRIMARY KEY(epoch, revision))
```

`append_change(session, *, event_type, snapshot_id, snapshot_version, chain_id, topology_version, identity_digest, invalidates) -> ChangeEvent` chạy **trong cùng transaction** với state mutation. `read_changes_after(epoch, revision, *, limit=100) -> list[ChangeEvent]`; `journal_position() -> {epoch, min_revision, revision}`. `ChangeEvent` là frozen DTO fields như table. No business payload in journal.

**Ordering decision:** Không dùng bare sequence ID làm resume cursor: transaction revision2 có thể commit trước revision1 và client bỏ lỡ revision1. Serialize journal writers bằng `UPDATE change_event_clock SET revision=revision+1 WHERE singleton_id=1 RETURNING epoch,revision` cuối business transaction; row lock giữ tới commit. Insert event rồi commit together. All publishing writers acquire lock in same order; no network/analysis while holding row lock. Throughput đo trong D1; chỉ publish state transitions, không từng progress-percent/edge.

- [ ] Postgres test hai transactions đảo thời gian xử lý; second revision không visible before preceding committed revision; rollback không tạo event phản ánh state không tồn tại. Test replay idempotency không publish terminal change vô ích khi persisted contents không đổi.
- [ ] Hook `quality.changed`, `snapshot.changed`, `topology.changed`. `invalidates` enum values `catalog`, `quality-summary`, `chain-list`, `chain-detail`, `topology`, `evolution`. topology profile update có thể invalidates nhiều snapshot; publish bounded scope/profile reference rồi client refresh active relevant resources, không materialize hàng nghìn per-chain events trong commit.
- [ ] Catalog file changes/config in-memory không có atomic DB mutation: client vẫn refresh REST 60s + on focus; local config action immediately invalidates local exact caches. Không tuyên bố journal bảo đảm transaction cho state ngoài database. Nếu thêm config event, mark advisory và không xem đó là source of truth.
- [ ] Retention: 24h mặc định, configurable, batched cleanup <=1000 old event rows/transaction. Cleanup chỉ journal rows, không quality/snapshot/audit. `min_revision` đọc từ retained data. New/unknown epoch forces full client resync. Database restore must rotate epoch as explicit recovery step before enabling stream; otherwise force all clients resync during maintenance.
- [ ] Unit test serialization, reason bounds; Postgres integration tests required for ordering (SQLite/mock không chứng minh lock behavior). Run `pytest -q tests/test_change_journal.py`; DB suite ở D1.
- [ ] Migration upgrade/downgrade only isolated DB; downgrade drops **new journal only**, never business data. Feature off permits rollback old binary without down migration.
- [ ] Commit: journal schema/repository; transactional hooks and tests.

## Task 10: C2 — SSE transport: replay, reset, heartbeat, disconnect

**Files:** create `services/api/nocpro_api/live_updates.py`, `tests/test_live_updates.py`; modify `app.py` lifespan, `routes.py` or include focused router from `live_updates.py`, `services/web/nginx.conf` for SSE location buffering. No global proxy buffering change.

**Endpoint:** `GET /api/v1/events`; scoped to same existing deployment access boundary, no privileged/raw data. SSE is not active-snapshot-specific, so do not bind entire stream lifetime to the normal short-lived expected-snapshot middleware. Read payload contains identities only; if deployment already authenticates read APIs, preserve that authentication for stream too. Do not introduce token query strings.

Wire contract:

```text
retry: 3000

id: <epoch>:<revision>
event: invalidate
data: {"schema_version":"change-event-v1","event_type":"quality.changed","snapshot_id":"s1","snapshot_version":"1","chain_id":"C1","identity_digest":"sha256...","invalidates":["quality-summary","chain-detail"]}

event: heartbeat
data: {"schema_version":"change-event-v1","server_time":"2026-09-24T00:00:00Z"}

event: reset
data: {"reason":"CURSOR_EXPIRED","epoch":"...","revision":123}

```

reset reasons `INITIAL_SYNC`, `CURSOR_EXPIRED`, `EPOCH_CHANGED`, `CURSOR_AHEAD`, `BUFFER_OVERFLOW`. Reset event carries current `id` as baseline; client first invalidates full REST resources. Races are safe because subsequent invalidations revalidate again, events aren't state deltas. Malformed Last-Event-ID →400 before streaming, feature off/no persistence →503 (frontend fallback). Valid cursor retained → replay after cursor, ordered max100/batch. Max serialized event 16KiB, named heartbeat15s, bounded queue256/connection. Heartbeat không có `id`, không advance Last-Event-ID và không invalidate data; timestamp chỉ để chẩn đoán, không tính latency giữa hai clock không đồng bộ.

- [ ] Unit tests parse cursor, correct content-type/cache-control, replay order, id field, initial reset, expired/ahead/epoch cursors, unknown schema, cancellation closes generator and DB sessions.
- [ ] Implement one journal tailer per app worker, DB polling <=1Hz when clients connected; fan-out bounded queues. Reconnect replay reader and live subscription must not lose events at handoff: register buffer first, snapshot high-water, replay up to high-water, then drain buffer >high-water with dedup. All DB cursors bounded; never keep a transaction open for stream duration.
- [ ] Slow client overflow → reset/disconnect, not unbounded RAM and not blocking other clients. Do not put event-loop sleep under DB transaction. Disconnect cancels connection task but not shared tailer used by other clients; lifespan closes all.
- [ ] Nginx SSE location: `proxy_buffering off`, read timeout >2 heartbeats, gzip off for stream, forwarding Last-Event-ID; preserve existing CORS/proxy path. Test actual deployment path, not only ASGI.
- [ ] Transport test using actual local socket against dedicated test app (httpx in-memory may buffer never-ending streaming responses); assert first event arrives before request completes, heartbeat visible, reconnect resumes. Release resources in finally.
- [ ] Run `pytest -q tests/test_live_updates.py`; D1 actual Postgres + proxy reconnect/slow consumer tests.
- [ ] Commit: SSE server and lifecycle; reverse-proxy support. Keep feature disabled until D1.

## Task 11: C3 — Một client refresh coordinator, bỏ polling trùng

**Files:** create `services/web/src/liveUpdates.ts`, `liveUpdates.test.ts`, `services/web/src/useLiveUpdates.ts`; modify `App.tsx` 4s/6s/6s polling effects, `api.ts`, A4 identity/cache invalidators; extend `services/web/e2e/snapshot-portfolio.spec.ts`, create `services/web/e2e/live-updates.spec.ts`.

**New interface:**

```typescript
type InvalidationScope = 'catalog' | 'quality-summary' | 'chain-list'
  | 'chain-detail' | 'topology' | 'evolution'
type LiveState = 'CONNECTING' | 'LIVE' | 'DEGRADED' | 'DISABLED'
// Class implementation owns one EventSource and timers per tab/app mount.
// new LiveUpdates({onInvalidate, onState, createEventSource})
// start(): void; stop(): void
// onInvalidate(scopes: ReadonlySet<InvalidationScope>): void
```

Parsed event validated structurally; invalid/unknown event schema →full REST refresh + degraded diagnostic, never silently mutate counts. Identity mismatches trigger revalidation, never apply old chain response to current route. Global summary/catalog changes processed even when another snapshot is open; detail refresh limited to current affected identity.

- [ ] Fake EventSource tests: StrictMode mount/unmount produces one live connection and zero leaked intervals; event burst merges scopes for250ms; dedup repeated epoch/revision; reject invalid payload; reset refreshes all; abort response from previous selection.
- [ ] Refresh scheduler max one in-flight GET per resource/context. If invalidated while request running, mark dirty and re-fetch once after completion; **do not drop** event merely because fetch in-flight. Switching context aborts obsolete request and clears old dirty flags only for old key.
- [ ] LIVE mode: remove independent4/6/6s loops; keep60s reconciliation and focus/visibility-return refresh. DEGRADED/DISABLED mode: single coordinator fallback every6s, single-flight, reconnect handled once (native EventSource auto reconnect with server retry interval; don't layer a second reconnect timer over it). After30s without open/event/named heartbeat show degraded. EventSource không bảo đảm exponential backoff; không ghi tài liệu như thể có sẵn.
- [ ] Consume C2 named `heartbeat` every15s for liveness only; no data refresh, no cursor advance. Tests assert comments alone do not satisfy JS liveness contract.
- [ ] Render subtle “Đang cập nhật trực tiếp / Kết nối gián đoạn, đang đồng bộ định kỳ”, last successful sync timestamp; keep old visible data with stale banner during network error, never reset healthy counts to0 without warning.
- [ ] Keyboard/tab behavior and hidden tab: no aggressive fetch while hidden, keep connection or close intentionally; on visible force REST refresh. All cleanup uses owner `stop`, no module-global orphan interval.
- [ ] Browser test: background snapshot completes while another is selected → totals/percent update without reload; duplicate event doesn't double count; outage→fallback refresh→reconnect→reset; stale prior request cannot overwrite latest. Assert <=one EventSource and bounded REST request count.
- [ ] Run `pnpm test -- src/liveUpdates.test.ts`; full build/lint; `pnpm e2e -- live-updates.spec.ts snapshot-portfolio.spec.ts` in isolated stack.
- [ ] Delete old independent polling effects and unused polling helpers once coordinator works in BOTH flag states. Feature rollback selects fallback mode in same coordinator, not reinstalls duplicated polling implementation.
- [ ] Commit: coordinator/tests; App integration and old-loop removal.

## Task 12: C4 — Timeline & Evolution: facts và lý do thay đổi

**Files:** create `services/api/nocpro_api/evolution_changes.py`, `tests/test_evolution_changes.py`, `services/web/src/components/EvolutionChanges.tsx`, `EvolutionChanges.test.tsx`; modify `persistence/models.py`, `persistence/repository.py`, `workspace.py:evolution`, `schemas.py`, `serializers.py`, `routes.py`, `services/web/src/types.ts`, `api.ts`, `EvolutionPanel.tsx`, `views/EvolutionView.tsx`, `services/web/e2e/evolution.spec.ts`; migration `0022_quality_evaluation_receipts.py` after C1 (rebase number onto actual head).

**Do not replace:** `services/analysis-worker/evolution/{lineage,global_lineage,lifecycle,drift,pipeline}.py` already own lineage and drift semantics. Reuse matched lineage edges and canonical alarm identities; don't build new chain matcher.

**Historical receipt:** immutable `quality_evaluation_receipts(receipt_id PK, identity_digest, artifact_revision, analysis_identity JSONB, assessment JSONB, source_artifact_refs JSONB, created_at, UNIQUE(identity_digest, artifact_revision))`. `artifact_revision` = SHA256 canonical assessment + source artifact fingerprints + policy version, không bao gồm created_at/progress. Cùng source identity có thể phát sinh Audit/Review mới, nên identity_digest **không** unique một mình. Write same transaction as successful/current quality materialization; ON CONFLICT same identity/revision verifies same canonical content or reports integrity error, not last-write-wins. Persist dimensions/readiness/score before display rounding. Old quality rows can be adapted only when identity/fingerprint verifiable; missing historical inputs are explicit UNAVAILABLE. Never invent historical receipts with today's config. Journal emits quality.changed after receipt transaction.

**Endpoint:** `GET /chains/{chain_id}/evolution/changes?parent_snapshot_id=...&parent_snapshot_version=...&parent_chain_id=...&parent_receipt_id=...&child_receipt_id=...`. Child = exact current context guarded as existing chain endpoints. Require chosen parent→child belongs to verified lineage edge; no parent args: return valid predecessor choices, don't pick arbitrary predecessor in merge. Receipt selection defaults latest compatible historical receipt for each endpoint; if multiple non-equivalent choices, return choices, don't silently compare different config versions.

**New response:**

```typescript
type EvolutionChanges = {
  status: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE'
  reason_codes: string[]
  parent: {snapshot_id: string; snapshot_version: string; chain_id: string}
  child: {snapshot_id: string; snapshot_version: string; chain_id: string}
  event_type: string // existing lineage event, no new matcher
  membership: {
    added_count: number; removed_count: number; retained_count: number
    added_alarm_ids: string[]; removed_alarm_ids: string[]; truncated: boolean
  } | null
  context_changes: Array<{field: string; before: string|null; after: string|null}>
  quality: {
    comparable: boolean; reason_codes: string[]
    before_stars: number|null; after_stars: number|null; delta: number|null
    before_receipt_id: string|null; after_receipt_id: string|null
  }
  explanations: Array<{code: string; text: string; evidence_ids: string[]}>
}
```

**Comparability:** score delta only when same quality method/readiness policy/config/pipeline and both READY, same topology version for strict numeric delta. Snapshot membership/input can change (that's what comparison studies). If config/topology differs, show individual scores and explicit context change but `delta=null`; do not attribute change to membership. Structural grouping changes/split-merge can report facts without declaring quality improved. Canonical alarm identity unavailable across snapshots →membership unavailable, not all removed+added by fabricated ID matching.

- [ ] Unit tests pure diff with sets:

```python
before = {"a1", "a2", "a3"}
after = {"a2", "a3", "a4"}
assert sorted(after - before) == ["a4"]
assert sorted(before - after) == ["a1"]
assert len(before & after) == 2
```

Implement `compare_evolution_facts(*, parent_members, child_members, parent_receipt, child_receipt, lineage_edge) -> dict` pure. Difference in chain membership is “rời chain”, **not** “alarm đã clear” unless lifecycle evidence says cleared. Time strings compared via parsed UTC instants; missing/timezone-invalid produces reason, not synthetic timestamp.

- [ ] Tests split/merge multiple predecessors, reused chain ID unrelated lineage, same snapshot ID different version, out-of-order arrival, source_kind synthetic vs real, missing receipt, fingerprint mismatch, config change with apparent star increase, incomplete topology history, singleton.
- [ ] Read path performs bounded DB lookups and set diff only, not audit/ranker/provider. Exact counts from indexed membership queries; max100 IDs per side response and `truncated=true` when longer. For large sets use DB count/set operations; no load entire lineage graph/topology on each click.
- [ ] Context changes: topology/config/pipeline version facts; do not claim which physical edge changed unless both historical graph artifacts retained and comparable. “Topology version thay đổi; không có đủ lịch sử để đối chiếu cạnh” is valid, not fabricated diff.
- [ ] Narrative templates tied to diff facts/evidence references: “Thêm 1 alarm vào chain”; “Không so trực tiếp số sao vì cấu hình đánh giá đã đổi”; “Audit mới phát hiện candidate split” only if receipt contains that Audit result. No new LLM generation necessary.
- [ ] UI extends existing Timeline & Evolution with selected transition details and parent chooser for merges; use A4 full context key instead of `chainId`-only loaded/initialResult guard in `EvolutionPanel`. Same chain ID across snapshots must refetch/discard stale data.
- [ ] Test UI preserves single-snapshot unavailable explanation; keyboard transition selection; explicit missing data; provenance synthetic badge; no causal language. API 404 unknown edge,409 stale context,422 malformed selection; DB outage503 rather than empty success.
- [ ] Run `pytest -q tests/test_evolution_changes.py tests/test_evolution.py tests/test_evolution_local.py tests/test_evolution_production_validation.py`; web component tests/build and `pnpm e2e -- evolution.spec.ts`.
- [ ] Commit: immutable receipts; diff contract/API; existing Timeline & Evolution integration. No old timeline page added, no separate lineage engine retained.
