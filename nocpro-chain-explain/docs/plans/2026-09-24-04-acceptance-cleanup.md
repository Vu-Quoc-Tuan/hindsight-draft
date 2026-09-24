# Acceptance, Cleanup and Rollout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking. No phase is complete from unit tests alone.

**Goal:** Chứng minh fixes/features qua runtime độc lập, dọn implementation cũ an toàn và bàn giao có thể rollback.

**Architecture:** Tách unit, database/Kafka integration, proxy/browser và performance gates. Acceptance stack có identity/ports/volumes riêng; feature flags default off tới khi đủ bằng chứng.

**Tech Stack:** pytest, PostgreSQL/Kafka in isolated Docker Compose, Alembic, Vitest/Playwright, GitHub Actions.

## Global Constraints

Kế thừa master. Không chạy cleanup Docker/SQL rộng, không reset worktree, không publish images/PR/push/deploy tự động. Việc tạo hoặc chạy acceptance stack cần quyền môi trường phù hợp; thiếu quyền ghi BLOCKED, không thay bằng giả lập rồi claim runtime pass.

## Task 13: D1 — Integration acceptance ma trận đầy đủ

**Files:** create `tests/test_restart_quality_integration.py`, `tests/test_live_pipeline_acceptance.py`, `docker-compose.acceptance.yml`, `scripts/run_hardening_acceptance.sh`, `docs/acceptance/hardening-report-template.md`; extend existing `tests/test_postgres_snapshot_ingest.py`, `tests/test_topology_repository_integration.py`, `services/web/e2e/deep-dive-persistence.spec.ts`, `operator-flow.spec.ts`, other new suites from B/C.

**Compose requirements:** unique project name `hindsight-hardening-<run-id>`; host bind127.0.0.1; no mount deployment DB/data; no `container_name` conflict; own volumes and Kafka topics ending run ID. Use actual existing repo image/build definitions; no invented service binary. Script prints only project/ports/nonsecret identities, records exact container/image digest and migration head.

**Script contract:** `scripts/run_hardening_acceptance.sh --project NAME --allow-isolated-runtime`. Refuse empty/project matching live deployment. Discover actual ports from compose, export `NOCPRO_E2E_BASE_URL`, `NOCPRO_E2E_API_URL`, test-only DSNs internally (no echo). Verify compose labels before any restart/down. Default leaves artifacts/volumes for inspection; `--cleanup-owned-containers` removes this run's containers/networks only, **no `down -v`** without explicit user approval.

