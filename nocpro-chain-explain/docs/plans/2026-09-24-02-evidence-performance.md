# Evidence and Warm-Chain Performance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking. Read the master and relevant A contracts first.

**Goal:** Người dùng truy ra được bằng chứng của từng kết luận và mở lại chain đã xử lý nhanh, có số đo kiểm chứng.

**Architecture:** Evidence presentation đọc canonical artifacts, không có graph reasoning engine mới. Đo theo request/job phase; tối ưu persisted read path dựa trên baseline, không preload toàn topology hoặc re-run analysis khi mở detail.

**Tech Stack:** FastAPI, typed Python/TypeScript DTOs, React, pytest/Vitest/Playwright, optional OpenTelemetry SDK/exporter.

## Global Constraints

Kế thừa master. B1 cần A4/A5; B2 có thể bắt đầu đo baseline trước A hoàn tất nhưng chỉ so sánh cùng dataset/config/machine. Không biến metric/trace thành nơi lưu alarm payload.

## Task 6: B1 — Một evidence drill-down cho Overview, WHY và topology

**Existing sources:** `libs/contracts/topology_paths.py`, `libs/contracts/topology_mapping.py`, `services/analysis-worker/channels/dependency.py`, `services/api/nocpro_api/cohesion_advisor.py`, persisted Audit/Review/overview projections. Reuse đường witness hiện đã được graph highlight; không implement lại BFS/Dijkstra trong drawer.

**Files:** create `services/api/nocpro_api/evidence_projection.py`, `tests/test_evidence_projection.py`, `services/web/src/components/EvidenceDetails.tsx`, `EvidenceDetails.test.tsx`; modify API `routes.py`, `schemas.py`, `cohesion_advisor.py` projection/finding serialization; frontend `types.ts`, `api.ts`, `components/ChainOverviewPreview.tsx`, `views/TopologyOverlayView.tsx`, `views/why/PairScopeView.tsx` và star renderer thực tế; extend `services/web/e2e/topology-evidence-paths.spec.ts`, `tests/test_topology_api_routes.py`.

**New view contract:**

```typescript
type EvidenceRecord = {
  evidence_id: string
  analysis_identity: AnalysisIdentity // A4 envelope mirrored in types.ts
  kind: 'MAPPING' | 'TOPOLOGY_PATH' | 'AUDIT' | 'MEMBERSHIP' | 'REVIEW'
  status: 'AVAILABLE' | 'UNAVAILABLE' | 'NOT_EVALUATED'
  statement_kind: 'OBSERVED' | 'DERIVED'
  source_artifact_id: string | null
  source_fingerprint: string | null
  summary: string
  reason_codes: string[]
  limitations: string[]
  path: null | {
    resource_ids: string[]
    relation_types: string[] // one per edge, length = nodes - 1
    hop_count: number
    traversal_semantic: string
    max_hops: number
    topology_version: string
    mapping_statuses: string[]
    analysis_truncated: boolean
  }
}
```

`EvidenceBundle = {analysis_identity, records: EvidenceRecord[], truncated: boolean, next_cursor: string|null}`. Backend mirrors typed schema. New read-only `GET /chains/{chain_id}/evidence?limit=50&cursor=...`; max100. Cursor encodes identity digest + sorted evidence ID position; stale cursor →409. `GET /chains/{chain_id}/evidence/{evidence_id}` returns 404 unknown,409 stale context. Use existing expected-snapshot headers/guard; ID alone never bypasses context.

Python builder `build_evidence_bundle(*, identity, overview_projection, pair_evidence, audit_artifact, review_result) -> dict` is pure; inputs absent produce reasons, not a database call or engine run. Route gathers already-available compatible artifacts; existing pair WHY evaluation remains its own endpoint, newly evaluated evidence can then appear in a subsequent bundle. Drawer opening must not enqueue analysis or call provider.

- [ ] Test fixture A–X–Y–Z–B (4 edges), exact mappings and pinned topology. Assert `hop_count==4`, edge list length4, same evidence ID when consumed by Overview and graph. ID = SHA256 of canonical JSON(identity + kind + semantic payload + source fingerprint), not Python `hash()` or array position.
- [ ] Test P0 configured max3 cannot support 4-hop Dep_hop claim; Overview may show bounded structural path4 with explicit semantic/bound. The common evidence drawer must expose this difference rather than falsely declaring equal evidence. Test directed reverse path rejected, ambiguous mapping excluded, mixed relation unsupported unless existing analyzer explicitly supports it.
- [ ] Test analysis truncation vs display truncation: hidden visual nodes không được sửa canonical witness; request pinned subgraph containing witness intermediates before highlight. If graph cannot load exact version/path, show explicit unavailable, never highlight approximate replacement.
- [ ] Add evidence references to deterministic findings/quality reasons. Existing strings remain readable during additive deployment, new `evidence_ids` link to typed records. LLM only receives reference IDs in grounded context; validate output references exist in same bundle. No new provider call just to label drawer.
- [ ] Implement drawer with `dialog`/accessible panel, focus return, Esc, keyboard links; show Vietnamese summary, source/version, relation direction, hop count, mapping verification, limitations and no-data reason. Reuse existing style tokens, not another dashboard layout.
- [ ] Click star → readiness + dimensions + evidence refs; click Overview claim → linked records; click path → pinned topology highlight. No-data → one concise explanation and data requirements, not three dead capability columns.
- [ ] Unit assertion pattern:

