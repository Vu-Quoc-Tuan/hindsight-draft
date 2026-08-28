# Camera-Ready D1 Patch Notes

No V2.4 and no ADR-0033+ were introduced.

## Spec cleanups
1. Removed remaining implication `TOPOLOGY_EXTERNAL = independent`.
2. Explicit source-kind gate: only REAL_LIVE / REAL_EXPORT_REPLAY may proceed; SYNTHETIC_TEST / BACKFILL cannot validate.
3. Added fail-closed `quality_status = PASS/FAIL/UNKNOWN`; validation requires PASS.
4. Scoped `chaining_usage` to source/version + chaining configuration/run context, not pair/alarm and not one coarse store-level flag.
5. Clarified `chaining_usage` constrains Validate only; Explain/Role/Audit remain governed by their existing masks.
6. Separated `M_pair`, `M_attribute_config`, `M_chain_rule`, `M_chain_characteristic`.
7. Added first-class singleton semantics (`NOT_APPLICABLE`, never WEAK only due to missing pairs).
8. Added explicit Gray-box Metadata Adapter to MVP.
9. Updated SYSTEM_FACT type list consistently.
10. Renamed section 3 heading to Tier-1A / Tier-1B / Tier-2.

## ADRs patched
ADR-0002, 0007, 0008, 0010, 0027, 0029, 0032.

## Unchanged
Fit/Role formulas, derivation-group aggregation, temporal local-mass math, H semantics, H_domain, G* definitions, conductance/candidate cuts, lineage/drift, Similar Chains, Evidence Coverage Attribution, tiered execution.
