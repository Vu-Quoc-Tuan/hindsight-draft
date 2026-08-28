# ADR-0002: Use one versioned Input Contract as the canonical integration schema

- **Status:** Accepted — implementation architecture
- **Date:** 2026-08-28
- **Scope:** Contracts / schema evolution

## Context

The system consumes several logical upstream inputs: alarms, chain partition, optional system metadata, topology/inventory, failure domains and operational context. If the mock and explanation repository invent separate schemas, semantic drift will occur.

The project is currently a two-repository project. Creating a third contracts repository adds unnecessary overhead for a one-person implementation.

## Decision

The canonical Input Contract SHALL live in `nocpro-chain-explain`, under a dedicated versioned contract directory such as:

```text
contracts/
└── v1/
    ├── snapshot.schema.json
    ├── alarm.schema.json
    ├── chain.schema.json
    ├── system_metadata.schema.json
    ├── topology.schema.json
    └── context.schema.json
```

`nocpro-mock` SHALL consume/export payloads conforming to these artifacts. CI SHALL verify contract compatibility.

The contract SHALL define at minimum: `Snapshot`, `Alarm`, `Chain`, `ChainMembership`, `SystemMetadata`, `TopologyNode`, `TopologyEdge`, `FailureDomain`, `AlarmResourceMapping`, and optional `OperationalContext`.

Every envelope SHALL carry `schema_version`, `event_id` or deterministic payload identity, `source`, `source_kind`, `produced_at`, and relevant snapshot/topology identifiers.

Data/Integration D1 adds contract fields/objects where applicable:
- `source_kind ∈ {REAL_LIVE, REAL_EXPORT_REPLAY, SYNTHETIC_TEST, BACKFILL}`;
- `ChainingUsageAssessment {source_id, source_version, chaining_config_version, executed_rule_set/attribute_set?, snapshot/run_context, usage}`;
- `usage ∈ {CONFIRMED_USED, CONFIRMED_NOT_USED, UNKNOWN}`;
- `quality_status ∈ {PASS, FAIL, UNKNOWN}` plus subtype-specific Quality inputs stamped by `config_version`;
- `system_pair_status ∈ {EVALUATED, NOT_EVALUATED, UNKNOWN}`;
- `coverage_scope ∈ {FULL_PAIR_SPACE, BOUNDED_COMPARISON, UNKNOWN}` for aggregate system characteristics;
- topology mapping metadata: `topology_layer`, `mapping_method`, `mapping_confidence`, `mapping_status`, `source_version`, `freshness`.

`BACKFILL` means bootstrap/training/backfill state; historical real exports replayed as observations use `REAL_EXPORT_REPLAY`, not `BACKFILL` merely because they are old.

## Rationale

One versioned schema is easier to govern than shared Python imports or a third repository. It keeps storage schema separate from integration schema and supports direct JSON and Kafka transports with identical semantics.

## Consequences

**Positive:** single semantic source of truth, reproducible parsing, simpler integration tests.

**Trade-offs:** schema evolution and compatibility tests become mandatory.

## Alternatives considered

1. A third `nocpro-contracts` repo — rejected for the current one-person scope.
2. Local Pydantic models independently defined in both repos — rejected due to drift.
3. Database tables as the wire contract — rejected because persistence and integration are different concerns.

## Implementation implications

Pydantic models MAY be generated from/validated against the versioned schema. TypeScript API types may also be generated from the same semantic definitions, but web types are not the integration authority.

## Invariants / required tests

- Unknown incompatible major versions are rejected.
- Additive compatible fields do not break existing consumers.
- Provenance class, provenance subtype, `source_kind`, usage assessment, `quality_status`, relation type, mapping status and snapshot identifiers are enum/format validated.
- Missing system pair metadata defaults to `UNKNOWN`, never silently to NEUTRAL/NOT_EVALUATED.
- `chaining_usage` is not stored as one global boolean/property for an entire topology/history store; it must be resolvable in chaining config/run context.
- Missing Quality needed for validation yields `quality_status=UNKNOWN`.
- The same fixture must parse identically through direct and Kafka adapters.

## References

V2.3.1 sections 2, 4, 4B and 12.
