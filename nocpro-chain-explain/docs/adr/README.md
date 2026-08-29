# ADR Index — NocPro Alarm Chain Explanation & Validation

**Camera-ready pass (28/08/2026):** no new ADR numbers. `source_kind`, contextual `chaining_usage`, fail-closed `quality_status`, SYSTEM_FACT typing, singleton behavior and MVP metadata-adapter requirements are now explicit.

**Data/Integration patch D1 (28/08/2026):** ADR-0002, 0006, 0007, 0008, 0010, 0012, 0013, 0026, 0027, 0029 and 0032 were tightened after checking real Attribute/Louvain metadata, chain 2214039 and topology export. No new methodology ADR was added; V2.3.1 mathematical core remains frozen.

This ADR set is aligned with the frozen **V2.3.1 FINAL** methodology.

Status meaning:

- **Accepted — frozen by V2.3.1:** methodology/architecture rule already fixed by the final spec.
- **Accepted — implementation/project decision:** implementation governance chosen for this project.
- **Proposed:** candidate infrastructure choice; does not block the research core.

## ADRs

- [0001 — Keep `nocpro-mock` as a separate upstream simulator repository](./0001-keep-nocpro-mock-as-a-separate-upstream-simulator-repository.md) — Accepted — project integration decision
- [0002 — Use one versioned Input Contract as the canonical integration schema](./0002-use-one-versioned-input-contract-as-the-canonical-integration-schema.md) — Accepted — implementation architecture
- [0003 — Keep Kafka as a proposed integration transport, not a prerequisite for the research core](./0003-keep-kafka-as-a-proposed-integration-transport-not-a-prerequisite-for-the-research-core.md) — Proposed — adopt only after the direct prototype path is working
- [0004 — Use PostgreSQL as the proposed primary persistent store](./0004-use-postgresql-as-the-proposed-primary-persistent-store.md) — Proposed — research implementation default, benchmark before production commitment
- [0005 — Treat the snapshot as the primary processing boundary](./0005-treat-the-snapshot-as-the-primary-processing-boundary.md) — Accepted — frozen by V2.3.1
- [0006 — Support Gray-box and Black-box modes with strict wording discipline](./0006-support-gray-box-and-black-box-modes-with-strict-wording-discipline.md) — Accepted — frozen by V2.3.1
- [0007 — Enforce four provenance classes throughout data, algorithms and UI](./0007-enforce-four-provenance-classes-throughout-data-algorithms-and-ui.md) — Accepted — frozen by V2.3.1
- [0008 — Keep pair evidence, chain descriptors and chain rule annotations type-separated](./0008-keep-pair-evidence-chain-descriptors-and-chain-rule-annotations-type-separated.md) — Accepted — frozen by V2.3.1
- [0009 — Deduplicate multi-channel evidence by derivation group before cross-channel aggregation](./0009-deduplicate-multi-channel-evidence-by-derivation-group-before-cross-channel-aggregation.md) — Accepted — frozen by V2.3.1
- [0010 — Apply source-kind gating before the Explain/Role/Audit/Validate eligibility mask](./0010-apply-source-kind-gating-before-the-explain-role-audit-validate-eligibility-mask.md) — Accepted — frozen methodology plus synthetic-source implementation guard
- [0011 — Keep `K_pair` pairwise evidence separate from `H_domain` failure-domain hyperedges](./0011-keep-k-pair-pairwise-evidence-separate-from-h-domain-failure-domain-hyperedges.md) — Accepted — frozen by V2.3.1
- [0012 — Use contextual burst segmentation and directed local-mass delay typicality](./0012-use-contextual-burst-segmentation-and-directed-local-mass-delay-typicality.md) — Accepted — frozen by V2.3.1
- [0013 — Use episode-deduplicated grouping history with positive evidence only for lift > 1](./0013-use-episode-deduplicated-grouping-history-with-positive-evidence-only-for-lift-1.md) — Accepted — frozen by V2.3.1
- [0014 — Use Tier-1A background, Tier-1B interactive-local and Tier-2 on-demand execution](./0014-use-tier-1a-background-tier-1b-interactive-local-and-tier-2-on-demand-execution.md) — Accepted — frozen by V2.3.1
- [0015 — Prohibit unguarded O(N²) pair materialization at both snapshot and large-chain scale](./0015-prohibit-unguarded-o-n-pair-materialization-at-both-snapshot-and-large-chain-scale.md) — Accepted — frozen by V2.3.1
- [0016 — Keep statistical, visualization and audit graphs distinct](./0016-keep-statistical-visualization-and-audit-graphs-distinct.md) — Accepted — frozen by V2.3.1
- [0017 — Separate IDENTITY and CONTRASTIVE descriptor search objectives](./0017-separate-identity-and-contrastive-descriptor-search-objectives.md) — Accepted — frozen by V2.3.1
- [0018 — Audit the module's evidence graph, not inferred Louvain internals](./0018-audit-the-module-s-evidence-graph-not-inferred-louvain-internals.md) — Accepted — frozen by V2.3.1
- [0019 — Generate structural candidate cuts deterministically and score them on `G*_audit`](./0019-generate-structural-candidate-cuts-deterministically-and-score-them-on-g-audit.md) — Accepted — frozen by V2.3.1
- [0020 — Track evolving incidents with lineage rather than raw chain IDs](./0020-track-evolving-incidents-with-lineage-rather-than-raw-chain-ids.md) — Accepted — frozen by V2.3.1
- [0021 — Separate explanation drift by execution tier and distinguish DATA_DRIFT from CONFIG_DRIFT](./0021-separate-explanation-drift-by-execution-tier-and-distinguish-data-drift-from-config-drift.md) — Accepted — frozen by V2.3.1
- [0022 — Use normalized fingerprint + cosine similarity as the Similar Chains baseline](./0022-use-normalized-fingerprint-cosine-similarity-as-the-similar-chains-baseline.md) — Accepted — frozen by V2.3.1
- [0023 — Run Tier-2 asynchronously and only per chain](./0023-run-tier-2-asynchronously-and-only-per-chain.md) — Accepted — frozen by V2.3.1
- [0024 — Use LLMs only for grounded narrative rendering, never as the reasoning source](./0024-use-llms-only-for-grounded-narrative-rendering-never-as-the-reasoning-source.md) — Accepted — frozen by V2.3.1
- [0025 — Version all analysis configuration and record parameter provenance](./0025-version-all-analysis-configuration-and-record-parameter-provenance.md) — Accepted — frozen by V2.3.1
- [0026 — Mark mock-generated topology, context and labels as synthetic test sources](./0026-mark-mock-generated-topology-context-and-labels-as-synthetic-test-sources.md) — Accepted — project/test provenance decision
- [0027 — Treat `spec_sanity` tests as executable methodology invariants](./0027-treat-spec-sanity-tests-as-executable-methodology-invariants.md) — Accepted — governance decision
- [0028 — Freeze membership Fit, three-axis roles, and WEAK vs INSUFFICIENT DATA semantics](./0028-freeze-membership-fit-three-axis-roles-and-weak-vs-insufficient-data-semantics.md) — Accepted — frozen by V2.3.1
- [0029 — Freeze implementation scope: MVP/P0 first, P1-Core minimum bar is 3+1](./0029-freeze-implementation-scope-mvp-p0-first-p1-core-minimum-bar-is-3-1.md) — Accepted — frozen by V2.3.1 scope
- [0030 — Use a Direct Snapshot Adapter as the accepted prototype reference path](./0030-use-a-direct-snapshot-adapter-as-the-accepted-prototype-reference-path.md) — Accepted — implementation sequencing decision
- [0031 — Freeze Evidence Coverage Attribution as a group-level closed-form coverage allocation](./0031-freeze-evidence-coverage-attribution-as-a-group-level-closed-form-coverage-allocation.md) — Accepted — frozen by V2.3.1
- [0032 — Freeze dependency evidence semantics, anti-hub specificity and failure-domain role](./0032-freeze-dependency-evidence-semantics-anti-hub-specificity-and-failure-domain-role.md) — Accepted — frozen by V2.3.1 P1-Core
- [0033 — Open the P2 topology foundation as fail-closed Tier-2 semantics](./0033-open-p2-topology-foundation-as-fail-closed-tier-2-semantics.md) — Accepted — explicit scope amendment

## Governance rule

If implementation code conflicts with a frozen methodology ADR, change the code. Changing a frozen ADR requires an explicit methodology/spec revision first.

Accepted ADRs are **not** all backlog features. ADR-0029 controls implementation scope.
