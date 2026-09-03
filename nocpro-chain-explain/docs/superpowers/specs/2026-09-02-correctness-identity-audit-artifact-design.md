# Correctness, Snapshot Identity, and Audit Artifact Design

## Scope

This change closes three frozen correctness and durability gaps without opening
new Counterfactual operations or adding production thresholds.

## Membership role semantics

Role conditions use strict mathematical conjunction. A missing metric does not
satisfy either a positive or negative condition.

- `CORE` requires computable representativeness at or above `r_min` and a
  computable positive `Margin_common`.
- `WEAK` requires a computable non-positive `Margin_common`.
- When the role availability gate passes but one of these conditions cannot be
  established, the member is `PERIPHERAL`.
- Only a failed role availability gate produces `INSUFFICIENT_DATA`.

## Canonical snapshot identity

The immutable identity of a snapshot is `(snapshot_id, snapshot_version)`.
Lineage and Similar Chains must carry both values through domain keys,
deterministic hashes, relational primary and foreign keys, repository queries,
fingerprint identities, and model/index lookup.

In particular, `(S1, v1, C1)` and `(S1, v2, C1)` are distinct lineage nodes.
No component or model may alias them solely because `snapshot_id` and
`chain_id` match.

The schema migration is additive/reconstructive for existing lineage and
similarity tables. Existing rows receive their version by joining the persisted
canonical snapshot identity. Ambiguous legacy rows must fail migration rather
than guess.

## Immutable exact Audit artifact

An exact Tier-2 Audit run persists a versioned, review-consumable artifact. It
does not persist the dense pair graph or every pair evidence record.

The artifact identity contains:

- snapshot ID and version;
- chain ID and chain membership fingerprint;
- analysis/config version;
- Audit artifact schema version and content fingerprint;
- exact mode/status and chain size;
- canonical candidate cuts, their members, source, and provenance label;
- exact scored-cut results and structural verdict inputs;
- creation metadata.

Artifacts are immutable. A new exact Audit run creates a new artifact row and
does not overwrite an artifact referenced by an earlier Review.

Counterfactual Review may consume only an exact compatible artifact whose
snapshot identity, chain fingerprint, analysis/config version, and artifact
fingerprint match. Review never runs Structural Audit implicitly. If no
compatible artifact exists, `REMOVE_MEMBER` remains independent while
`SPLIT_CHAIN` returns `STRUCTURAL_AUDIT_UNAVAILABLE`.

Candidate-specific before/after metrics continue to be recomputed exactly from
the immutable snapshot and current evidence. The persisted artifact preserves
Audit candidate-generation truth; it is not a cached Counterfactual verdict.

## Verification

Tests must cover the strict Role matrix, two versions of one snapshot ID in
lineage and Similar Chains, migration/repository compatibility, exact Audit
artifact immutability, restart reuse by Review, stale artifact rejection, and
the absence of implicit Audit recomputation.

