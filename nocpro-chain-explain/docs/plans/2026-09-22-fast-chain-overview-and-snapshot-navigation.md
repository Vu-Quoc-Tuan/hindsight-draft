# Fast Chain Overview and Snapshot Navigation Implementation Plan

> **For the implementing agent:** Execute task by task, with a test/review checkpoint after each task. This is a handoff plan, not authorization to discard existing work or data.

**Goal:** Opening a processed chain shows its deterministic Overview cards without waiting for Ollama; exiting chain detail returns to Snapshot Overview; selecting a processed snapshot does not synchronously redo expensive work on the UI request path.

**Architecture:** Persist a small, versioned deterministic card projection during the existing background quality pipeline, expose it through a read-only endpoint, and fetch it independently of the LLM narrative. Treat snapshot selection as activation of an exact ready identity, with cached/prepared analytical state and explicit progress for cold activation. Keep snapshot, topology, config, Deep Dive and Counterfactual provenance attached to every reused projection.

**Tech stack:** FastAPI, SQLAlchemy/PostgreSQL JSONB, Python worker, React/TypeScript, Vitest, pytest, Playwright.

## Global constraints

- Preserve the dirty worktree; inspect `git status --short` and diffs before touching any listed file. Do not reset, delete, or overwrite user changes.
- Do not call Ollama from a deterministic cards endpoint or from background scoring. AI is for the narrative only.
- Do not weaken topology/evidence validation, use a global edge cap, fabricate missing scores, or present `UNAVAILABLE` as zero.
- Reuse only results matching exact `snapshot_id`, `snapshot_version`, `config_version`, topology version and relevant Tier-2 artifact identity. A stale result must be visibly stale/pending, never silently substituted.
- The new `GET /overview-cards` endpoint must never submit Deep Dive, Counterfactual or LLM work. The existing narrative endpoint is the deliberately separate on-demand LLM path.
- Singleton chains are explicitly `NOT_APPLICABLE` for chain-quality scoring; their observed member/topology cards may still be shown if deterministically available.
- Test on an isolated dev/test instance before performing selection/performance probes; selection changes the server-wide active snapshot.

## Evidence and chosen design

Current `ChainDetailView` gets three of four cards from `cohesion.context`, which is set only after `AIAdvisorPanel` calls `GET /chains/{id}/cohesion-narrative`. `Workspace._materialize_chain_quality()` already calls `extract_cohesion_context()` in the background but stores only `quality_assessment`. The browser's narrative cache lasts five minutes and disappears on reload. Snapshot selection waits for `POST /snapshots/select` and then `GET /chains`; selecting an already durable but inactive snapshot calls `ingest_snapshot()`, topology hydration and `load_validated_package()` again. The back button is hard-coded to `chains-explorer`.

Chosen over two alternatives:

1. **Recommended: persist a small card projection and keep narrative separate.** Reuses work already done by the quality pipeline; no provider dependency; requires a versioned JSON payload and backward-compatible backfill.
2. Recompute deterministic context on every card GET. Simpler schema, but repeats topology/analysis work on every visit and can recreate the lag.
3. Keep using `cohesion_narrative_cache.context`. Minimal UI change, but cards still depend on whether AI was called, its fingerprint and its cache lifetime. Reject.

The snapshot activation optimization is a separate, measurable workstream. Do not claim the card projection alone fixes the Snapshots click latency.

## Task 1 — Deterministic card projection, persisted without AI

**Files:**

- Modify `services/api/nocpro_api/workspace.py` (`_materialize_chain_quality`)
- Modify `services/api/nocpro_api/persistence/repository.py` (`persist_chain_quality_assessment`)
- Modify `services/api/nocpro_api/quality_background.py` (`_source_quality_complete` and resume behavior)
- Modify `tests/test_automatic_quality_pipeline.py`
- Modify `tests/test_snapshot_quality_summary.py` if status/backfill semantics change

**Contract:** Keep existing top-level `assessment` fields in `chain_quality_assessment.payload` unchanged, and add `overview_projection` with `projection_version: "CHAIN_OVERVIEW_V1"`, `representative_member`, the bounded fields needed by `TopologyCoverageCard`, and `recommendations`. Record source identity/fingerprint beside the projection. Do not store the entire cohesion context (it may include large paths/analytical findings). Explicitly define the allowed field set in one helper, e.g. `build_chain_overview_projection(context) -> dict`.

