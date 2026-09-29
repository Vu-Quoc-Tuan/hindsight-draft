# Offline Audit Coverage & Sensitivity Diagnostic

This CLI produces a frozen, read-only diagnostic for Structural Audit evidence coverage and leave-one-effective-group-out (LOGO) sensitivity. It does not change API responses, Role assignment, Review behavior, chain membership, or production Audit policy.

The source-verified feature boundaries are summarized in
[Active Methodology](METHODOLOGY.md) and the
[Feature Capability Matrix](FEATURE_CAPABILITY_MATRIX.md). The diagnostic does
not adjudicate the completeness of that feature set.

## Run it

Use a complete canonical Input Contract v1 snapshot file and an explicit chain ID. From `nocpro-chain-explain/`:

```bash
PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/python \
  benchmarks/run_audit_diagnostics.py prepare \
  --snapshot-json /path/to/frozen-snapshot.json \
  --chain-id CHAIN_ID \
  --analysis-config config/thresholds/v1.yaml \
  --experiment config/audit_diagnostics/experiment-v1.json \
  --scope-policy config/audit_diagnostics/scope-v1.yaml \
  --output-dir /tmp/hindsight-audit-diagnostics

PYTHONPATH=.:services/analysis-worker:services/api .venv/bin/python \
  benchmarks/run_audit_diagnostics.py run \
  --manifest /tmp/hindsight-audit-diagnostics/RUN_ID/manifest.json
```

`prepare` validates the snapshot and freezes its byte and canonical-content hashes, chain membership, analysis config, scope policy, experiment, effective-group registry, source commit, relevant source file hashes, variants, and resource limits. It does not evaluate channel evidence or score candidates. It creates a new run directory and refuses to reuse one.

`run` verifies those frozen inputs, evaluates the exact pair matrix in a child process, and publishes `report.json` and `report.md` atomically. It refuses to overwrite existing reports. A changed input, config, policy, or relevant source file invalidates the manifest. The child process is stopped at the frozen timeout; no report is published on timeout.

Each run directory contains:

```text
RUN_ID/
  manifest.json
  manifest.sha256
  report.json
  report.md
```

Exit codes: `0` complete, `2` invalid input or manifest mismatch, `3` technical limit/timeout/incomplete input, `4` invariant or worker failure. Read `run_status` and `complete` in JSON as the authoritative execution status.

## What the report measures

The frozen v1 scope policy makes every distinct pair in the chain applicable to every channel in the exact Audit execution profile. Missing input stays applicable but unavailable. There are no `NOT_APPLICABLE` rules in the initial registry. A future not-applicable rule must be explicit and versioned before measurement; a missing topology mapping is not proof that `Dep_hop` is out of scope.

For each channel and effective group, the report partitions every pair as `APPLICABLE`, `NOT_APPLICABLE`, or `UNKNOWN_APPLICABILITY`. Availability, invocation, and evidence state remain separate. Coverage is:

```text
available / applicable
```

The report also gives applicability, unknown-scope and not-applicable shares, primary reason counts, invocation counts, and group partial-observability counts. It reports chain-wide rows and `within_A`, `within_B`, and `cross` rows for every frozen candidate. These are exact descriptive counts for this snapshot; they are not confidence intervals, probabilities of correctness, or proof that all relevant evidence channels exist.

Tier-2 already reports Evidence Coverage Attribution: the share of unordered pairs supported by at least one explain-eligible group, plus group contributions. Its deletion curve measures remaining pair-support coverage after removing groups. This diagnostic answers different questions: whether each channel/group was available within its registered scope, and how removing an audit-eligible group changes the weighted Audit graph and candidate conductance. Keep these results separate; the shared word “coverage” does not mean their numerators or denominators are interchangeable.

This diagnostic does not consume adjudicated pair or incident labels.
`review-label-v1` is a Counterfactual candidate-ranking label policy and does
not establish pair relatedness or the correctness of an Audit partition.

