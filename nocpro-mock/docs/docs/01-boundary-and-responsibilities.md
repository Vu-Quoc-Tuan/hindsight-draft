# Boundary & Responsibilities

## Upstream role

`nocpro-mock` mô phỏng **interface** của upstream systems, không mô phỏng toàn bộ implementation.

Nó có thể đại diện cho:

```text
NocPro chaining output
Inventory / topology
Operational context
Historical replay
Scenario controller
```

## Input/output boundary

```text
raw exports
observed fixtures
scenario definitions
      │
      ▼
 nocpro-mock
      │
      ├── validate
      ├── normalize
      ├── replay
      └── inject explicitly-synthetic scenario data
      │
      ▼
versioned Input Contract
      │
      ▼
nocpro-chain-explain
```

## Mock owns

- file loaders,
- canonicalization,
- raw-source retention,
- snapshot packaging,
- replay clock,
- scenario generation,
- synthetic source stamping,
- output contract validation.

## Mock does NOT own

- `T_burst`, `T_delay`, `E_*`, `Dep_*`, `H`, `S`,
- derivation groups,
- Fit / MembershipSupport,
- role classification,
- descriptor mining,
- audit conductance,
- lineage reasoning inside Explain,
- Similar Chains,
- Evidence Coverage Attribution,
- validation verdict.

## Repository dependency

`nocpro-mock` SHALL NOT import Explain business logic.

Allowed coupling:
- versioned JSON schema / contract artifact,
- documented enum values,
- integration test fixture exchange.

Forbidden coupling:
- calling Explain engines to create mock source data,
- using Explain result to decide what upstream “should have said”.
