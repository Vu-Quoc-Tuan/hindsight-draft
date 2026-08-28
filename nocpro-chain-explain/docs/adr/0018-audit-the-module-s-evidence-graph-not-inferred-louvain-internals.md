# ADR-0018: Audit the module's evidence graph, not inferred Louvain internals

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Structural audit

## Context

The module does not have guaranteed access to original Louvain edge weights, node movement or ΔQ. Pretending reconstructed evidence is the original chaining graph would overclaim.

## Decision

Structural audit SHALL operate on `G*_audit`, built only from audit-eligible derivation groups.

Claims SHALL describe robustness/separation of the evidence graph and SHALL NOT claim that NocPro/Louvain would necessarily split the chain.

## Rationale

This preserves the partial-observability contract.

## Consequences

**Positive:** no fake model introspection.

**Trade-offs:** audit is an independent post-hoc structural test, not a proof of model error.

## Alternatives considered

1. Reconstruct a presumed Louvain graph — rejected.
2. Rerun Louvain and call differences counterfactual proof — rejected.

## Implementation implications

If exact NocPro internals become available later, add an adapter without changing the current audit semantics.

## Invariants / required tests

- Audit outputs use “review candidate” wording.
- No endpoint exposes reconstructed edges as “original Louvain edges”.

## References

V2.3.1 sections 6, 8.1 and 10.
