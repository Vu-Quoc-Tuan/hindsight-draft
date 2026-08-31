# Canonical Output Model

The mock outputs a complete `MockSnapshotPackage` conforming to the versioned contract owned by `nocpro-chain-explain`.

## Logical package

```text
MockSnapshotPackage
├── snapshot
├── alarms[]
├── chains[]
├── memberships[]
├── system_metadata
│   ├── chain_rules[]
│   ├── chain_characteristics[]
│   ├── attribute_configs[]
│   └── pair_metadata[]
├── topology
│   ├── nodes[]
│   ├── edges[]
│   ├── failure_domains[]
│   ├── active_paths[]
│   └── mappings[]
├── operational_context[]
└── provenance_manifest
```

## Snapshot

Minimum:

```json
{
  "schema_version": "v1",
  "snapshot_id": "...",
  "snapshot_time": "...",
  "status": "COMPLETE",
  "source": "nocpro-mock",
  "source_kind": "REAL_EXPORT_REPLAY"
}
```

## Alarm

Preserve:
- raw source ID,
- raw timestamp strings,
- canonical parsed time,
- device/resource/entity fields,
- quality flags.

Example quality flags:

```text
TIMESTAMP_FUTURE_OUTLIER
END_BEFORE_START
UNPARSEABLE_TIMESTAMP
MISSING_DEVICE_CODE
MISSING_NODE_REFERENCE
```

## Topology edge

Required semantic fields:

```text
edge_id
source_resource_id
target_resource_id
relation_type
directed
source_id
source_version
source_kind
freshness
```

Do not use a generic directed edge when source only provides undirected adjacency.

## Synthetic topology source identity

A scenario that provides `topology`, `paths`, `failure_domain` or
`failure_domains` must declare:

```yaml
generator_version: mockgen-1.4.0
topology_source:
  source_id: synthetic-topology
  source_version: syn-topo-activepath-v1
```

`generator_version` identifies generator code. `topology_source.source_version`
identifies the topology model being generated. They are independent and must
never be aliased or used as fallbacks for one another. The mock stamps the
exact topology source ID/version plus generation metadata on every topology
node, edge, active path and failure domain, validates the package before
publication, and preserves those fields inside the canonical bytes transported
by Kafka.

The canonical contract keeps record-level `source_version` optional so Explain
can ingest foreign producers in degraded mode. That compatibility does not
weaken the mock scenario contract: a mock topology scenario missing either
source field is rejected before publication.

## Alarm-resource mapping

```text
alarm_id
resource_id
mapping_status
mapping_method
mapping_confidence
topology_layer
source_version
```

`mapping_status`:
- EXACT
- VERIFIED_ALIAS
- UNMAPPED
- AMBIGUOUS

Fuzzy prefix match is not a default mapping method.

## Contract ownership

The actual JSON Schema lives in:

```text
nocpro-chain-explain/contracts/v1/
```

The mock may vendor a generated/read-only copy for CI, but must not create an incompatible second canonical schema.
