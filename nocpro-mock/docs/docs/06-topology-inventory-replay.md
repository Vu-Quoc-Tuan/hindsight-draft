# Topology & Inventory Replay

## Real topoIP

Treat `topoIP` as a real exported **IP adjacency/inventory relation source**.

Supported baseline capability:

```text
ADJACENCY
PORT_ENDPOINTS
NETWORK_CLASS
FRESHNESS
```

Not supported without additional data:

```text
DIRECTED_DEPENDENCY
SHARED_ANCESTOR
ACTIVE_PATH
ROUTING_PATH
DOMINATOR
FAILURE_DOMAIN
```

## Mapping policy

1. exact device/resource identity,
2. verified alias table,
3. otherwise UNMAPPED.

Never use prefix similarity as truth.

For Golden 2214039:

```text
DEHL01          -> UNMAPPED in current topoIP
DEHT01          -> UNMAPPED
HLC9102DEA01    -> UNMAPPED
HHT9603DEA01    -> UNMAPPED
```

So the real-replay mock emits mapping status, not invented topology.

## relation_type

Normalize only what source supports.

Example baseline:

```text
IP_ADJACENCY
```

Do not rename an adjacency edge to `LOGICAL_DEPENDENCY` merely because its endpoints have hierarchy-looking network classes.

## Freshness

Use `update_time_vipa` as a source-quality input.

Store:
- topology source version,
- edge update time,
- snapshot replay time,
- freshness age.

Do not hardcode PASS threshold in the mock spec; config decides.

## topoIT

Until archive schema is extracted and verified:
- preserve it as pending source,
- use the image only to motivate future multi-layer support,
- do not claim real directed SERVICE dependency.

## What to mock for missing topology capabilities

Create separate synthetic scenarios:

1. `synthetic_hierarchy`
   - directed logical dependency tree
   - enables shared-ancestor tests

2. `synthetic_active_path`
   - explicit path membership
   - enables shared-active-path tests

3. `synthetic_failure_domain`
   - SRLG/power/rack/service-instance hyperedges

4. `synthetic_service_dependency`
   - only for contract tests until topoIT semantics are verified

All use `SYN-*` resource IDs and `source_kind=SYNTHETIC_TEST`.