```python
assert record["path"]["hop_count"] == len(record["path"]["resource_ids"]) - 1
assert record["analysis_identity"] == bundle["analysis_identity"]
assert set(finding["evidence_ids"]) <= {r["evidence_id"] for r in bundle["records"]}
```

- [ ] Run `pytest -q tests/test_evidence_projection.py tests/test_topology_api_routes.py tests/test_cohesion_narrative.py`; web `pnpm test -- src/components/EvidenceDetails.test.tsx`; `pnpm e2e -- topology-evidence-paths.spec.ts` against isolated frontend/fixtures. Add one real API version-pinned acceptance in D1: route mocks alone không chứng minh persisted provenance.
- [ ] Cleanup: remove duplicate presentation mappers only after all three consumers use bundle; retain layout utilities and distinct algorithm policies. Commit: API evidence contract; common drawer; existing consumers + cleanup.

## Task 7: B2 — Instrumentation và reproducible warm-chain benchmark

**Files:** create `services/api/nocpro_api/observability.py`, `tests/test_observability.py`; modify `app.py`, `routes.py`, `workspace.py`, `quality_background.py`, `tier1a_coordinator.py` at phase boundaries; extend `benchmarks/run_runtime_review_benchmark.py`, `tests/test_runtime_review_benchmark.py`; create `services/web/e2e/warm-chain-performance.spec.ts`; documentation output `docs/acceptance/2026-09-24-performance.md` at implementation time.

**Consumes:** A4 identity for trace context (not metric labels); persisted completed chain; canonical benchmark dataset metadata.
**Produces:** timing JSON with manifest, p50/p95/sample count/errors/job-submission delta, request phase timings and optional OTLP traces.

**Do not run existing runtime benchmark against user stack:** it restarts Docker API and creates/deletes benchmark Review rows despite read-focused description. Extend it with safe read-only mode first.

New CLI contract:

```text
python -m benchmarks.run_runtime_review_benchmark
  --mode read-only|acceptance-restart
  --api-url URL --chain-id ID --snapshot-id ID --snapshot-version VERSION
  --repetitions 30 --output PATH
```

Defaults: `read-only`, no restart/write/delete. `acceptance-restart` requires explicit `--allow-disruption`, dedicated compose project name and DB identity check; abort if supplied project not isolated. Preserve existing env compatibility via adapter, deprecate unsafe implicit mode. Script must not select snapshot in read-only mode: verify active exact identity and fail if different. The source audit found `GET /api/v1/chains` can enqueue snapshot-wide quality work in the in-memory fallback, so read-only mode uses the read-only snapshot catalog for identity and measures only the pinned persisted `overview-cards` GET; it records analysis/list/Deep Dive/Review as not measured with the handler side-effect reason. The UI E2E acceptance runs only on the isolated persisted stack.

