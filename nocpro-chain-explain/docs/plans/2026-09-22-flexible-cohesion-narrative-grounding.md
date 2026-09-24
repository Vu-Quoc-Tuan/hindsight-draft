# Flexible Cohesion Narrative and Exact-Fact Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` when this plan is executed in another session. Implement tasks in order with a focused test and review checkpoint after each task. Preserve the existing dirty worktree; do not reset or commit unrelated changes.

**Goal:** Make the chain investigation narrative easier to read by guiding the LLM to be selective, while preserving enough room for complex evidence and rejecting invented IDs, IPs, measurements, and unsupported causal assertions.

**Architecture:** Keep the existing deterministic evidence extraction and on-demand Cohesion LLM call. Change the prompt's editorial guidance without a word, sentence, or display-length cutoff. Validate exact atomic facts separately from prose semantics: whole IPv4 addresses, domain identifiers, and numeric values must come from the data payload, while observed ordering, topology connectivity, and causal direction retain distinct meanings. A rejected provider response receives the existing single Ollama retry and deterministic fallback. The development-only raw bypass must be disabled for any grounded acceptance test.

**Tech stack:** Python/FastAPI, existing `grounded_llm.py` and `cohesion_advisor.py`, pytest, and a small React badge-label update. No database migration is needed.

## Global constraints

- The user approved a flexible narrative: no fixed character, word, or sentence limit as a style rule; no trimming a valid answer for display.
- Preserve exact identifiers, complete IPv4 addresses, numbers, units, and uncertainty. Do not invent or reassign evidence.
- A structural topology path is not proof of causal direction; temporal precedence is not proof of propagation.
- Keep deterministic assessment, cards, stars, Counterfactual, and cached quality results independent of LLM prose.
- The current `.env` has `NOCPRO_BYPASS_COHESION_GROUNDING=true`; turn it off only when testing the grounded path, and make the active setting visible in the handoff. Do not call a raw-bypass result grounded.
- Preserve unrelated pending work. Before each edit, inspect the target diff and make a narrow patch.
- Existing `_MAX_OUTPUT_CHARS=12_000` is a provider safety ceiling, not an editorial length target. If a Cohesion response exceeds it, reject the whole candidate with a clear status rather than exposing a mid-sentence `[TRUNCATED_BY_SERVER]` fragment.

## Current evidence and design choice

- At design time, `cohesion_advisor.py` prompted Vietnamese `3 đến 5 câu`, and `_briefing_is_concise` checked banned card terms rather than length. The separate system prompt lacked explicit selectivity guidance. The raw bypass returned before this final check.
- `_grounding_failure_reason()` recognizes hyphen/underscore IDs and numbers, but treats an IPv4 address as two decimal fragments. Matching fragments do not prove a complete address appeared in the evidence.
- The numeric allowlist currently includes `facts["instruction"]`; editorial numbers in that instruction can accidentally authorize a number in the answer. The allowlist should derive from evidence-bearing data, not instruction text.
- Phrase matching catches common causal shortcuts but cannot prove that arbitrary natural-language relationships follow from facts. Do not present it as a semantic proof. Add focused relation checks only where the evidence schema gives a deterministic answer, and retain uncertainty wording for hypotheses.

Chosen approach: prompt-level selectivity plus narrow deterministic fact validation. Alternative A, a short output-token/character cap, risks cutting off the weakness or next action. Alternative B, a second LLM judge for every response, increases latency and can disagree with the original model without providing deterministic proof. Neither is needed for this change.

## Task 1 — Prompt for selective, flexible investigation prose

**Files:**

- Modify `services/api/nocpro_api/cohesion_advisor.py:2414` and `services/api/nocpro_api/grounded_llm.py:112`.
- Test `tests/test_cohesion_narrative.py` and `tests/test_grounded_llm.py`.

**Interface:** `generate_cohesion_narrative(..., language="vi")` and `render_grounded(..., purpose="COHESION")` remain unchanged. Only their prompt text changes.