- [ ] Add pytest markers `postgres`, `kafka`, `docker`, `e2e` consistently; tests requiring services skip with precise reason if env absent. Dedicated acceptance CI fails if required tests skipped. Unit command in master never touches deployment.
- [ ] Migration test fresh DB upgrade to head, prior baseline head0020→head preserving seeded snapshots/artifacts, Alembic single head. Downgrade only added tables in throwaway DB then upgrade; do not rewrite historical checksums.
- [ ] Restart scenario: ingest isolated snapshot/topology →finish Deep Dive/Review→flush persistence→restart API only→read chain detail. Check same compatible artifact IDs, quality materializes if deliberately absent in fixture, no extra job, correct stars/readiness, no legacy fallback prose.
- [ ] Freshness scenario: pinned snapshot remains on old topology after new active topology; unpinned snapshot moves through stale/queued→new identity. Change analysis/review config mid-job: old result cannot publish current; eventually exactly one compatible completed result. Simulate restart during pending job.
- [ ] Kafka scenario: valid topology event; malformed UTF8 key; malformed JSON; valid schema but wrong key; DLQ outage/recovery; duplicate events; DB commit then process killed before offset commit. Verify no data loss/no duplicate materialized version and next valid record processed. Record DLQ topic/offset evidence without raw payload.
- [ ] Offload scenario: deterministic slow blocking provider stub in isolated process, cancel request task via server test hook/test harness; unrelated `/health` remains responsive; pool capacity stays bounded. This is not proof every browser disconnect cancels ASGI automatically; test both server cancellation and client disconnect behavior separately.
- [ ] SSE scenario: real PostgreSQL journal + API + nginx + browser; commit visible before event; two transactions order; reconnect cursor replay; expired cursor reset; slow-client overflow; proxy buffering disabled; one event source/tab; fallback polling continues when SSE disabled/down. Test API process restart loses no required invalidation after REST resync.
- [ ] UI scenario: select snapshotA, start request, switchB with same chain ID; old response must not paintB. Completed chain details render without submit POST. All Chains sort/star/unrated filters persist correctly. Background completion changes portfolio counts/percent without selecting that snapshot.
- [ ] Evidence/Evolution scenario: 4-hop witness includes intermediates and exact topology version; P0 max3 remains unavailable if out-of-bound; no false equality. Split/merge chooser, config-drift comparison disabled, retained historical receipts and synthetic provenance shown.
- [ ] Capture raw pytest/Vitest output, browser traces/screenshots on failure, timings JSON and manifest in `/tmp/hindsight-acceptance-<run-id>/`; sanitized summary saved under `docs/acceptance/` only with authorized documentation change. Never copy `.env`/cookies/authorization headers into artifact.
- [ ] Expected: all required matrix rows PASS. Inaccessible broker/socket/provider marks that specific row BLOCKED; unrelated tests still run. Provider live test opt-in only with explicit credentials authorization; fake provider validates contract, not model quality.
- [ ] Commit: isolated harness; integration tests. Do not commit test artifacts containing generated data/log secrets.

## Task 14: D2 — CI gates và dọn code thừa sau cutover

**Files:** root `../.github/workflows/ci.yml`, root `../Makefile`; modify obsolete helpers only in actual consumer files from A–C; update `docs/CURRENT_STATUS.md`, `docs/FEATURE_CAPABILITY_MATRIX.md`, `docs/METHODOLOGY.md` for changed readiness semantics.

**CI split:**

1. Unit/backend full feasible suite with explicit empty provider/DB env and no dotenv leakage; frontend tests/build/lint; mock full tests. Current `make test-backend` selects a subset, so add `make test-backend-unit-all` target rather than claim existing selected suite covers all.
2. Postgres migration/integration with test-only service; no hidden production DSN. Require0 skips in marked service suite when services healthy.
3. Kafka+proxy/browser acceptance as separate job on PRs touching ingest/topology/jobs/live/evolution and nightly full; attach sanitized failure artifacts. No conditional path filter that skips shared libs/lockfile/schema changes.
4. Performance structural invariants each PR; reproducible timing benchmark in controlled runner/nightly, not flaky stopwatch assertion on arbitrary shared runner.

- [ ] New Makefile target executes master unit selection with project PYTHONPATH; no install/upgrade implicit in test target. Test count may grow; require0 failures, skips listed rather than pinning1120 as magic count.
- [ ] Build/lint actually run in CI; preserve lockfile frozen installs and pinned supported tools. Add job timeout appropriate for measured ~4min backend + new tests, no timeout weakening to mask hangs.
- [ ] Search old consumers and document disposition before delete:

```bash
rg -n 'latest_for_chain|ThreadPoolExecutor|projection_staleness_reason|terminal_quality_row_is_current' services libs tests
rg -n 'setInterval|nocpro_review_|initialJobMatchesContext' services/web/src
rg -n 'evaluate_slice_subset|evaluate_all_slices|evaluate_operation_slices' scripts/review_learning
rg -n 'AttributeExplorer|MultiChainTimeline|ChainsExplorerView' services/web/src
```

These searches include valid remaining hits. Never bulk-delete by name. `latest_for_chain` may still be valid for history display; `ThreadPoolExecutor` is valid inside shared pool/worker owner; metric helpers already shared in `slice_metrics.py` must not be reimplemented.

