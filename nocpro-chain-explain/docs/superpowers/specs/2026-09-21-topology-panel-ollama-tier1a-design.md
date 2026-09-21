# Topology Panel, Ollama Response, and Tier-1A Startup Design

## Scope

This change addresses three observed problems without changing analysis semantics:

1. The topology focus indicator duplicates the alarm panel controls and consumes header space.
2. The node panel header renders verbose role and hop descriptions that wrap badly at its fixed width.
3. A valid Ollama configuration can be reported as `INVALID_RESPONSE`, and initial snapshot activation can race the recovery worker for the Tier-1A claim.

## Topology interaction

- Remove the `Focus: ... / Thoát Focus` chip from the topology header.
- Clicking a node continues to focus its immediate connected neighborhood and open the node alarm panel.
- The panel remains portaled into `#canvas-bg` and constrained to the canvas bounds.
- The panel header shows only the node name and a compact hop label: `Seed`, `1-Hop`, or `2-Hop`.
- Alarm-count badges remain unchanged.
- The panel X button, footer Close button, and Escape key all close the panel and clear the focused node and hovered edge.

## Grounded Ollama request

The current limits are individually bounded but can exceed the 32 KB total after serialization. The resulting local `ValueError` is currently mislabeled as an invalid provider response.

- Build the request within a total byte budget.
- Preserve the system prompt, deterministic draft, and structured facts first.
- Add fact references in order only while the serialized request remains within the total budget.
- If the mandatory core alone exceeds the limit, return `REQUEST_TOO_LARGE`; do not classify it as a provider response error.
- Native Ollama requests set `think: false` to bias reasoning models toward a concise final answer.
- If Ollama returns HTTP 200 with an incomplete response or empty `message.content`, retry once with the same bounded payload. A second invalid response remains fail-closed and returns the deterministic draft.
- Never use `message.thinking` as the published narrative, and never log provider bodies, authorization headers, or credentials.
- Preserve grounding validation after a valid textual response is obtained.

## Tier-1A startup ordering

The lifespan currently starts the recovery loop before configured initial snapshot activation. Both paths may attempt to claim the same newly completed snapshot.

- Hydrate any already-active snapshot first.
- Perform configured initial snapshot activation or default auto-seeding next.
- Start the background recovery loop only after this activation step finishes.
- Keep activation failure fail-safe: log it, leave health available, and allow the subsequently started recovery worker to process pending work.
- Do not weaken repository claim or lease ownership rules.

## Verification

- Unit-test request budgeting, correct `REQUEST_TOO_LARGE` classification, Ollama `think: false`, single retry, and rejection after the retry.
- Unit-test startup ordering so recovery cannot claim the initial snapshot before explicit activation.
- Update topology component and browser tests to confirm the header chip is absent, the panel label is compact, and X clears both the panel and Focus.
- Run targeted backend tests, all frontend unit tests, TypeScript production build, lint, and the topology Chromium E2E.

## Non-goals

- No change to topology graph expansion, chain scoring, grounding rules, root-cause semantics, provider credentials, or the 32 KB safety ceiling.
- No switch to the OpenAI-compatible Ollama endpoint.