- [ ] Add a prompt-capture test that asserts the Vietnamese instruction asks for one central insight, supporting evidence, the material limitation, and a concrete next check; it must not contain `3 đến 5 câu`, a maximum number of words, or a maximum number of characters. Keep the existing test that accepts a longer grounded answer.
- [ ] Add a system-prompt assertion for the same editorial intent in English, including the requirement to omit repeated dashboard facts but retain necessary detail for complex chains.
- [ ] Run `PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/python -m pytest tests/test_cohesion_narrative.py::test_ai_investigation_accepts_detailed_grounded_prose_without_template tests/test_cohesion_narrative.py::test_ai_investigation_does_not_reject_a_grounded_detailed_answer_by_sentence_count tests/test_grounded_llm.py -q`. Expect the new prompt assertion to fail before the edit.
- [ ] Replace the Vietnamese sentence-count instruction with wording equivalent to: `Viết một nhận định điều tra tập trung vào insight quan trọng nhất. Ưu tiên một đoạn văn gọn, bỏ thông tin lặp lại từ các card; nếu quan hệ phức tạp, dùng đủ câu để giải thích evidence, điểm yếu và bước kiểm tra tiếp theo. Không bỏ dữ kiện thiết yếu chỉ để rút ngắn.` Keep the existing exact-fact, uncertainty, and no-card-recap instructions.
- [ ] Re-run the focused tests. A detailed 7-sentence response that is otherwise grounded must still be accepted.

**Acceptance:** The LLM receives clear brevity guidance without a rigid length threshold. The code does not trim or reject an otherwise valid narrative for having many sentences.

## Task 2 — Validate complete IPs and keep editorial instructions out of fact allowlists

**Files:**

- Modify `services/api/nocpro_api/grounded_llm.py:306-394`.
- Test `tests/test_grounded_llm.py`.

**Interface:** Keep `_grounding_failure_reason(content, draft, facts, fact_refs) -> str | None`. Extract complete dotted-quad candidates and compare each output candidate with the evidence-bearing source as a whole token. Return `IP_MISMATCH` for an unlisted candidate, including an unlisted malformed address-shaped candidate. Exact source literals remain valid because source data may contain version-like dotted strings. Do not authorize an output address merely because its numeric fragments appeared elsewhere.

- [ ] Write failing tests using `draft="Quan sát 10.208.94.101 và 10.209.108.94."` and `facts={"devices": ["10.208.94.101", "10.209.108.94"]}`. `10.208.94.101` must pass. The unlisted `10.208.108.94` composed of familiar numeric fragments must fail as `IP_MISMATCH`. `10.208.94.999` must fail. A device ID such as `ROUTER-01` must continue to use `IDENTIFIER_MISMATCH`.
- [ ] Write a failing test where the only occurrence of `5` is `facts["instruction"]="Viết 5 câu"`; output `Có 5 cảnh báo.` must fail as `NUMBER_MISMATCH`. A number in `facts["investigation_evidence"]` must pass.
- [ ] Run `PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/python -m pytest tests/test_grounded_llm.py -q` and confirm the new tests fail for the intended reason.
- [ ] Introduce an evidence-source builder that excludes editorial keys such as `instruction` from the allowlist but keeps the deterministic draft and evidence-bearing facts. Use that same source for ID, IP, and number checks. Extract and compare IPv4 tokens before generic number tokens; preserve exact IP spelling in prose. Ensure retry feedback for `IP_MISMATCH` tells the model to use only complete addresses from grounding data.
- [ ] Re-run `tests/test_grounded_llm.py`. Check that accepted narrative tests still pass and that percent versus count remains distinct.

**Acceptance:** Rearranging known numeric fragments cannot produce an accepted new IP. Editorial prompt numbers do not become observed counts. Existing identifiers and real measurements remain usable.

## Task 3 — Evidence relationship safeguards without a universal prose ban

**Files:**

- Modify `services/api/nocpro_api/grounded_llm.py:289-394` only where the evidence contract supports a deterministic check.
- Test `tests/test_grounded_llm.py` and `tests/test_cohesion_narrative.py`.

**Interface:** Preserve `_grounding_failure_reason()` statuses and add a distinct `UNSUPPORTED_RELATION` only for a relation contradicted by structured evidence, if such a check can be made from the existing bounded `investigation_evidence` schema. A speculative relationship explicitly marked as a hypothesis may remain in the narrative; it must not be presented as verified topology or causal direction.

