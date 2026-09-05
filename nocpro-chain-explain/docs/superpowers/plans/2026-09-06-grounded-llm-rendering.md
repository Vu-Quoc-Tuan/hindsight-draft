# Grounded LLM Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use the configured server-side OpenAI-compatible LLM to render grounded Advisor and Assistant narratives while preserving deterministic facts, statuses, references, and typed actions.

**Architecture:** Add one isolated provider adapter that accepts a deterministic draft plus bounded structured facts and returns either a rendered message or a stable fallback state. Advisor and Assistant keep all existing deterministic analysis, routing, context validation, and action generation; only their text fields are replaceable by the provider.

**Tech Stack:** Python 3.12, stdlib `urllib.request`, FastAPI/Pydantic, pytest/httpx2, React/TypeScript/Vitest, Docker Compose.

## Global Constraints

- LLM use remains optional and server-side under ADR-0024.
- `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL` are never exposed to the browser or logs.
- The LLM cannot create facts, scores, statuses, recommendations, validation verdicts, URLs, tools, or actions.
- Provider failure preserves the existing deterministic result and never fails the core request.
- Do not change H, T_delay, Role, Audit, derivation groups, Counterfactual Review v1, topology semantics, or thresholds.
- Do not add or commit the existing untracked `nocpro-chain-explain/ui/` directory.

---

### Task 1: Server-side grounded renderer

**Files:**
- Create: `services/api/nocpro_api/grounded_llm.py`
- Test: `tests/test_grounded_llm.py`

**Interfaces:**
- Consumes: `draft: str`, `facts: dict[str, Any]`, `fact_refs: Sequence[str]`, `purpose: Literal["ADVISOR", "ASSISTANT"]`.
- Produces: `GroundedRenderResult(message: str, model: str, provider_status: str, used_provider: bool)` through `render_grounded(...)`.

- [ ] **Step 1: Write failing provider tests**

Add tests with a patched `urllib.request.urlopen` for successful OpenAI-compatible JSON, missing configuration, HTTP failure, malformed/empty content, bounded input, and stable non-secret provider states. Assert the request contains the deterministic draft and facts but no API key in its JSON body.

```python
def test_renderer_uses_configured_provider_without_changing_grounding(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "test-secret")
    monkeypatch.setenv("AI_BASE_URL", "https://provider.invalid/v1")
    monkeypatch.setenv("AI_MODEL", "test-model")
    result = render_grounded(
        draft="Deterministic draft",
        facts={"status": "AVAILABLE", "member_count": 2},
        fact_refs=["analysis:C1"],
        purpose="ADVISOR",
    )
    assert result.message == "Rendered grounded text"
    assert result.provider_status == "OK"
    assert result.used_provider is True
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `.venv/bin/pytest tests/test_grounded_llm.py -q`

Expected: collection fails because `nocpro_api.grounded_llm` does not exist.

- [ ] **Step 3: Implement the provider adapter**

Implement immutable configuration/result values, environment parsing without loading client configuration, an OpenAI-compatible POST to `${AI_BASE_URL}/chat/completions`, a strict ADR-0024 system prompt, bounded JSON facts/draft, response parsing, and stable failure categories:

```python
@dataclass(frozen=True)
class GroundedRenderResult:
    message: str
    model: str
    provider_status: str
    used_provider: bool

def render_grounded(*, draft: str, facts: dict[str, Any],
                    fact_refs: Sequence[str], purpose: RenderPurpose,
                    timeout_seconds: float = 8.0) -> GroundedRenderResult:
    ...
