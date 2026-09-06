# Ollama Grounded Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit native Ollama chat protocol to the grounded narrative renderer while preserving the existing OpenAI-compatible protocol and deterministic fallback.

**Architecture:** Keep one grounding and result boundary, but select a small request/response codec from `AI_PROVIDER_PROTOCOL`. `OPENAI_COMPATIBLE` remains the default; `OLLAMA` uses `${AI_BASE_URL}/chat`, disables streaming, and accepts only the final `message.content` field.

**Tech Stack:** Python 3.12, stdlib `urllib.request`, pytest, Docker Compose, React/TypeScript/Vitest.

## Global Constraints

- LLM output may replace narrative text only; deterministic facts, statuses, references, and typed actions remain authoritative.
- `AI_PROVIDER_PROTOCOL` is explicit. Do not infer it from hostname, URL, or model ID.
- Supported values are `OPENAI_COMPATIBLE` and `OLLAMA`; omitted means `OPENAI_COMPATIBLE` for backward compatibility.
- Ollama requests use `stream=false`; streaming NDJSON is not parsed by this adapter.
- Provider errors and malformed responses return the exact deterministic draft with a stable non-secret status.
- Never log or serialize the API key or raw provider error body.
- Do not modify H, T_delay, Role, Audit, Review, topology, thresholds, or production semantics.

---

### Task 1: Native Ollama request/response codec

**Files:**
- Modify: `services/api/nocpro_api/grounded_llm.py`
- Modify: `tests/test_grounded_llm.py`

**Interfaces:**
- Consumes: `AI_PROVIDER_PROTOCOL`, `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`.
- Produces: the existing `GroundedRenderResult` from `render_grounded(...)` for either supported wire protocol.

- [x] **Step 1: Add failing protocol tests**

Add a mocked Ollama success case that configures:

```python
monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
monkeypatch.setenv("AI_BASE_URL", "https://ollama.com/api")
monkeypatch.setenv("AI_MODEL", "gpt-oss:120b")
```

The patched `urlopen` must assert:

```python
assert request.full_url == "https://ollama.com/api/chat"
assert payload["model"] == "gpt-oss:120b"
assert payload["stream"] is False
```

Return:

```python
{"message": {"role": "assistant", "content": "Grounded Ollama text"}, "done": True}
```

Assert `provider_status == "OK"`, `used_provider is True`, and the final content is used. Add malformed cases for `done=false`, missing `message`, empty content, and a test proving an unsupported protocol does not call the network and returns `INVALID_CONFIGURATION`.

- [x] **Step 2: Run the focused tests and confirm failure**

Run:

```text
.venv/bin/pytest tests/test_grounded_llm.py -q
```

Expected: the new Ollama success test fails because the current renderer calls `/chat/completions` and parses `choices`.

- [x] **Step 3: Implement explicit codecs**

In `grounded_llm.py`, normalize the configured protocol once:

```python
protocol = os.environ.get("AI_PROVIDER_PROTOCOL", "OPENAI_COMPATIBLE").strip().upper()
if protocol not in {"OPENAI_COMPATIBLE", "OLLAMA"}:
    return _fallback(draft, "INVALID_CONFIGURATION")
```

Build the same bounded `messages` grounding block for both protocols. Use:

```python
if protocol == "OLLAMA":
    url = f"{base_url}/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 1200},
    }
else:
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 1200,
    }
```

Parse Ollama only when `done is True` and `message.content` is a non-empty string. Ignore `thinking` and `tool_calls`. Preserve the existing response-size bounds and fallback statuses.

- [x] **Step 4: Run focused tests**

Run:

```text
.venv/bin/pytest tests/test_grounded_llm.py tests/test_ai_advisor.py -q
```

Expected: all provider, Advisor, and Assistant cases pass.

- [x] **Step 5: Commit the codec**

```text
git add services/api/nocpro_api/grounded_llm.py tests/test_grounded_llm.py
git commit -m "feat: support ollama grounded rendering"
```

