# ADR-0031: Freeze Evidence Coverage Attribution as a group-level closed-form coverage allocation

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Tier-2 attribution

## Context

The final spec intentionally renamed the feature from generic Shapley language to Evidence Coverage Attribution. Channel-level players would over-credit repeated representations of the same derivation, while exact combinatorial Shapley is unnecessary and can violate latency constraints.

## Decision

Players SHALL be eligible derivation groups, not channels.

Define:

`v(S) = |{pairs p: exists g in S with b_g(p)=1}| / C(|C|,2)`.

For each group g:

`phi_g = (1/C(|C|,2)) * sum_{p supported by g} 1/g_p`

where `g_p` is the number of derivation groups supporting pair p.

This closed-form allocation is the baseline. It SHALL be named **Evidence Coverage Attribution**, not “exact Shapley”.

Default players are EXPLAIN_ELIGIBLE groups; BEHAVIORAL contribution is visually labeled; SYSTEM_FACT is excluded.

Large chains SHALL NOT materialize all C(n,2) pairs. Attribution is exact from indexed support statistics when `|C| <= audit.exact_max_members`; above that ceiling it is `UNAVAILABLE / ATTRIBUTION_LIMIT_EXCEEDED`. This version has no sampled, sparsified, or supernode attribution mode.

For `|C| = 1`, Attribution is `NOT_APPLICABLE / SINGLETON` because the pair denominator is zero. For `|C| >= 2` with zero eligible groups, Attribution remains `AVAILABLE / EXACT` with zero total coverage and an empty contribution list.

## Rationale

The formula shares each covered pair equally among supporting derivation groups and is representation-invariant at the group level.

## Consequences

**Positive:** deterministic, explainable, consistent with derivation dedup.

**Trade-offs:** it measures evidence coverage contribution, not causal importance or connectivity value.

## Alternatives considered

1. Channel-level attribution — rejected.
2. Exact combinatorial Shapley — rejected as baseline.
3. Rename output “cohesion attribution” — rejected because the value function is coverage.

## Deletion-curve evaluation

Deletion evaluation runs only when Attribution is `AVAILABLE / EXACT`.

- `PRIMARY` orders groups by `phi_g` descending, then stable `group_id` ascending.
- `REVERSE` orders groups by `phi_g` ascending, then stable `group_id` ascending.
- At step `k`, the implementation removes the first `k` groups and recomputes exact union coverage `v(G \ R_k)` from indexed group support. It SHALL NOT use `1 - cumulative_phi`.
- Raw curves contain `G + 1` points, with `curve[0] = v(G)` and `curve[G] = 0`.
- Normalized AUC uses `x_k = k/G` and the trapezoidal rule. Lower PRIMARY AUC is better because highly ranked group deletion should reduce coverage sooner.
- The qualitative ordering `primary_auc < random_mean_auc < reverse_auc` is an evaluation signal, not an invariant.
- Deltas are `random_mean_auc - primary_auc` and `reverse_auc - primary_auc`.

Random evaluation is config-required:

```yaml
attribution_evaluation:
  randomization:
    algorithm: SPLITMIX64_FISHER_YATES_V1
    seed: {value: 42, source: FROZEN_SPEC}
    repetitions: {value: 100, source: FROZEN_SPEC}
```

Missing or invalid fields produce `UNAVAILABLE / ATTRIBUTION_EVALUATION_CONFIG_INCOMPLETE`; they do not fail the Tier-2 job. All repetitions consume one RNG stream and shuffle the stable ascending `group_id` list. The stream is never reseeded between repetitions.

`SPLITMIX64_FISHER_YATES_V1` is defined independently of a language runtime:

1. State and arithmetic are unsigned 64-bit modulo `2^64`; initial state is `seed mod 2^64`.
2. Each draw increments state by `0x9E3779B97F4A7C15`, then applies the SplitMix64 xor/shift/multiply sequence with constants `0xBF58476D1CE4E5B9` and `0x94D049BB133111EB`.
3. A bounded draw for `n` rejects values at or above `2^64 - (2^64 mod n)` and returns the accepted value modulo `n`.
4. Fisher-Yates visits `i = G-1 ... 1`, draws `j` in `[0, i]`, and swaps positions `i` and `j`.

Random pointwise curve and AUC standard deviations are population standard deviations (`ddof=0`) over exactly the configured repetitions.

For `G=0`, deletion evaluation is `NOT_APPLICABLE / NO_ELIGIBLE_GROUPS`: curves are empty, AUC fields are null, repetitions executed is zero, and RNG state is not instantiated or consumed. If Attribution itself is unavailable or not applicable, evaluation is `UNAVAILABLE / ATTRIBUTION_UNAVAILABLE`.

## Implementation implications

Evaluate with exact deletion curves and brute-force comparison on tiny synthetic cases where exhaustive subset computation is feasible. The exact bitmap support model is shared between allocation and deletion evaluation; it is not serialized as a pair list. Indexed producers explicitly certify `SYMMETRIC_UNORDERED_PAIRS_V1`; uncertified support indexes fail closed. Exact support signatures are aggregated once. For each ordering, each signature contributes its pair count to the step at which its last supporting group is removed; one cumulative pass then derives all `G + 1` curve points. Random evaluation therefore does not repeat member-by-group unions or rescan every signature for every curve point.

## Invariants / required tests

- Duplicating channels inside one derivation group does not multiply attribution.
- Large-chain mode proves no full pair matrix was materialized.
- PRIMARY/REVERSE ties use stable `group_id` and every deletion point recomputes exact union coverage.
- Golden permutations pin `SPLITMIX64_FISHER_YATES_V1` across runtimes.
- Random curve and AUC deviations use population standard deviation.
- Singleton Attribution and zero-group deletion evaluation remain distinct.
- UI wording says “% evidence coverage”, not “causal importance/cohesion”.

## References

V2.3.1 section 8.4 and evaluation section 13.
