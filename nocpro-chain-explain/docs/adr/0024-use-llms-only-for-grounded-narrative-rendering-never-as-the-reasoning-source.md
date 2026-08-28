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

## Invariants / required tests

- Removing the LLM leaves all core explanation functionality intact.
- LLM output cannot create a new validation verdict.

## References

V2.3.1 sections 8.6 and 10.