- [ ] Write a failing test where a completed background quality job produces an assessment row containing the projection above, with no mocked provider call.
- [ ] Write a failing legacy-row test: `status=EVALUATED` but no matching `overview_projection.projection_version` must not be treated as backfill-complete. It must be retried from already persisted deterministic artifacts, not trigger Ollama or discard the old assessment.
- [ ] Implement the projection helper from the `context` that `_materialize_chain_quality()` already has; update repository upsert to preserve the current top-level status/stars fields and include the projection.
- [ ] Make the background completion check require a current projection version for eligible multi-alarm chains. Keep `UNAVAILABLE` terminal when evidence is genuinely unavailable; do not loop forever trying to invent a projection.
- [ ] Run `uv run pytest -q tests/test_automatic_quality_pipeline.py tests/test_snapshot_quality_summary.py` from `nocpro-chain-explain`. Expected: all pass. Review the JSON payload shape and exact fingerprint in one stored test row.

**Acceptance:** A processed multi-alarm chain has one deterministic DB row with card fields; old rows are eligible for automatic deterministic backfill; quality totals still read status/stars correctly.

## Task 2 — Read-only card API and independent frontend fetch

**Files:**

- Modify `services/api/nocpro_api/schemas.py`, `services/api/nocpro_api/routes.py`
- Modify `services/web/src/api.ts`, `services/web/src/types.ts`
- Modify `services/web/src/views/ChainDetailView.tsx`, `services/web/src/components/ChainQualityCards.tsx`, `services/web/src/AIAdvisorPanel.tsx`
- Add focused API tests in `tests/test_api.py` or a new `tests/test_chain_overview_projection.py`
- Modify `services/web/src/components/ChainQualityCards.test.tsx`; add a Chain Detail data-flow test

**API contract:** `GET /api/v1/chains/{chain_id}/overview-cards` returns `{snapshot_id, snapshot_version, chain_id, status, projection_version, representative_member, topology, quality_assessment, recommendations}`. `status` is `READY`, `PENDING`, `UNAVAILABLE`, or `NOT_APPLICABLE`. For missing/legacy projection return `PENDING` with null card fields and no LLM call; the background backfill from Task 1 supplies it. For a singleton, return `NOT_APPLICABLE` quality; derive small observed member/topology facts deterministically if safe, otherwise explicit unavailable fields. Reject a chain not belonging to the active snapshot. A mismatched projection fingerprint must not return `READY`.

- [ ] Write API tests for ready, missing/legacy, unavailable, singleton and wrong-chain cases. Assert the route never calls `generate_cohesion_narrative`, provider plumbing or Tier-2 submission.
- [ ] Implement the route as a persisted projection lookup, with no `extract_cohesion_context()` in the hot path for eligible multi-alarm chains. Any singleton derivation must be bounded and documented.
- [ ] Add `api.chainOverviewCards(chainId, signal)` with a typed response; cache only by exact snapshot/version/chain/projection version, or do not client-cache initially. Avoid a cache keyed only by `chainId`.
- [ ] Let `ChainDetailView` own a separate cards request keyed by snapshot/version/chain. Render its cards from that response; retain the duration card from `analysis`. Unmount/chain switch must abort the old request, and a late result must not populate the next chain.
- [ ] Remove the `AIAdvisorPanel -> onCohesionChange -> cards` dependency. Keep AI narrative loading, provider badge and explicit “Tải lại” local to the narrative section. Pressing “Tải lại” may refresh narrative, not clear or block deterministic cards.
- [ ] Render `PENDING`, `UNAVAILABLE` and `NOT_APPLICABLE` as distinct states. Do not show indefinite “ĐANG TẢI” after a terminal response; poll only `PENDING` at a bounded interval while detail remains open.
- [ ] Run `uv run pytest -q tests/test_api.py tests/test_chain_overview_projection.py` if the new file exists; run `pnpm test -- ChainQualityCards` and `pnpm build` from `services/web`. Expected: all pass.

**Acceptance:** With Ollama intentionally unavailable/slow, persisted card fields appear as soon as the cards GET returns; only the narrative section waits/falls back. F5 and revisiting a chain do not require an AI response to show deterministic cards. Opening a different chain never flashes the previous chain's values.

## Task 3 — Correct chain-exit navigation

**Files:**

- Modify `services/web/src/App.tsx` (`handleClearSelectedChain`)
- Modify `services/web/src/components/SubNavBar.tsx` (label/title if needed)
- Add/update a focused UI test and `services/web/e2e/snapshot-portfolio.spec.ts`

