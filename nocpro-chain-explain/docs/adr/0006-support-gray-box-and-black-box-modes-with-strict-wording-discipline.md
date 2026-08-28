# ADR-0006: Support Gray-box and Black-box modes with strict wording discipline

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Explanation semantics

## Context

The module may receive NocPro metadata in Gray-box mode, or only alarms/partition plus context in Black-box mode. Post-hoc evidence must not be misrepresented as the model's internal reason. External provenance also does not by itself prove independence from chaining.

## Decision

Gray-box MAY show system-provided facts separately from post-hoc analysis. Black-box claims SHALL use wording such as “post-hoc support” and SHALL NOT say the model grouped alarms because of topology, time or any other feature.

Connector/extender labels SHALL be displayed as reported metadata unless their operational semantics are independently documented. The UI SHALL NOT infer causal/structural meaning from the label name alone.

Black-box SHALL NOT use wording such as “independently validates NocPro” unless ADR-0010's source-kind + chaining-usage + quality gate is satisfied.

## Rationale

This prevents overclaiming and preserves graceful degradation when internals are unavailable.

## Consequences

**Positive:** defensible explanations under partial observability.

**Trade-offs:** wording templates and API claim types require explicit mode/provenance information.

## Alternatives considered

1. Treat metadata and post-hoc evidence as one score — rejected.
2. Infer Louvain/rule internals from outputs — rejected.

## Implementation implications

Every claim payload should include `mode`, provenance/source references and config version. Gray-box system facts should render in a separate section.

## Invariants / required tests

- Black-box templates contain no “model grouped because …” language.
- Connector/extender metadata is not translated into unsupported semantics.
- Removing Gray-box metadata does not break Black-box WHY endpoints.

## References

V2.3.1 sections 2, 9 and 12.