The bounded pair examples prioritize unknown applicability and applicable-but-unavailable evidence. Their display caps do not change aggregate counts. A per-pair trace includes channel, full effective group key, scope, invocation, evidence state, and a reason code; raw channel scores and free-text detail are not copied into the report.

The capability catalog records `H` as excluded from this exact Audit profile and `H_domain` as a candidate hyperedge capability, not pairwise clique evidence. Dynamic dependency providers are included only when their source and full effective group identity resolve from the frozen package.

The report measures availability/support of registered evidence only. In
particular:

- Entity currently has five separately tagged channels. The source does not
  establish a device/card/site containment hierarchy or prove that separate
  tags are statistically independent. `E_remote` remains a relation outside
  that possible containment scale.
- `Dep_hop` uses undirected adjacency. Directed upstream providers can score a
  shared ancestor or explicit active path for a pair, but that pair score does
  not assert alarm-to-alarm propagation direction.
- No post-hoc negative-evidence channel in `K_pair` or shared event pair feature
  was identified. Gray-box can preserve an upstream `M_pair` `VETO` as a separate
  `SYSTEM_FACT`, which is not Audit edge evidence. The optional Tier-2
  `cross_block_negative_evidence` input defaults false and has no in-repository
  producer identified; Counterfactual external-validation contradictions are a
  separate input path.
- Input Contract v1 carries `operational_context`, and the Mock can generate
  synthetic maintenance/ticket contexts. The three checked real replay presets
  have no such records, and pair evaluation does not consume them into `K_pair`.
- Severity/type fields enter descriptor mining and can affect representativeness
  and Audit candidate generation, but are not a dedicated pairwise compatibility
  feature. `S` compares name/family/category, not severity/type.

Thus, full coverage across the registered groups cannot establish that no
unmodeled relation exists. It also cannot decide whether missing evidence or a
missing feature concept explains a candidate cut.

## How to read LOGO

The baseline graph uses the canonical `build_audit_graph`. LOGO removes one full effective group key:

```text
(derivation_tag, provenance_class,
 explain_eligible, role_eligible, audit_eligible)
```

It then rebuilds the graph from the remaining raw pair values. The report separates edges removed because fewer than two supporting groups remain from retained edges whose weight changed. It includes available/support group counts, full group-key traces, per-region transition totals, weight changes, and pairs on the two-support boundary. Boundary examples are listed first.

Candidates are generated once from the baseline and held fixed across all LOGO variants. The report includes graph edge/isolate counts, cut weight, side volumes, conductance and rank for each candidate. `production_baseline_winner_id` preserves the canonical baseline winner; `variant_best_id` is the best scorable candidate in the same frozen set. Regret and `epsilon_phi` verdict flips are separate. No candidate score is called a global minimum cut.

The configured `epsilon_phi=0.3` comes from the documented weak baseline and is not production-calibrated. `delta_phi` is intentionally `null` until an operational materiality threshold is approved. A winner change can therefore be reported without labeling it material.

## Resource and interpretation limits

The checked-in experiment pins technical limits: at most 500 members, 124,750 unordered pairs, 32 total variants including baseline, 128 candidates, 50 pair examples per section, 64 channel traces per example, and a 300-second worker deadline. The stricter canonical exact-audit guard still applies. Exceeding a limit never silently truncates candidates and then claims a complete result.

Sensitivity is conditional on the frozen candidate set and input snapshot. It cannot establish that a cut was caused by missing data, that a relation is causal, that a chain is wrong, or that the current channels are sufficient. The initial scope policy is explicitly marked `UNAPPROVED_DIAGNOSTIC_POLICY`; a complete report is not production acceptance or policy activation.

## Verification scope

Tests use synthetic fixtures to verify contracts, denominators, LOGO transitions, candidate scoring, frozen hashes, resource limits, timeout behavior, strict JSON, and CLI artifacts. A synthetic fixture run demonstrates the implementation path only; it does not validate any operational NOC snapshot.
