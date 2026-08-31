# Integrated Synthetic Temporal Topology Design

## Goal

Add one deterministic synthetic sequence that exercises the production-shaped
snapshot pipeline and the directed-topology capabilities that current real
exports cannot provide. The fixture is implementation evidence only and must
never be presented as production validation.

## Scenario

The scenario ID is `synthetic_temporal_topology_v1`. It contains six complete
snapshots at one-minute logical intervals. Membership transitions cover:

```text
CONTINUE -> GROW -> SPLIT -> MERGE -> SHRINK
```

Every snapshot is an ordinary canonical `MockSnapshotPackage`; no new
multi-snapshot wire format is introduced. Sequence order lives in the existing
manifest and every timestamp is explicitly UTC-qualified.

## Topology and mapping

Each snapshot carries the same small directed dependency topology:

```text
SYN-CORE-01
    -> SYN-AGG-01
        -> SYN-DEVICE-01
        -> SYN-DEVICE-02
        -> SYN-DEVICE-03
        -> SYN-DEVICE-04
```

The topology includes:

- directed `LOGICAL_DEPENDENCY` edges;
- exact alarm-to-resource mappings;
- explicit ordered active paths from devices to the core;
- one synthetic failure domain represented as a hyperedge, never clique
  projected;
- exact topology source identity and independent generation provenance.

The source contract is:

```yaml
source_kind: SYNTHETIC_TEST
generator_version: mockgen-integrated-v1
topology_source:
  source_id: synthetic-topology
  source_version: syn-topo-temporal-v1
```

`generator_version` is not a fallback for `topology_source.source_version`.

## Data flow

```text
scenario manifest + deterministic fixture
  -> nocpro-mock canonical packages
  -> Kafka SNAPSHOT_CHUNK + SNAPSHOT_COMPLETE
  -> Explain PostgreSQL ingest
  -> Tier-1A in logical snapshot order
  -> lineage and snapshot-versioned SimilarityModel
  -> lazy Tier-1B
  -> on-demand Tier-2 topology hypotheses
```

HTTP/direct loading remains a unit-test oracle, not the integration acceptance
path for this scenario.

## Required observations

The sequence acceptance verifies:

- all six snapshots become complete and Tier-1A READY in logical order;
- lineage emits the intended continue/grow/split/merge/shrink behavior;
- Similar Chains trains strictly on `history < snapshot_time`;
- exact mapping enables dependency channels without fuzzy identity inference;
- shared ancestor and shared active path retain one dependency derivation
  regime for the same topology source;
- dominator, configured propagation and dependency-scope overlap are available
  under the synthetic acceptance config;
- API output retains `scenario_id`, `generator_version`, `source_id` and
  `source_version` independently;
- no synthetic result becomes validation-eligible.

## Failure behavior

The existing fail-closed rules remain unchanged:

- missing topology source version disables affected topology capability;
- missing or ambiguous mapping produces `UNAVAILABLE`;
- missing directed semantics cannot be replaced with undirected adjacency;
- missing propagation configuration produces
  `PROPAGATION_CONFIG_INCOMPLETE`;
- incomplete Kafka assemblies never trigger Tier-1A.

## Non-goals

- Do not modify or supplement real alarm/topology exports.
- Do not establish production delta thresholds.
- Do not calibrate production propagation parameters.
- Do not claim causal proof, root cause, production topology validation or
  production evolution validation.
- Do not add full motifs, KEDB, under-merge or other unopened P2 extensions.
