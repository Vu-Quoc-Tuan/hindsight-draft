# UI and Backend Integration Design

## Goal

Turn the `feat/code_ui` presentation shell into an evidence-faithful UI. Every production-facing metric, status, graph, timeline and operator action must come from a typed API artifact or render as loading, unavailable, or not yet evaluated.

## Global invariants

- Missing data is never replaced with a favorable, adverse, or neutral number.
- UI context identity is `(snapshot_id, snapshot_version, chain_id, config_version)` where applicable.
- A response from an older context must not render under a newer selection.
- Snapshot-level pages must not start Tier-2 work or perform dense per-chain analysis.
- Operator feedback is durable feedback on a persisted Review candidate. It is not Apply, network mutation, multi-reviewer consensus, rollback, or an SLA guarantee.
- IT source relations and IP adjacency remain navigation data. The UI must not promote them to causal or operational dependency semantics.
- Assistant inspection remains read-only and must not submit Deep Dive or Review jobs.

## Data flow

### Application context

The application obtains the active snapshot identity from `GET /chains`. A selected chain starts an analysis request keyed by the full current context. Until the matching response arrives, chain-level views render a shared loading state. A failed request renders an unavailable state and never reuses the previous chain's analysis.

The header displays the backend identity. Static dataset choices may select a topology navigation profile, but they must not pretend that a different alarm snapshot has been activated. Persisted snapshot selection requires a separate, snapshot-scoped API contract and is not implemented as a label-only switch.

### Snapshot views

`ChainsExplorer` displays only fields present in `ChainSummary`. Conductance, weak-member counts and cut status are shown only when a compatible persisted artifact is explicitly projected; otherwise the UI displays `Audit on demand`.

`MultiChainTimeline` consumes chain-level `start_time`, `end_time`, and `duration_seconds`, computed exactly from canonical member timestamps. It renders unavailable when these are absent. It must not fetch every chain's Tier-1B analysis.

`CompareChains` compares factual fields available for both chains. It does not assert cross-chain causality, upstream direction, topology sharing or a delay unless a future typed artifact explicitly establishes those semantics.

### Chain views

Pair WHY calls `GET /chains/{chain_id}/pairs/{alarm_a}/{alarm_b}` for two distinct selected members and renders channel availability, provenance and scores without null coercion.

Audit uses the persisted Deep Dive job result. Existing public structural summary, best cut, attribution and deletion-curve fields can render immediately. A dynamic graph requires a new bounded persisted visualization read-model; internal graph existence alone is not a public API contract. No graph placeholder is rendered as a live result.

Recommendations use Counterfactual Review v1 as the only source of candidate counts, frontier state, metrics and feedback identity. Evolution timeline and DAG are two projections of the same persisted Evolution response.

Topology renders only the returned topology projection and mapping diagnostics. A missing payload is loading, and an unavailable response remains unavailable. No fabricated CMDB provenance, mapping ratio, cut, root-cause or dependency semantics is allowed.

### Operator feedback

Feedback requires a persisted Review job ID and candidate ID. APPROVED or REJECTED plus operator ID and an optional reason are submitted through the existing feedback API. The response is reloaded from persistence and shown as operator feedback history. If no compatible Review candidate exists, controls are unavailable.

## API additions

- Extend `ChainSummaryView` with nullable `start_time`, `end_time`, and `duration_seconds`, derived from canonical snapshot members without Tier-2 analysis.
- Reuse existing Pair WHY, Deep Dive job, Evolution, Counterfactual Review and feedback endpoints.
- Do not add global snapshot switching in this change. A later snapshot catalog must preserve explicit snapshot/version identity and concurrent request safety.
- Do not expose raw Audit graph until a bounded immutable visualization artifact and size policy are defined.

## Error and loading states

- `checking`: connection status is unknown; no synced claim.
- `online`: only the API health is established. `STREAM SYNCED` is shown only when a current snapshot has loaded successfully.
- `offline`: data-backed dashboard values are unavailable; no silent demo substitution.
- Per-artifact errors are scoped to the selected snapshot/chain and do not poison unrelated navigation.

## Verification

- Unit tests cover null metrics, chain context switching, exact timeline projection, unavailable artifacts, Pair WHY selection and durable feedback payloads.
- Browser tests cover delayed A-to-B chain responses, API failure, equal chain IDs across snapshot versions, Evolution unavailable, feedback reload and mobile width.
- Full frontend tests, lint, build and `git diff --check` must pass.
- Backend schema/serializer tests pin exact temporal summary values and prevent Tier-2 work in `GET /chains`.

## Deferred by explicit boundary

- Cross-chain causal inference.
- Global mutable snapshot switching.
- Dense all-chain Audit precomputation.
- Audit force-layout until a bounded public graph artifact exists.
- Apply/rollback/provisioning and multi-reviewer consensus.

