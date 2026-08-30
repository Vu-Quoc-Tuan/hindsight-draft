# Task 3 report: Configured propagation DAG and RWR

## Outcome

- Status: DONE
- Commit: `241ca16` (`feat: rank propagation hypotheses with configured RWR`)
- Scope: Task 3 only. No scope/API/UI work and no audit, membership, normalized-evidence or validation integration.

## TDD evidence

### RED

Command:

```bash
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests/test_p2_propagation.py -q
```

Result before implementation: collection failed as expected because
`PropagationEdgeHypothesis` and `analyze_propagation` were absent.

### GREEN

Focused command after implementation and the final numerical assertion:

```bash
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests/test_p2_propagation.py -q
```

Result: `17 passed in 0.24s`.

Full Python regression command after the final test edit:

```bash
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests -q
```

Result: `426 passed, 29 skipped in 2.59s`.

Additional checks:

- `git diff --cached --check`: pass.
- `python -m py_compile` on the Task 3 implementation/models/exports/test: pass.
- Ruff and mypy are not installed in the specified repository virtualenv, so no result is claimed for them.

## Files

- Created `nocpro-chain-explain/services/analysis-worker/tier2/topology_hypotheses/propagation.py`.
- Modified `nocpro-chain-explain/services/analysis-worker/tier2/topology_hypotheses/models.py`.
- Modified `nocpro-chain-explain/services/analysis-worker/tier2/topology_hypotheses/__init__.py`.
- Created `nocpro-chain-explain/tests/test_p2_propagation.py`.

## Numerical and semantic self-review

- No production numeric defaults were added. Every scalar is read from the supplied `PropagationConfig`; missing/invalid configuration returns `PROPAGATION_CONFIG_INCOMPLETE`.
- Candidate construction uses one exact Task 2 universe only, identified by source plus version plus relation. It requires all mapped chain resources to be covered by exactly one universe and fails closed rather than combining or lexically selecting universes.
- Only direct resource edges with strictly positive normalized UTC time deltas become candidate alarm edges. Equal/reversed time, missing/unparseable time and unresolved mappings are pinned by tests.
- The complete candidate count is compared with `max_candidate_edges`; overflow returns `CANDIDATE_LIMIT_EXCEEDED` with no truncation or numerical output.
- A deterministic Kahn check rejects a cyclic low-level candidate graph before iteration.
- Restart is uniform over every indegree-zero alarm, initialization is exactly `pi(0)=r`, and every dangling node redistributes to the same restart distribution.
- Exponential outgoing weights use an algebraically equivalent shifted exponent before normalization to avoid an all-zero underflow denominator. A test pins the configured decay and outgoing probabilities.
- Iteration order is sorted, convergence is configured L1 `<= tolerance`, and success on the final allowed iteration is accepted. Exhaustion emits `RWR_NOT_CONVERGED`, iteration/L1 diagnostics, and empty node/edge output.
- Edge hypothesis score is exactly `(1-alpha) * pi(u) * P_uv` from the converged mass. A closed-form two-node check pins stationary mass and edge flow.
- Public tuples and parameter provenance are immutable and sorted; repeated identical input returns equal output, while config version/source changes remain visible.

## Concerns

None. The deliberate fail-closed result when zero or multiple exact universes cover the chain uses the existing `DIRECTED_TOPOLOGY_UNAVAILABLE` reason because the approved reason enum has no generic propagation-universe ambiguity value.

## Follow-up: strict P2 mapping and timezone fail-closed fixes

### Root cause and RED evidence

- `_parse_timestamp()` assigned `timezone.utc` to a naïve ISO timestamp. The
  regression `test_naive_timestamp_fails_closed_without_inferring_utc` failed
  before the fix because the result was `AVAILABLE` with a one-second edge.
- Both P2 analyzers called the P0/P1 `ResourceResolver`, whose documented
  last-row-wins behavior allowed conflicting rows to produce different results
  under row reordering. New parameterized regressions for conflicting resolved
  resources, resolved plus `AMBIGUOUS`/`UNMAPPED`, and conflicting mapping
  context failed before the fix (the first result could be `AVAILABLE` while the
  reversed-row result differed).

### Fix and GREEN evidence

- Added `topology_hypotheses.mapping.resolve_p2_mappings`, a P2-only strict
  resolver. Every relevant alarm must have one coherent resolved claim;
  conflicting resources, mixed resolved/unresolved statuses, or any differing
  mapping status/method/context/provenance metadata return
  `RESOURCE_MAPPING_UNAVAILABLE`. Duplicate identical claims are harmless and
  all resolution is independent of row order. P0/P1 `ResourceResolver` is
  unchanged.
- Naïve canonical timestamps now return
  `TEMPORAL_ORDERING_UNAVAILABLE`; only timezone-qualified values are converted
  to UTC.

Required focused command after the fixes:

```text
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests/test_p2_propagation.py tests/test_p2_dominator.py tests/test_common_dependency.py -q
57 passed in 0.26s
```

Full suite after the fixes:

```text
/home/vqt/UET/Project/hindsight/nocpro-chain-explain/.venv/bin/python -m pytest tests -q
432 passed, 29 skipped in 2.48s
```

`python -m py_compile` over the changed implementation and regression files
passed with exit code 0. `git diff --check` passed.

### Follow-up self-review

- Confirmed `channels.dependency.ResourceResolver` and all P0/P1 callers remain
  unchanged; only dominator and propagation import the new P2 resolver.
- Confirmed relevant rows are grouped by alarm, metadata signatures include
  mapping status, method, resource and all supplied context/provenance keys,
  and row-order permutations produce equal structured results.
- Confirmed no approximate propagation output is emitted on either mapping or
  temporal failure, and no naïve timestamp is assigned a fabricated timezone.

Implementation follow-up commit: `aa329d909a093c9a67b5e7da18ef5b81a2854c1a`
(`fix: harden P2 mapping and temporal ordering`).
