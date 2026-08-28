# ADR-0001: Keep `nocpro-mock` as a separate upstream simulator repository

- **Status:** Accepted — project integration decision
- **Date:** 2026-08-28
- **Scope:** Repository boundary / upstream simulation

## Context

The explanation system is downstream of NocPro and external operational inputs. During development, the real upstreams are unavailable, so a simulator is required. The simulator must be able to produce alarm snapshots, chain memberships, optional Gray-box metadata, synthetic inventory/topology, failure-domain membership, and optional maintenance/ticket context.

Placing the simulator inside `nocpro-chain-explain` would blur the production boundary and would make it easy for downstream code to depend on simulator internals.

## Decision

`nocpro-mock` SHALL remain a repository/process outside `nocpro-chain-explain`.

It MAY internally contain logical upstream modules such as `nocpro/`, `inventory/`, `context/`, `scenarios/`, `replay/`, and `producer/`, but the explanation system SHALL consume only the external Input Contract.

`nocpro-chain-explain` SHALL NOT import Python modules/classes from `nocpro-mock`.

## Rationale

The same dependency direction should hold in research and production: upstream systems publish state; the explanation system consumes state. This makes replacement of the mock by real NocPro/inventory sources straightforward and prevents circular test logic.

## Consequences

**Positive:** clean boundary, realistic integration, simulator is replaceable, provenance is explicit.

**Trade-offs:** cross-repository integration tests and contract compatibility checks are required.

## Alternatives considered

1. Put the mock inside the explanation repo — rejected because it weakens the upstream/downstream boundary.
2. Split NocPro, topology and context into three mock services — rejected for now because one simulator repository is sufficient.
3. Read CSV directly inside analysis code — allowed only as a test fixture path, not as the system boundary.

## Implementation implications

Recommended workspace:

```text
workspace/
├── nocpro-mock/
└── nocpro-chain-explain/
```

The mock must stamp logical source (`nocpro`, `inventory`, `context`) and `source_kind`.

## Invariants / required tests

- Downstream code must not import `nocpro_mock.*`.
- The same downstream logic must work with mock and future real upstream producers.
- Synthetic inputs must never be silently reclassified as real external validation.

## References

V2.3.1 sections 1–2 and 12.
