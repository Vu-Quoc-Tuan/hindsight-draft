# Version Synthetic Topology Sources Design

## Goal

Carry an explicit synthetic topology-source identity from scenario definition
through `nocpro-mock`, the canonical snapshot package, Kafka and Explain. The
topology source version is independent from the generator implementation
version:

```text
generator_version != topology_source.source_version
```

No adapter may copy or fall back from one value to the other.

## Scenario contract

A scenario that emits any topology-derived object MUST declare one shared
metadata block:

```yaml
topology_source:
  source_id: synthetic-topology
  source_version: syn-topo-v1
```

Topology-derived objects are `TopologyNode`, `TopologyEdge`, `ActivePath` and
`FailureDomain`. Therefore the block is required when the scenario contains at
least one of `topology`, `paths` or `failure_domain`. A scenario containing none
of those blocks does not need `topology_source`.

Both values must be strings with non-whitespace content. Missing, blank or
non-string values make scenario parsing/generation fail with `ScenarioError`.
The mock never repairs them from `scenario_id`, `scenario_version`,
`generator_version` or snapshot metadata.

`generator_version` continues to live in every synthetic object's
`GenerationMetadata`. It identifies the code that generated the fixture, not
the topology source being modelled.

## Generated canonical records

All topology-derived records from one scenario carry the exact
`topology_source.source_id` and `topology_source.source_version`. The canonical
`ActivePath` and `FailureDomain` records gain the same optional
`source_version` field already present on topology nodes and edges. Their
generation metadata independently carries:

```text
scenario_id
seed
generator_version
generation_rule
```

The provenance manifest declares the topology source with the same source ID,
source version and `source_kind=SYNTHETIC_TEST`. Kafka needs no new envelope
field: chunking transports the canonical serialized package byte-for-byte, so
the source identity travels inside the payload and remains covered by the
whole-snapshot checksum.

The canonical dataclasses keep `source_version` optional for compatibility
with non-mock producers. This is deliberate: an invalid topology capability
must not necessarily invalidate unrelated alarm-chain data in the same
snapshot.

## Two validation boundaries

The mock is strict because it owns its scenarios:

```text
topology-derived block present
AND topology_source missing/invalid
-> reject scenario before package publication
```

Explain is independently fail-closed because Kafka and HTTP may receive other
producers:

```text
topology-derived records present
AND their exact source_id/source_version identity is missing or inconsistent
-> accept the otherwise valid snapshot
-> mark topology-derived capability unavailable
-> reason TOPOLOGY_SOURCE_VERSION_MISSING
```

Explain must neither reject the whole snapshot solely for this capability
failure nor merge records across different source IDs or versions.

## Explain capability behavior

Add `TOPOLOGY_SOURCE_VERSION_MISSING` as a stable topology capability reason.
Before topology computation, adapters/index builders distinguish three cases:

1. No relevant topology data: retain the existing capability-specific
   unavailable reason.
2. Relevant topology data exists but any required source identity/version is
   missing, blank or internally inconsistent: return
   `TOPOLOGY_SOURCE_VERSION_MISSING`.
3. One complete, internally consistent source identity exists: isolate records
   by `(source_id, source_version, relation_type)` and continue normal
   capability checks.

This gate applies to topology-derived `Dep_*` providers and to Tier-2
`UNAVOIDABLE_DEPENDENCY`, `PROPAGATION_HYPOTHESIS` and
`DEPENDENCY_SCOPE_OVERLAP_SIGNAL`. For pair evidence, whose public contract has
no separate reason field, the stable reason token is retained in the
unavailable detail. Tier-2 returns it in its existing structured `reason`
field. Scope remains anchored to the dominator and inherits the unavailable
topology-source condition.

Topology-derived public API output exposes these four fields explicitly rather
than requiring the operator to parse a derivation tag:

```text
scenario_id
generator_version
source_id
source_version
```

Tier-2 dominator, propagation and scope views add those fields to their existing
provenance projection. Pair evidence views do the same for `Dep_*` outputs.
Internally, `source_ref` remains the non-mixable `source_id@source_version`
identity used by indexes, derivation deduplication and caches.

These values are trace data only. Synthetic source kind remains ineligible for
production validation.

## Version and failure invariants

- Same `generator_version` plus different topology source versions is valid and
  produces different source identities/cache inputs.
- Different `generator_version` plus the same topology source version is valid;
  topology identity remains the same while generation provenance differs.
- A topology-derived scenario without a topology source version fails at the
  mock boundary.
- A scenario without topology-derived blocks does not require a topology source
  version.
- A foreign canonical payload with topology records but no source version keeps
  the snapshot usable while all affected topology capabilities return
  `UNAVAILABLE / TOPOLOGY_SOURCE_VERSION_MISSING`.
- HTTP and Kafka serialization of the same generated package preserve identical
  topology and generation provenance.

## Acceptance

The synthetic P2 acceptance path generates a directed scenario with exact
alarm-resource mappings and timestamps, publishes it through Kafka, waits for
Tier-1A readiness, requests a chain and runs Tier-2. It proves that the API
returns available P2 topology results whose source identity is the scenario's
declared topology source version and whose generation provenance identifies the
independent generator version.

Production replay behavior remains unchanged: undirected or otherwise
insufficient topology stays fail-closed. Synthetic acceptance is implementation
evidence, not production validation.

## Non-goals

- Inferring a topology source version from `generator_version`.
- Promoting synthetic topology to production-validation evidence.
- Relaxing directed-topology, mapping, temporal or propagation-config gates.
- Changing Kafka chunk/barrier ordering, checksums or snapshot completion.
- Adding topology hypotheses to normalized audit, membership or validation.
