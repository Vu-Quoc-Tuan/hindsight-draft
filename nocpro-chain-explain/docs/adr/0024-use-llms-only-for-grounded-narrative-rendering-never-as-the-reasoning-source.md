# ADR-0024: Use LLMs only for grounded narrative rendering, never as the reasoning source

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** LLM usage

## Context

The contribution is a structured, provenance-first explanation engine. Letting an LLM invent reasons would break reproducibility and traceability.

## Decision

LLMs MAY render natural-language narratives from structured claims/evidence at P2. They SHALL NOT create new evidence, change scores, infer root causes unsupported by structured analysis, or bypass provenance.

## Rationale

This preserves deterministic methodology and allows optional UX improvements.

## Consequences

**Positive:** narrative convenience without making the LLM an epistemic source.

**Trade-offs:** generated text must remain constrained/grounded.

## Alternatives considered

1. LLM as primary explainer — rejected.
2. LLM to infer missing topology/causality — rejected.

## Implementation implications

Narrative inputs should be structured claim objects. Rendered text should link back to those objects.

### NocPro Assistant navigation boundary

The NocPro Assistant may explain registered concepts, search the active
snapshot through deterministic tools, and return typed in-application
navigation targets. It is a read-only projection layer: it SHALL NOT submit
Tier-2 jobs, create or alter evidence, change memberships, apply a Review
proposal, submit feedback, query arbitrary SQL, or generate a URL/tool call
from language-model output.

Assistant requests carry the active snapshot identity. A stale identity must
return `STALE_CONTEXT`, not read a similarly named chain from a newer snapshot.
Topology source navigation is not an alarm-to-resource mapping or a promotion
to P2 dependency semantics; requests needing that unavailable mapping must
fail closed.

## Invariants / required tests

- Removing the LLM leaves all core explanation functionality intact.
- LLM output cannot create a new validation verdict.
- Assistant actions are typed, context-checked in-app targets only.
- Missing resource-to-chain mapping is reported as unavailable, never inferred
  from topology source relations.

## References

V2.3.1 sections 8.6 and 10.