- [ ] Keep the existing fixture in which observed order plus an explicit caveat passes. Add a failing fixture for `investigation_evidence.topology.dependency_verified=false` where the answer says topology **confirmed** a directed dependency. The negative form, `topology chưa xác nhận`, must pass.
- [ ] Inspect the exact `investigation_evidence.topology`, temporal and Audit fields used by Cohesion. Implement the directed-dependency check only against the explicit `dependency_verified` field. For free-form shared-cluster or mechanism hypotheses, improve the prompt and document the remaining limitation; do not add a broad blacklist for terms such as `cluster`, `may`, or `hypothesis`.
- [ ] Verify that the retry remains one extra Ollama call and that repeated violation returns deterministic fallback with its reason. A good narrative that explains a plausible relationship and clearly states its limitation must pass.
- [ ] Run the two focused test files, then `git diff --check`.

**Acceptance:** Known overclaims are caught without rejecting useful, qualified investigation insights. The handoff explicitly distinguishes exact-fact checks from semantic certainty.

## Task 4 — Reject pathological output whole, restore grounded demo, and verify end to end

**Files:**

- Modify `services/api/nocpro_api/grounded_llm.py:430-550` and `tests/test_grounded_llm.py` if the Cohesion safety ceiling is currently reachable by a complete response.
- Modify `services/api/nocpro_api/routes.py` to bump `COHESION_NARRATIVE_VERSION`, invalidating stored prose made under the old prompt.
- Modify `services/web/src/GroundedProviderBadge.tsx` to explain the new explicit rejection statuses.
- Local-only `.env` setting for the dev demo, if it is still enabled at execution time.

- [ ] Add a test where complete Cohesion prose exceeds `_MAX_OUTPUT_CHARS`. It must retry/fallback with a clear status and must never return prose containing `[TRUNCATED_BY_SERVER]`.
- [ ] Replace only the Cohesion output truncation path with whole-response rejection. Keep request/response byte ceilings and existing non-Cohesion behavior unchanged unless a focused test proves a shared fix is necessary.
- [ ] Increment the Cohesion narrative cache version so opening a chain under the revised prompt cannot silently reuse a prior DB narrative. Keep the existing exact snapshot/input fingerprint rules.
- [ ] Turn `NOCPRO_BYPASS_COHESION_GROUNDING=false` in the local demo environment after the raw-output investigation is complete. Verify the running process picked up the value; if it did not restart/reload, report that clearly.
- [ ] Run `PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/python -m pytest tests/test_grounded_llm.py tests/test_cohesion_narrative.py -q`, then the affected API tests. Run `git diff --check`.
- [ ] When a live dev API is reachable, request one known chain with a persisted Deep Dive and capture: provider status, whether the answer is complete, exact IP/ID/number grounding, and whether the prose includes insight, limitation, and next check. Compare raw and grounded output only on the same snapshot/chain/fingerprint. Do not claim live verification if the API is unavailable.

**Acceptance:** A grounded answer is complete and readable; an oversized pathological answer is rejected as a whole. The live demo no longer displays `AI RAW · GROUNDING TẮT` once the API has reloaded the local flag.

## Final review

- [ ] Review the target diff to ensure no star, Counterfactual, quality pipeline, or frontend navigation code changed.
- [ ] Check the four failure classes independently: invented ID, invented whole IPv4, unsupported number or unit, unsupported relation. Keep each provider status explicit in logs and fallback behavior.
- [ ] Report tests and live evidence separately. If a free-form semantic relationship cannot be proven from structured facts, state that as an intentional limit rather than calling the validator complete.

## Execution note, 2026-09-22

The implementation in this workspace covers the prompt, complete dotted-quad matching, numeric-source cleanup, the explicit unverified-directed-topology check, whole-response oversized fallback, new badge statuses, and a Cohesion cache-version bump. The local demo flag is set to `false`. Focused backend/API tests and the web build passed at the last verification checkpoint; rerun the exact commands after any later edits. A live browser/API probe was not possible in the available sandbox because no API or Vite process was running there; that runtime check remains for the active dev-demo environment.
