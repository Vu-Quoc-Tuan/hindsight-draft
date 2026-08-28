# NocPro Gray-box Replay

## Fidelity levels

### Level 0 — Observed partition replay

Use observed `chaining_id` / memberships exactly as exported.

No re-clustering.

### Level 1 — Observed Gray-box metadata replay

Attach real/observed:
- rules,
- merge strategy,
- connector/extender labels/counts,
- aggregate characteristics,
- exact system pair metadata only when actually available.

This is the MVP target.

### Level 2 — Synthetic system-metadata scenarios

Create controlled `SYNTHETIC_TEST` metadata to exercise:
- raw score 2.0,
- TimeWindow veto,
- pair EVALUATED / NOT_EVALUATED / UNKNOWN,
- bounded coverage.

These are contract/scenario tests, not claims about a real chain.

### Level 3 — Partial Attribute emulator (optional)

Only if needed later.

May emulate a documented subset of Attribute behavior, but:
- must be clearly synthetic/emulated,
- must not be used to infer missing real system internals,
- must not become a dependency of Explain methodology.

## Golden 2214039 policy

Replay:
- 3 rules,
- OR merge,
- observed connector/extender counts,
- observed aggregate characteristics.

Do NOT create:
- fake exact `simiDict`,
- fake `A_ij`,
- fake ΔQ,
- fake pair score vector,
- fake connector semantics.

## `M_attribute_config`

General Attribute schema can be modeled from the technical report.

Exact executed config for 2214039 should remain UNKNOWN unless sourced.

If a synthetic scenario needs it:

```text
source_kind = SYNTHETIC_TEST
scenario_id = ...
generation_rule = ...
```