- [ ] Add a failing test for both entry paths: open a chain from Snapshot Overview and from Chains Explorer, click the detail back button, and expect **Snapshot Overview** with no selected chain.
- [ ] Change `handleClearSelectedChain()` to set `currentTab` to `snapshot-overview`, retaining the currently selected snapshot. Update button label/title from “Chains”/“back to Chains Explorer” to a truthful “Snapshot Overview” or concise “Overview”.
- [ ] Confirm a user can still reach Chains Explorer through the top navigation; do not hijack that top-level button.
- [ ] Run the focused Vitest test and Playwright flow; expected back destination is identical from both entry paths.

**Acceptance:** Exiting detail always returns to the active snapshot's Overview, never Chains Explorer or the all-snapshots portfolio.

## Task 4 — Make processed snapshot activation fast and non-blocking

**Files to inspect first:** `services/api/nocpro_api/routes.py:451-477`, `workspace.py:767-840`, `tier1a_coordinator.py:57-145`, `persistence/topology_repository.py:997-1043`, `services/web/src/App.tsx:318-344`, `services/api/nocpro_api/quality_background.py:272-330`.

**Implementation boundary:** Do not introduce a topology edge cap or silently swap in a different topology version. The background quality worker's private `Workspace` must not be directly used as the HTTP active workspace. Store/reuse a validated immutable activation artifact only when its exact snapshot payload digest, config version, topology version and artifact schema version match. A stale/missing artifact enters an explicit cold-activation state and is built off the event loop; only after validation succeeds is it atomically promoted as active. Never show previous-snapshot chains under the newly selected snapshot ID.

- [ ] In an isolated dev instance, capture timings for `POST /snapshots/select`, `GET /chains`, topology hydration, `load_validated_package`, Tier-1A precompute, and browser click-to-Overview. Measure warm revisit and cold activation separately for `real_alarm_ip_demo` and a large IT snapshot. Keep request/identity timestamps together; do not attribute lag from CPU alone.
- [ ] Add failing tests: active same-identity selection performs no re-hydration/reparse; selecting a prepared exact identity activates it without rerunning Tier-1A; changed payload/config/topology version invalidates the artifact; cold activation cannot block unrelated `/health` and catalog GETs; failure leaves the previous active snapshot intact with an explicit error.
- [ ] Implement the narrow same-identity fast path first. Use trusted catalog metadata containing the canonical digest for this check; if that metadata is absent, load and verify the payload before short-circuiting. Do not call `repository.ingest_direct()` or parse the full topology for a verified same-identity no-op. Preserve duplicate-payload integrity checks for any actual activation.
- [ ] Add a versioned prepared-activation cache/artifact for inactive READY snapshots. Populate it during existing background preparation (or a dedicated bounded preparation worker) and promote only matching validated state. Keep a documented memory bound; do not serialize Python objects with unsafe pickle.
- [ ] For a cold miss, return/track an activation job with explicit `PREPARING`, `READY`, `FAILED` states; do CPU-heavy parse/hydration off the API event loop. The UI should show progress immediately and switch Overview only when the new identity is truly active. In `App.tsx`, do not block painting the selection state behind the sequential select+chains waterfall.
- [ ] Add integration tests for rapid A→B→A selection, concurrent Kafka arrival, page refresh during preparation and failed activation. Only the latest user selection may become active; background quality progress must continue independently.
- [ ] Re-run isolated timings. Target: warm same-identity selection under 1 s and non-blocking health/catalog during cold activation; report measured cold time rather than claiming an arbitrary bound. Check CPU/reloader overhead separately from request work.

**Acceptance:** Warm selection does not re-read the full topology or repeat full contract validation. Cold selection presents an immediate truthful preparation state and never freezes unrelated requests. Provenance checks still reject stale state.

## Final verification and handoff

- [ ] Run backend targeted tests, then the full backend suite: `uv run pytest -q` from `nocpro-chain-explain`.
- [ ] Run `pnpm test`, `pnpm lint`, `pnpm build` from `services/web`; run the focused Playwright flows against an isolated backend with Ollama slow/offline.
- [ ] Capture a network waterfall for opening chain `6336199`: `overview-cards` must complete independently of `cohesion-narrative`; no card waits on provider latency.
- [ ] Capture before/after warm and cold snapshot activation timings and state which dataset, topology edge count, active config and cache state were used. Do not generalize an IT snapshot benchmark to all snapshots.
- [ ] Inspect `git diff --check` and the final diff; preserve all pre-existing unrelated changes. Commit only if the user/implementing workflow authorizes commits.

**Not in scope:** changing star thresholds, weakening grounding checks, bulk-calling Ollama for all chains, redesigning the Snapshots portfolio, or replacing evidence with guessed values.
