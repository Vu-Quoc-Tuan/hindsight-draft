# Grounded LLM Rendering for Advisor and Assistant

## Status

Approved scope: use the configured server-side LLM for both the chain AI
Advisor and the free-text NocPro Assistant, while preserving ADR-0024.

## Objective

Add optional natural-language rendering without making the model a source of
evidence, analysis, navigation targets, recommendations, or operational
actions. Removing or disabling the provider must leave every core Explain,
Audit, Review, topology, and navigation capability intact.

## Approaches considered

1. **Grounded renderer after deterministic execution (selected).** Existing
   code resolves intent, validates snapshot context, retrieves facts, and
   constructs typed actions. The LLM may rewrite only the bounded message from
   those facts. This retains deterministic behavior and permits a safe
   fallback.
2. **LLM intent and tool router.** The model chooses searches and navigation
   actions. Rejected because model output could escape the current typed,
   snapshot-bound action contract and make behavior provider-dependent.
3. **Advisor-only LLM.** The Assistant remains fully deterministic. Rejected
   because the approved product scope includes natural-language Assistant
   replies, and the same grounded renderer can safely serve both surfaces.

## Architecture

Introduce one server-side grounded narrative provider with a small interface:

```text
deterministic facts + deterministic draft + rendering context
                            |
                            v
                 grounded LLM renderer
                            |
             valid narrative or provider failure
                            |
          LLM narrative / deterministic fallback
```

The Advisor continues to extract structured Tier-1B and persisted Review facts.
The Assistant continues to run its semantic registry, active-snapshot checks,
chain search, pair validation, and typed navigation generation before invoking
the renderer. The model receives neither authority nor an API for starting
jobs, changing evidence, applying recommendations, submitting feedback, or
mutating NocPro.

## Provider configuration

The API service reads only server-side configuration:

```text
AI_API_KEY
AI_BASE_URL
AI_MODEL
```

The browser never receives the key. Docker passes these variables only to the
API container. The configured endpoint uses the existing OpenAI-compatible
`/chat/completions` contract. Provider timeout and bounded response size are
fixed implementation safeguards, not analysis thresholds.

Missing configuration is a normal unavailable provider state. Invalid HTTP,
timeout, malformed JSON, an empty response, or rejected content must not fail
the API request; each falls back to the deterministic message.

## Grounding and safety contract

The provider receives a bounded JSON projection containing only facts already
produced by the deterministic system, stable fact references, and the existing
deterministic draft. Untrusted alarm labels, descriptors, and other source data
are explicitly delimited as data rather than instructions.

The renderer may:

- translate, summarize, and improve readability;
- explain the meaning and limitations of referenced metrics;
- describe persisted Review proposals as proposals.

The renderer may not:

- introduce an alarm, device, relation, score, role, or recommendation absent
  from the supplied facts;
- infer root cause, causal direction, topology dependency, or missing taxonomy;
- change status, availability, hard-gate, Pareto, validation, or calibration
  results;
- create URLs, tool calls, actions, job submissions, feedback, or mutations;
- treat `UNAVAILABLE` as neutral or zero.

Assistant `actions` and `fact_refs` always come unchanged from deterministic
code. Only the `message` field is eligible for rendering. Advisor
`grounded_claims`, Review status, and Review reason likewise remain unchanged.

## Output and provenance

Existing response contracts remain backward compatible. Provider provenance is
explicit:

- provider used successfully: configured model plus `provider_status=OK`;
- missing configuration: deterministic model plus
  `provider_status=NOT_CONFIGURED`;
- runtime/provider failure: deterministic model plus a stable non-secret error
  category;
- intentionally ineligible response, including stale context: deterministic
  response with `provider_status=NOT_APPLIED` where surfaced.

Raw provider error bodies are logged only in sanitized form and are not exposed
to the browser. Secrets are never logged or serialized.

## Assistant flow

1. Validate the active snapshot identity.
2. Resolve the bounded deterministic intent and facts.
3. Construct and validate typed actions.
4. Render only the deterministic response message when eligible.
5. Return the original deterministic message if rendering is unavailable or
   invalid.

`STALE_CONTEXT` and input-validation failures do not invoke the provider.
Unknown questions remain bounded by the registry and available context; the LLM
does not become an unrestricted knowledge or RCA endpoint.

## Advisor flow

1. Load the exact Tier-1B analysis and compatible persisted Review result.
2. Project structured facts and stable grounded claims.
3. Build the deterministic narrative.
4. Ask the provider to render that projection.
5. Preserve the deterministic narrative on any provider failure.

No API GET or POST causes Review execution or NocPro mutation.

## Verification

Tests must prove:

- successful provider rendering for Advisor and Assistant with a mocked HTTP
  endpoint;
- exact preservation of deterministic `actions`, `fact_refs`, statuses, Review
  facts, and grounded claims;
- no provider call for stale/invalid context;
- deterministic fallback for missing key, timeout, HTTP error, malformed or
  empty response;
- provider errors do not reveal secrets;
- Docker configuration passes credentials only to the API service;
- frontend renders provider provenance and never contains an API credential;
- existing Explain, Audit, Review, topology, H, T_delay, and anti-dense-scan
  regressions remain unchanged.

An optional live provider smoke test may be run with the configured local
secret, but it is not a deterministic CI requirement.

## Non-goals

- No LLM-based evidence channel, Role/Audit statistic, RCA, taxonomy inference,
  topology promotion, recommendation generation, or validation verdict.
- No change to H, T_delay, Counterfactual Review v1, P2, thresholds, or
  production calibration.
- No client-side provider invocation and no mutation/apply workflow.