- [ ] Delete per-request pool logic replaced by A3; delete per-consumer identity checks replaced by A4; delete obsolete cache prefix read fallback after migration tests; delete independent App polling loops replaced by C3. Keep common comparator plus adapters, not one all-knowing module importing every layer.
- [ ] Verify no unused route/import/export/component and no frontend reference to deleted page. Keep Timeline & Evolution, layout algorithms, directed dependency semantics, chain-vs-snapshot classifiers and `project_adjacency_tree` delegation: these are different responsibilities, not code duplication to delete.
- [ ] Re-run complete unit/frontend/mock suites and builds after cleanup; `git diff --check`; inspect generated bundle size and dependency changes. No auth modifications hidden in cleanup.
- [ ] Docs state exact readiness policy, migration/legacy rules, default flags, event delivery/reset limits, security deferral and performance proof scope. Remove outdated claims of unconditional 4star/complete pipeline only if superseded by new behavior.
- [ ] Commit boundaries: CI/harness gates; narrow obsolete-code deletion; accurate docs. Review diff per commit; no blanket `git add .` when user worktree not clean.

## Task 15: D3 — Rollout, rollback, evidence-based final handoff

**Files:** create `docs/operations/hardening-rollout.md` and final acceptance report at implementation time. No live deployment as part of plan execution without separate approval.

- [ ] Record migration versions, exact image/commit, compatibility range, old/new projection version, cache prefixes, actual default flags. Backup/recovery procedure must be tested in isolated stack; don't call an untested backup sufficient.
- [ ] Recommended rollout: database additive migrations→API identity/readiness producer and pools→frontend new identity reader/evidence UI→verify A/B→enable evolution changes→verify historical coverage→enable SSE server/client→verify C/D. Rollout in maintenance window if mixed-version consumers cannot interpret new readiness; don't let old frontend silently display cached old stars.
- [ ] Rollback toggles SSE/evolution flags off first; REST fallback/read-only core remain available. Stop new writes before binary rollback if old binary cannot understand new projection schema. Keep additive tables/receipts; no automatic destructive down migration. Never mark stale projections current merely to restore visual stars.
- [ ] Monitor candidate release: job error/retry count, stale publication rejection, queue wait, pool saturation, DLQ rate, event lag/reconnect/reset rate, warm-chain p95, memory and database connections. Compare same baseline load, not a quiet machine vs saturated before run.
- [ ] Close each acceptance row with PASS/FAIL/BLOCKED, exact command/artifact/time/HEAD; output distinction between code unit, live integration and production proof. No aggregate “all okay” if auth remains deferred or live gates blocked.
- [ ] Final handoff includes task/commit map, code removed/replaced, API/schema contract changes, new env options, benchmark before/after, known limits and operator rollback commands scoped to exact project. State no user data deleted unless an explicitly authorized deletion occurred and recovery is known.

## Definition of Done cho toàn chương trình

- [ ] A0–A5, B1–B3, C1–C4 tests/contracts implemented and accepted.
- [ ] Four runtime repros no longer reproduce; insufficient-evidence scenario no longer yields public4stars.
- [ ] Full compatible identity reaches persisted writes, reads, background decisions and frontend caches.
- [ ] Cached/completed chain opens without duplicate jobs/provider work and meets documented benchmark or remains visibly FAIL.
- [ ] Evidence link opens exact same witness/version; no layout path passed off as causal evidence.
- [ ] Portfolio remains dynamic across Kafka updates, reconnect and degraded REST fallback.
- [ ] Timeline & Evolution preserved and explains factual differences without false comparability.
- [ ] No duplicate execution path retained solely for migration; necessary compatibility adapters have tests and bounded scope.
- [ ] Live Postgres/Kafka/browser/migration gates have artifacts, not only mock evidence.
- [ ] Security authorization debt is still clearly deferred, not concealed or broadened into unauthorized changes.
