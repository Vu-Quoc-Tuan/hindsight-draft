# LLM-Primary NocPro Assistant Design

**Date:** 2026-09-07  
**Status:** Proposed for implementation  
**Scope:** NocPro Assistant query execution, project knowledge retrieval, current-view inspection, and typed navigation

## Goal

Make the configured LLM the primary author of Assistant responses. The LLM
interprets the user's intent, selects one or more read-only tools, receives
their structured results, and writes the final natural-language answer.
Deterministic responses remain available only as a safe fallback when the
provider is unavailable or the provider/tool loop cannot produce a valid
grounded answer.

This change does not make the LLM an evidence source. Status, facts, artifact
identity, navigation actions, and all mutations remain controlled by the
backend and the frozen ADR boundaries.

## Non-goals

- Do not let the LLM submit Deep Dive or Counterfactual Review jobs.
- Do not let the LLM apply a recommendation, submit feedback, change config,
  query arbitrary SQL, or construct arbitrary URLs.
- Do not use DOM scraping or screenshots as an authoritative data source.
- Do not let synthetic evidence become production validation.
- Do not let topology navigation become dependency or causal evidence.
- Do not replace deterministic analysis algorithms with model inference.

## Response execution flow

1. The frontend sends the user query and a bounded active-view context.
2. The backend verifies `snapshot_id` and `snapshot_version` before calling the
   provider. A mismatch returns `STALE_CONTEXT` without a provider call.
3. The provider receives the system prompt, bounded recent conversation,
   active context, and the read-only tool schemas.
4. The provider may answer directly only for ordinary conversation that makes
   no project-specific or active-data claim.
5. For project knowledge or active-data questions, the provider calls one or
   more tools.
6. The backend validates every tool name and argument, executes the tool, and
   appends the structured result as a tool message.
7. The provider receives the tool result and writes the final answer. It may
   make another tool call when required, within a strict round limit.
8. The backend preserves authoritative `status`, `fact_refs`, `actions`, and
   `chart_data` from tool results. Only the natural-language `message` is model
   authored.
9. If provider execution fails or no valid final response is produced, the
   existing deterministic router returns the fallback response.

The tool loop is bounded to three provider rounds and four total tool calls.
Only one tool call is executed at a time in model-returned order so results are
deterministic and context can be revalidated between calls.

## Assistant knowledge catalog

Create a versioned JSON catalog owned by `nocpro-chain-explain`, separate from
the Python router. Each knowledge entry contains:

- stable ID, canonical term, aliases, and category;
- short and detailed definitions;
- formula and variable definitions when applicable;
- interpretation of high, low, zero, unavailable, and not-applicable states;
- required inputs and capability gates;
- claims the Assistant must not make;
- related terms;
- source references to methodology, ADRs, config paths, or implementation
  modules.

The initial catalog covers evidence channels, derivation groups, Fit and
MembershipSupport, membership/structural/redundancy roles, descriptors,
contrastive margins, Audit, conductance and cuts, over-merge, attribution and
deletion AUC, evolution/lineage/drift, Similar Chains, Counterfactual Review,
P2 topology hypotheses, provenance, calibration, and public status vocabulary.

Retrieval is deterministic and local:

1. exact stable-ID or alias match;
2. normalized token match over term, aliases, category, and related terms;
3. scored text match over definitions and sources;
4. return at most five complete entries.

Embeddings are not part of the first implementation. The catalog is small,
contains exact mathematical identifiers, and must remain usable without an
external model. An embedding recall layer may be added later without changing
the tool contract, provided every result resolves to catalog entries.

## Tool contracts

### `search_project_knowledge`

Replaces the narrow `explain_metric` behavior. It accepts a query and optional
category, then returns matching catalog entries including formulas,
interpretations, limitations, and sources. It never reads active snapshot data.

### `navigate_workspace`

Supports snapshot overview, chains explorer, timeline, comparison, chain
overview, WHY scopes, members, structure, review, evolution, topology, and
validation. Optional targets include chain, member, pair, chart, Review
candidate, and topology resource IDs. The backend binds every action to the
active snapshot and rejects invalid targets. The frontend revalidates the same
identity before navigation.

### `search_chains`

Searches the active snapshot using exact chain ID and bounded text fields that
the backend already owns. Results are structured and capped. The tool does not
infer symptoms, relations, or causality from names.

### `explain_capability_boundary`

Generalizes the root-cause-only boundary tool. It explains structured reasons
such as `UNAVAILABLE`, `NOT_APPLICABLE`, `NOT_CALIBRATED`,
`INSUFFICIENT_DATA`, missing topology mapping, missing persisted artifacts,
and production-data gates. It may return safe navigation actions to relevant
evidence views.

### `inspect_mapping_capability`

Reads the active mapping and topology capability artifacts. It distinguishes
exact mappings, ambiguous/unmapped records, topology navigation eligibility,
and P2 dependency eligibility. It never substitutes prefix/name heuristics.

### `inspect_current_view`

Generalizes `inspect_chart`. It accepts a view kind and optional selected
entity identifiers. It reads authoritative backend state for the active
snapshot and returns a bounded projection for:

