# Audit Hardening Design

## Goal

Close the verified technical gaps found in the repository audit without changing
the frozen Explain, Audit, Counterfactual, topology-P2, H, or T_delay semantics.

## Scope

The work is split into four independently reviewable changes:

1. **Mock input and presentation boundary.** Every browser-controlled file
   reference resolves to an approved final path; sequence child names and golden
   fixture directories cannot escape the allowlist. Request payloads must be a
   bounded JSON object and chunk sizes must be validated before use. Mock preview
   data is rendered as text, never interpolated into HTML.
2. **Assistant read-only and snapshot contract.** Assistant actions carry the
   snapshot identity they were generated for, targets are validated before the
   action is returned and again before navigation, and Assistant navigation to
   Review only opens an existing artifact/status view. It must never implicitly
   submit a Review job. Concurrent queries cannot replace a newer result with an
   older response.
3. **Benchmark evidence integrity.** Closure projection accepts a measurement
   only when all timing metadata is finite, non-negative, internally consistent,
   and backed by an explicit sample count/reliability field. Missing metadata is
   `NOT_RUN`, never fabricated defaults.
4. **Documentation and regression evidence.** Status and README accurately
   distinguish current capability, fresh test evidence, prior runtime evidence,
   and production/data gates. Tests reproduce each fixed boundary.

## Non-goals

- No new evidence channel, Counterfactual operation, production threshold,
  taxonomy inference, topology P2 promotion, or dense pairwise fallback.
- No automatic Review/Deep Dive analysis caused by Assistant navigation.
- No claim that synthetic fixtures or synthetic operator feedback establish
  production calibration or ground truth.
- No LLM integration in this change set.

## Design

### Mock boundary

`build_package_from_request()` resolves the *final* sequence file and golden
fixture directory through one allowlisted resolver. A child path must be a
relative plain filename; absolute paths, path traversal, and resolved symlink
escapes are rejected. The HTTP body reader returns only a JSON object. Numeric
fields go through existing bounded integer validation before preview/publish.

The static Mock page keeps its layout but creates table/log text nodes with
`textContent`. It may use literal HTML for fixed UI fragments only; fields from
alarms, chains, previews, or server errors are never concatenated into
`innerHTML`.

### Assistant contract

The request context must contain the active snapshot identity. The API returns a
typed, in-app action containing the same identity plus an action-specific target.
The API validates a requested chain/member/pair against that identity before
returning an action. The client rejects actions whose identity differs from the
currently displayed `ChainList`.

The Review page gets an explicit read-only mode. Assistant navigation uses that
mode, so a missing latest Review remains an unavailable/not-run view instead of
calling `submitReview`. Direct operator navigation retains its current explicit
Review workflow. Pair WHY actions select an already validated pair instead of
only opening its tab.

### Benchmark contract

A closure measurement has positive repetitions, finite non-negative timing,
`p50 <= p95`, and an explicit boolean reliability flag. The projection never
uses implicit `20` repetitions or implicit `true` reliability. If a required
field is absent or invalid, the operation is `NOT_RUN` with
`INVALID_OR_INCOMPLETE_BENCHMARK_EVIDENCE`.

## Verification

- Focused Mock tests cover absolute child path, traversal, fixture root,
  non-object JSON, invalid chunk size, and text-safe rendering.
- API/UI tests cover stale Assistant actions, invalid targets, Review navigation
  with no existing artifact, pair action selection, and response ordering.
- Closure tests cover missing, negative, non-finite, and inconsistent artifacts.
- Run both Python suites excluding/including available real data, React tests,
  build/lint, `git diff --check`, then the Docker preflight. Docker acceptance is
  run only as its explicitly authorized command and reported separately.
