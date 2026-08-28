# spec_sanity — methodology firewall

These tests are not ordinary implementation tests. A failure means the code violates a frozen methodological invariant.

Required cases:

1. `SYSTEM_FACT` cannot strengthen `G*_audit`.
2. `BEHAVIORAL` cannot validate NocPro.
3. `SYNTHETIC_TEST` external-shaped evidence cannot count as real validation.
4. Derivation channels from the same source group count at most once.
5. Chain descriptors and `M_chain_rule` are not pair Agreement players.
6. `UNAVAILABLE (⊥)` is distinct from `NEUTRAL`.
7. Missing evidence does not automatically produce WEAK.
8. WEAK requires at least two computable role-eligible derivation groups.
9. `H_domain` is not clique-projected.
10. `H_domain` membership may propose a candidate cut.
11. Candidate cut quality is scored on `G*_audit`.
12. Visualization top-K changes do not alter audit results.
13. Multimodal T_delay midpoint typicality is low.
14. Directed A→B delay does not automatically match B→A.
15. History with lift≤1 has zero positive support.
16. Target snapshot is not included in its own history bootstrap.
17. Small-chain over-merge returns SKIPPED/NOT_APPLICABLE.
18. CONFIG_DRIFT is not reported as incident DATA_DRIFT.
19. Attribution players are derivation groups, not channels.
20. Large-chain attribution does not materialize C(n,2).
21. CommonDependency Specificity is always in [0,1].
22. Broad hub ancestors receive lower specificity than narrow dependencies.

23. `SYNTHETIC_TEST` and `BACKFILL` cannot validate.
24. `REAL_EXPORT_REPLAY` only enters later validation gates; it is not automatically validation-eligible.
25. `quality_status=UNKNOWN` or `FAIL` cannot validate.
26. `chaining_usage` must resolve in source-version + chaining-config/run context, not as one coarse store-level flag.
27. `chaining_usage` affects Validate only, not Explain/Role/Audit masks.
28. Raw score/veto belongs to `M_pair`; Attribute config belongs to `M_attribute_config`.
29. Aggregate system characteristics belong to `M_chain_characteristic` and never synthesize exact pair edges.
30. Singleton chain cannot be labeled WEAK solely because pair evidence is unavailable.
31. Singleton pair/connector/over-merge operations return NOT_APPLICABLE.

32. Channels with the same `derivation_tag` but different provenance class form different effective derivation groups
    (`test_same_derivation_tag_different_provenance_split_groups`).
33. Every effective derivation group carries a single eligibility signature
    (`test_group_has_single_eligibility_signature`).
34. `chaining_usage` does not change Explain/Role/Audit grouping
    (`test_chaining_usage_does_not_change_explain_role_audit_grouping`).
35. An audit edge requires >= 2 distinct audit-eligible derivation groups,
    enforced at audit-graph construction
    (`test_audit_edge_requires_two_distinct_audit_eligible_groups`).