---

### Task 2: Configuration, presentation, and live verification

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `services/web/src/GroundedProviderBadge.tsx`
- Modify: `services/web/src/AIAdvisorPanel.test.tsx`
- Modify: `IMPLEMENTATION_STATUS.md`
- Modify locally, not committed: `.env`

**Interfaces:**
- Consumes: the Task 1 protocol status and existing `provider_status` public field.
- Produces: server-only deploy configuration, a safe invalid-configuration label, and verified Ollama runtime behavior.

- [x] **Step 1: Add the failing presentation/config assertions**

Extend the panel test with `provider_status="INVALID_CONFIGURATION"` and assert the UI renders `Deterministic fallback · Invalid provider configuration` without exposing environment names or credentials. Assert Compose passes `AI_PROVIDER_PROTOCOL` only to the API service.

- [x] **Step 2: Add server-only protocol configuration**

Document:

```text
AI_PROVIDER_PROTOCOL=OPENAI_COMPATIBLE
```

in `.env.example` with allowed values. Pass it to the API service in Compose:

```yaml
AI_PROVIDER_PROTOCOL: "${AI_PROVIDER_PROTOCOL:-OPENAI_COMPATIBLE}"
```

Add `INVALID_CONFIGURATION` to the badge's safe label map. For the local Ollama Cloud smoke test, set only the non-secret `.env` protocol field to `OLLAMA`; do not modify or print the key.

- [x] **Step 3: Update status documentation**

Record that mocked Ollama protocol correctness is tested and distinguish that from a live-provider smoke result. Do not claim production validation from this rendering test.

- [x] **Step 4: Run full deterministic verification**

Run:

```text
.venv/bin/pytest tests -q
npm test -- --run
npm run lint
npm run build
docker compose config --quiet
git diff --check
```

Expected: backend/frontend tests and build pass. Existing unrelated lint warnings may remain warnings but no new warning may be introduced.

- [x] **Step 5: Run one live Ollama smoke test**

Load only the three AI values plus protocol from the local `.env`, invoke `render_grounded(...)` with synthetic bounded facts, and print only configured model, `provider_status`, `used_provider`, and safe rendered text. Never print the key or raw error body.

Expected:

```text
provider_status=OK
used_provider=true
model=gpt-oss:120b
```

If access fails, preserve deterministic fallback and report the exact sanitized HTTP category without calling the feature PASS.

- [x] **Step 6: Commit configuration and status**

```text
git add .env.example docker-compose.yml services/web/src/GroundedProviderBadge.tsx services/web/src/AIAdvisorPanel.test.tsx IMPLEMENTATION_STATUS.md
git commit -m "chore: configure ollama grounded provider"
```

- [x] **Step 7: Final cleanliness check**

Run `git status --short`, `git diff --check`, and a frontend source scan for `AI_API_KEY` or `VITE_AI_*`. Expected: feature worktree clean, no browser-side secret configuration, and no temporary smoke-test file.

---

### Task 3: Preserve the deterministic draft language

**Files:**
- Modify: `services/api/nocpro_api/grounded_llm.py`
- Modify: `tests/test_grounded_llm.py`

- [x] **Step 1: Pin the presentation instruction**

Assert that the provider system message requires the renderer to preserve the
primary language of the deterministic draft, keep Vietnamese drafts in
Vietnamese, and avoid implicit translation.

- [x] **Step 2: Confirm the focused test fails, then implement the prompt rule**

Add only a presentation constraint. Do not change facts, actions, evidence,
fallback behavior, protocol codecs, or any deterministic decision semantics.

- [x] **Step 3: Verify with mocked and live Ollama responses**

Run the focused provider tests, then a live Vietnamese smoke test that checks
both provider status and the actual language of the rendered message.

- [x] **Step 4: Run the full regression and commit**

Run backend tests, frontend tests/lint/build, Compose validation, and
`git diff --check`, then commit the focused change.