- [x] Unit test CLI default forbids subprocess Docker/repository writes; test nearest-rank percentile reuse existing `observed_nearest_rank`, empty samples/errors counted correctly, fixture results not labeled live.
- [ ] Baseline scenarios: 2-alarm, ~50-alarm, largest available multi-alarm chain; >=30 sequential warm reads after 5 warmups; 10 concurrent readers; cold UI route with persisted backend; restart/persisted recovery separately. Record actual counts, data SHA256/version, machine CPU/RAM, commit/config/topology, provider mode and background load.
- [ ] Measure chain analysis read, overview projection read, latest Deep Dive/Review read individually. Capture endpoint paths from `api.ts` rather than inventing nonexistent endpoints. Block POST analysis/job creation in browser benchmark and assert no hidden calls; compare DB job count before/after dedicated acceptance.
- [x] Add timers/counters: `api.request.duration`, `db.read.duration`, `analysis.queue.wait`, `analysis.compute.duration`, `provider.duration`, `event_loop.lag`, `quality.freshness.lag`, `cache.hit/miss`. Call sites are wired for requests, persisted quality/review reads, bounded executor queue/compute/provider, event-loop lag, freshness, and job/cache submissions. Labels are allow-listed route template/stage/status/workload only; IDs and fingerprints are not attributes or metric labels.
- [x] Keep `observability.py` no-op when `NOCPRO_TELEMETRY_ENABLED=false` (default); API never fails if exporter down. The optional official OpenTelemetry SDK/exporter extra is pinned and one process runtime is acquired/released with lifespan. Span links from ingestion to job are not yet implemented; do not force a four-hour single open span.
- [x] HTTP `Server-Timing` optional behind `NOCPRO_SERVER_TIMING_ENABLED=false`; no secret/cache key details. Browser harness uses `performance.now`, not cross-host wall clock subtraction. End-to-end freshness still needs a single clock/test driver or explicit clock uncertainty.
- [ ] Proposed acceptance budgets on documented local acceptance hardware: warm read API p95 <=300ms; first useful persisted detail p95 <=1000ms; 10-reader warm read p95 <=750ms; idle event-loop lag p95 <=50ms. Exclude LLM generation and initial analysis from warm-read budget. If baseline cannot meet budgets, keep report FAIL with phase bottleneck; do not silently raise budget.
- [ ] Regression gate: >20% p95 regression and >20ms absolute on same hardware is fail; use >=30 samples and raw timings. CI noisy shared-runner timings informational; structural gates (no recompute/no POST/bounded query count) mandatory CI.
- [ ] Run unit tests then read-only benchmark on isolated loaded app. Example (after CLI implemented):

```bash
PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/python -m benchmarks.run_runtime_review_benchmark --mode read-only --api-url http://127.0.0.1:8800 --chain-id SYN-CHAIN-MOVE-SOURCE --snapshot-id synthetic_counterfactual_move_v1:snapshot_000 --snapshot-version 1 --repetitions 30 --output /tmp/hindsight-warm-chain.json
```

Verify fixture's real snapshot ID/version against REST first; if catalog ID differs from snapshot ID, use returned canonical identity and document it. No fabricated latency numbers.

- [ ] Commit: safe benchmark modes; tracing boundaries; browser performance harness.

## Task 8: B3 — Tối ưu theo số đo, cache có giới hạn, sửa lint causes

**Files:** modify only measured hot paths among `workspace.py`, `routes.py`, `persistence/repository.py`, `services/web/src/App.tsx`, `CounterfactualReview.tsx`, `views/TopologyOverlayView.tsx`, `reviewJobCache.ts`; extend existing focused tests and B2 benchmark. Create `services/web/src/chainReadCache.ts` only if multiple consumers still duplicate equivalent requests after A4 (otherwise reuse existing canonical cache).

**Contract:** Completed/current artifact GET never starts job; one in-flight request per exact resource identity; in-memory LRU <=100 chain entries/sessionStorage <=20 persisted terminal entries. TTL proposed 5min bounds memory/staleness exposure but never substitutes A4 identity checks; version event invalidates immediately. No indefinite cache of transient UNAVAILABLE.

- [x] Write spies for `submit_deep_dive`, `submit_review`, provider calls and heavy analysis on warm overview GET; expected zero. Cold persisted read may hydrate bounded DTO, not rescore/recompute. Test active snapshot changes while GET pending →discard stale result.
- [ ] Identify dominant span from B2. Fix it narrowly: repository batch lookup instead of N+1, index only with EXPLAIN evidence, memoize immutable projection by full identity instead of recalculation. Don't add DB index migration on speculation.
- [x] Frontend fetches chain detail only for the selected chain; Overview reads share exact-context in-flight work, are identity-gated before cache reuse, and abort on unmount/context switch. List virtualization was not added because no DOM-cost measurement justified it.
- [x] Test in-memory LRU eviction, session-storage cap/quota, corrupt JSON, old schema prefix, context-change race, and identity mismatch. Never return a different chain's result to satisfy a fast-path cache hit.
- [x] Fix lint causes at source: App polling closure reads fresh chainList through primitive dependencies; CounterfactualReview includes stable context dependencies; TopologyOverlay selections are context-bound/derived; canonical path/terminal defaults are stable. No lint suppressions added.
- [ ] Compare the same live B2 workload before/after; record request/query counts, heap/memory bound and p95. Structural fixture E2E confirms Overview GET count fell from three to one across Overview/Chain Detail/Topology; no live latency/query/heap comparison is available.
- [ ] Run backend focused affected tests and web full `pnpm test`, `pnpm build`, `pnpm lint` (these passed: 1,213 backend marker tests, 148 web tests, build and lint). The separate browser route switch/reopen/refresh run under network throttling remains pending.
- [ ] Commit separately: backend hot path, frontend request/cache consolidation, lint/derived state. Delete obsolete read-cache adapters only after all consumers migrate.