- snapshot overview and chain list;
- selected chain overview and members;
- selected member or Pair WHY;
- persisted Structural Audit and visualization;
- attribution/deletion curves and conductance cuts;
- persisted Counterfactual Review;
- Evolution and lineage;
- topology capability and bounded source navigation;
- validation/operator feedback.

The frontend may send selection hints such as `selected_metric`, member IDs,
pair IDs, chart kind, or candidate ID. These are untrusted identifiers. The
backend verifies them against the active package/artifact before returning
data.

## Request context and conversation

Extend `AssistantContext` with an optional typed `selection` object. It may
identify the metric, member, pair, chart, Review candidate, or topology
resource currently selected in the UI. Existing top-level pair fields remain
temporarily compatible.

Add bounded recent message history to the request. The client sends at most the
last eight user/assistant messages and a fixed character budget. The server
validates roles, lengths, and total size. Tool results are never accepted from
the client.

Changing snapshot, chain, pair, or selected artifact clears the client-side
conversation and aborts in-flight work, preserving the existing stale-context
behavior.

## System prompt policy

The primary system prompt tells the model to:

- respond in the user's language, normally Vietnamese;
- understand intent before selecting tools;
- use project knowledge for terminology, formulas, and methodology;
- call `inspect_current_view` for claims about the screen, selected chain,
  selected metric, or current artifact;
- combine knowledge and active data when the user asks why a displayed metric
  has its current value;
- clearly separate observed fact, deterministic analysis result,
  interpretation, hypothesis, limitation, and unavailable capability;
- preserve proposal-only and synthetic labels;
- avoid unsupported root-cause, causal, validation, or operational claims;
- never claim that navigation or a proposal changed NocPro state;
- say what evidence is missing when a tool reports unavailable;
- return a concise, useful final answer after tool results instead of repeating
  raw JSON.

Knowledge content is retrieved through tools rather than embedding the entire
catalog in every system prompt.

## Grounding and fallback rules

The current exact-text validator is removed from normal tool-result answering,
because it prevents the LLM from doing meaningful explanation. It is replaced
by structural controls:

- the model cannot alter backend `status`, `actions`, `fact_refs`, or artifact
  identity;
- tool outputs are bounded and serialized as untrusted data;
- the final answer must be non-empty and within the output size limit;
- identifiers and numeric values introduced in a project-specific answer must
  appear in the user query, verified context, knowledge result, or tool result;
- forbidden mutation instructions and unsupported causal/production claims
  trigger deterministic fallback;
- provider error categories remain secret-safe and stable.

Fallback occurs only for `NOT_CONFIGURED`, invalid provider configuration,
HTTP/provider error, timeout, oversized/invalid response, tool-loop limit,
unknown or invalid tool calls that cannot be recovered, stale context, or a
grounding-policy violation. A successful provider response is never replaced
merely because it is worded differently from the deterministic draft.

## API response behavior

Keep `nocpro-assistant-v1` response compatibility and add optional diagnostic
fields:

- `response_mode`: `LLM_PRIMARY` or `DETERMINISTIC_FALLBACK`;
- `tools_used`: ordered list of executed tool names;
- `provider_status`: stable provider/fallback reason;
- `model`: configured model or `DETERMINISTIC_EVIDENCE`.

The UI badge derives its label from `response_mode`, not merely from
`provider_status == OK`. This prevents a successful tool-selection call whose
final message is deterministic from being mislabeled as AI-authored.

## Error handling

- Revalidate snapshot identity before every tool execution and before returning
  the final response.
- Convert invalid model-selected arguments to a controlled tool error that the
  model may correct once; never pass them directly to workspace methods.
- Never log credentials, Authorization headers, raw provider exceptions, or
  unrestricted tool payloads.
- Provider and tool failures return stable reason codes.
- Deterministic fallback remains capable of metric lookup, chart inspection,
  safe navigation, chain search, and capability-boundary reporting.

## Verification

Backend tests must prove:

- a configured provider answers directly for ordinary conversation;
- knowledge questions call `search_project_knowledge` and the provider writes
  the final answer from the tool result;
- current-metric questions call both knowledge and current-view tools;
- navigation intent produces a validated snapshot-bound action;
- multi-round OpenAI-compatible and Ollama tool messages use the correct wire
  shape;
- provider failures enter deterministic fallback;
- a valid differently worded grounded answer is retained;
- invented identifiers/numbers, mutation requests, and unsupported causal
  claims fail closed;
- tool-loop and payload bounds are enforced;
- stale contexts never call the provider or execute tools.

Frontend tests must prove:

- typed selection context is sent for the active view;
- bounded history is sent and cleared on context changes;
- `LLM_PRIMARY` and deterministic fallback badges are accurate;
- returned actions are still rejected after snapshot/context changes;
- no provider credential reaches the browser.

A focused browser test must cover: select a chain and metric, ask why the
displayed value has that value, observe knowledge plus current-view tool use,
receive an LLM-authored grounded answer, then change chain during a delayed
request and verify that no stale response is displayed.

## Compatibility and rollout

The existing six public tool responsibilities are migrated without removing
the deterministic fallback path. Existing Assistant response fields remain
valid. New context and response fields are optional during rollout so the
backend and frontend can be deployed together without accepting stale or
untyped data.

The implementation remains inside `nocpro-chain-explain`; it does not import
`nocpro_mock` or depend on the Mock UI at runtime.
