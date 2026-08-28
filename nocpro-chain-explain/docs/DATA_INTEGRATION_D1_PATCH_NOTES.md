# ADR Data/Integration D1 — Patch Summary

No ADR-0033 is required. The new facts constrain existing decisions rather than introduce a new subsystem.

Patched ADRs:
- ADR-0002 — contract adds chaining_usage, system_pair_status, coverage_scope, topology mapping metadata.
- ADR-0006 — Black-box wording: external != independent validation.
- ADR-0007 — provenance stays four classes; source_kind/chaining_usage are metadata dimensions.
- ADR-0008 — M_pair/M_attribute_config remain raw SYSTEM_FACT; no raw NocPro score normalization.
- ADR-0010 — source_kind → chaining_usage → provenance/Quality validation gate.
- ADR-0012 — NocPro TimeWindow is distinct from T_burst/T_delay.
- ADR-0013 — NocPro HistorySimilarity/system counts are distinct from behavioral H.
- ADR-0026 — REAL_EXPORT_REPLAY is distinct from SYNTHETIC_TEST/REAL_LIVE.
- ADR-0027 — spec_sanity tests expanded for D1 invariants.
- ADR-0029 — P1 CommonDependency is capability-gated; missing active-path data may return UNAVAILABLE.
- ADR-0032 — fail-closed mapping and topology semantic capability gates.

Unchanged core ADRs:
derivation dedup, Fit/Role, H_domain semantics, 3-graph rule, candidate cuts/Φ, lineage/drift, cosine Similar Chains, attribution, tiering.