```

Use `DETERMINISTIC_EVIDENCE` plus `NOT_CONFIGURED`, `HTTP_ERROR`, `TIMEOUT`, `INVALID_RESPONSE`, or `PROVIDER_ERROR` for fallback. Never serialize raw exception/provider text.

- [ ] **Step 4: Run provider tests**

Run: `.venv/bin/pytest tests/test_grounded_llm.py -q`

Expected: all tests pass without a live network call.

---

### Task 2: Ground the chain AI Advisor

**Files:**
- Modify: `services/api/nocpro_api/ai_advisor.py`
- Modify: `services/api/nocpro_api/routes.py`
- Test: `tests/test_ai_advisor.py`

**Interfaces:**
- Consumes: Task 1 `render_grounded(...)` and the existing `extract_grounded_claims(...)` projection.
- Produces: the existing `AISuggestionResult` contract, with provider model/status when rendering succeeds and deterministic content on failure.

- [ ] **Step 1: Add failing Advisor tests**

Patch the provider boundary and assert:

```python
assert result.narrative == "Rendered grounded advisor text"
assert result.model == "configured-model"
assert result.provider_status == "OK"
assert result.grounded_claims == original_claims
assert result.review_status == "AVAILABLE"
```

Also assert missing/error provider keeps the exact deterministic narrative and the route does not block the event loop by running the synchronous provider call through `asyncio.to_thread`.

- [ ] **Step 2: Run the Advisor tests and verify the new cases fail**

Run: `.venv/bin/pytest tests/test_ai_advisor.py -q`

Expected: new provider assertions fail while existing deterministic tests pass.

- [ ] **Step 3: Integrate rendering after deterministic fact extraction**

Keep `extract_grounded_claims` and `build_deterministic_narrative` authoritative. Pass the structured projection, claims, Review status, and Review reason to `render_grounded`; copy only its `message`, `model`, and `provider_status` into `AISuggestionResult`.

Change the FastAPI route to execute the blocking provider adapter in a worker thread:

```python
suggestion = await asyncio.to_thread(
    generate_ai_suggestion,
    chain_id=chain_id,
    analysis=analysis,
    review_result=review_result,
    review_status=review_status,
    review_reason=review_reason,
)
```

- [ ] **Step 4: Run Advisor tests**

Run: `.venv/bin/pytest tests/test_ai_advisor.py -q`

Expected: all Advisor/API cases pass with mocked provider behavior.

---

### Task 3: Ground Assistant messages without granting tool authority

**Files:**
- Modify: `services/api/nocpro_api/assistant.py`
- Modify: `services/api/nocpro_api/routes.py`
- Modify: `services/api/nocpro_api/schemas.py`
- Modify: `services/web/src/types.ts`
- Test: `tests/test_ai_advisor.py`

**Interfaces:**
- Consumes: existing `answer_query(...)` deterministic response and Task 1 `render_grounded(...)`.
- Produces: the existing Assistant v1 response plus additive `model` and `provider_status` fields.

- [ ] **Step 1: Add failing Assistant provider tests**

For a valid definition, chain search, and navigation request, assert the rendered message is used while `status`, `fact_refs`, and `actions` are byte-for-byte equal to the deterministic response. Assert stale context and input validation never invoke the provider. Assert provider failure returns the original deterministic message.

```python
assert rendered["message"] == "Rendered assistant text"
assert rendered["actions"] == deterministic["actions"]
assert rendered["fact_refs"] == deterministic["fact_refs"]
assert rendered["provider_status"] == "OK"
```

- [ ] **Step 2: Run the Assistant tests and verify failure**

Run: `.venv/bin/pytest tests/test_ai_advisor.py -q`

Expected: additive provider fields/rendering tests fail before integration.

- [ ] **Step 3: Add a post-routing render function**

Keep `answer_query` deterministic. Add a function that refuses rendering for `STALE_CONTEXT`, calls the grounded renderer for eligible results, and copies only the rendered message/provider provenance:

```python
def render_answer(query: str, context: dict[str, Any],
                  deterministic: dict[str, Any]) -> dict[str, Any]:
    ...
```

The route runs this function in `asyncio.to_thread`. Extend `AssistantResponseView` and the TypeScript type with:

```text
model: string
provider_status: string
```

No model output is parsed as an action, reference, status, or target.

- [ ] **Step 4: Run backend Assistant tests**

Run: `.venv/bin/pytest tests/test_ai_advisor.py -q`

Expected: all Assistant action/context tests and provider tests pass.

---

### Task 4: Deployment, UI provenance, and regression verification

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `services/web/src/AIAdvisorPanel.tsx`
- Modify: `services/web/src/NocProAssistantPanel.tsx`
- Modify: `services/web/src/AIAdvisorPanel.test.tsx`
- Modify: `services/web/src/NocProAssistantPanel.test.tsx`
- Modify: `IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Consumes: API provider status/model fields from Tasks 2 and 3.
- Produces: visible but non-alarming provider provenance and server-only Docker configuration.

- [ ] **Step 1: Write failing UI tests**

Assert successful LLM rendering displays `AI-assisted · <model>`, fallback displays `Deterministic fallback`, and no HTML contains `AI_API_KEY`, the configured credential, an Apply control, or causal wording.

- [ ] **Step 2: Run Vitest and verify the new cases fail**

Run: `npm test -- --run`

Expected: provider provenance assertions fail before UI integration.

- [ ] **Step 3: Add deployment and presentation wiring**

Document only variable names/placeholders in `.env.example`. Pass `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL` to the API service in Compose. Do not create `VITE_AI_*` variables. Update both panels to render safe model/provider provenance without exposing provider errors or secrets.

Update `IMPLEMENTATION_STATUS.md` to distinguish optional grounded LLM rendering from deterministic core correctness and to state that LLM does not fill H, T_delay full-chain, taxonomy, topology, or ground-truth gaps.

- [ ] **Step 4: Run focused and full verification**

Run:

```text
.venv/bin/pytest tests/test_grounded_llm.py tests/test_ai_advisor.py -q
.venv/bin/pytest tests -q
npm test -- --run
npm run lint
npm run build
git diff --check
```

Expected: all available suites pass; live provider access is not required.

- [ ] **Step 5: Optional configured-provider smoke test**

With the existing local `.env`, call the Advisor and Assistant through the API without printing any secret. Verify `provider_status=OK`, a configured model name, typed actions unchanged, and no causal/mutation claim. If network/provider access is unavailable, report the smoke test as `NOT_RUN` or `UNAVAILABLE`, not PASS.

- [ ] **Step 6: Review scope and status**

Run `git status --short` and confirm the change set excludes `nocpro-chain-explain/ui/`. Report exact tests, live-provider status, and the unchanged production/data limitations before any implementation commit.
