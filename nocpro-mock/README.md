# nocpro-mock

Upstream replay, normalization and scenario simulator for `nocpro-chain-explain`.

It replays observed data and emits versioned Input Contract snapshot packages. It
does not reimplement NocPro chaining or any Explain methodology.

Design docs live in `docs/`. Start with `docs/README.md` and
`docs/IMPLEMENTATION_BRIEF_FOR_AI.md`.

## Status — P0 and P0.5 implemented

| Capability | State |
|---|---|
| Alarm CSV loader (multiline, BOM, quality flags) | done |
| topoIP loader (adjacency + freshness) | done |
| Real-data profile catalog + topology tree read model | done |
| topoIT directed source-relation navigation graph | done |
| Canonical models + raw preservation | done |
| Direct Snapshot producer with contract validation | done |
| Observed `chaining_id` replay incl. singletons | done |
| Golden 2214039 fixture replay | done |
| Exact-identity alarm-resource mapping (fail closed) | done |
| topoIT structural aliases | navigation-only; not an alarm-resource mapping authority |
| Synthetic directed hierarchy / active path / failure domain | done |
| Synthetic operational context | done |
| Synthetic operator-feedback ground-truth fixture | done, synthetic-only |
| System pair metadata (explicit + deterministic generator) | done |
| History / evolution sequences via manifest + step mode | done |
| Kafka chunk + completion-barrier producer | done |
| `fast` / `realtime` replay, alias-table file (P1) | not started |

The canonical contract lives in `../nocpro-chain-explain/contracts/v1` per
ADR-0002 and is imported read-only through `nocpro_mock.contract`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Usage

```bash
# Real input profiles are intentionally non-interchangeable
# ALARM_ONLY = alarm/alarm_data.csv without topology
# IP_NETWORK = alarm/alarmIP.csv + topo/topoIP.csv (undirected adjacency)
# IT_SERVICES = alarm/alarmIT.csv + topo/topoIT/ (directed source relations,
# not operational dependency edges)
nocpro-mock topology-tree --profile ALARM_ONLY
nocpro-mock topology-tree --profile IP_NETWORK --max-depth 2 --max-children 12
nocpro-mock topology-tree --profile IT_SERVICES --root-id it:service:1

# Emit a Direct Snapshot package for one observed chain
nocpro-mock replay --chain-id 6907125 --out datasets/generated/chain.json

# Include real topoIP adjacency in a canonical replay (slower; ~200k edges)
nocpro-mock replay --chain-id 6907125 --with-topology --out datasets/generated/chain.json

# Replay the Golden Gray-box fixture
nocpro-mock golden --with-topology --out datasets/generated/golden.json

# Publish the canonical snapshot to Explain through Kafka
nocpro-mock replay \
  --snapshot-id replay-001 \
  --snapshot-version 1 \
  --kafka-bootstrap localhost:9092 \
  --chunk-target-bytes 2097152

# Materialize the history/evolution sequence fixtures, then step through one
nocpro-mock build-sequences
nocpro-mock run-sequence docs/examples/synthetic/history_positive_lift
nocpro-mock run-sequence docs/examples/synthetic/evolution_split_merge

# Launch the interactive Web UI with explicit 'Push to Kafka' button
nocpro-mock ui --port 8085
```

## Synthetic operator feedback

`docs/examples/synthetic/operator_feedback/feedback.json` is a typed mock of
operator acceptance/rejection labels for the existing REMOVE/MOVE/MERGE
fixtures.  It exercises future empirical-evaluation plumbing, but it is
explicitly `SYNTHETIC_TEST` and
`eligible_as_production_ground_truth=false`; it must never calibrate or validate
production recommendations.

Kafka publication serializes canonical JSON, calculates the whole-snapshot
SHA-256 checksum, compresses it once with zstd, then emits idempotent
`SNAPSHOT_CHUNK` events followed by `SNAPSHOT_COMPLETE`. Every event uses
`snapshot_id` as its Kafka key. Explain remains responsible for assembly,
contract validation, persistence, and analysis.

## Sequences (history / evolution)

The canonical unit stays `1 MockSnapshotPackage = 1 snapshot`. Contract v1 gains
no multi-snapshot object, because sequencing is mock orchestration rather than a
NocPro input. A sequence is a directory:

```text
history_positive_lift/
├── sequence.yaml            # mock/runner artifact, never an Explain input
├── snapshot_000.json        # ordinary MockSnapshotPackage
├── ...
└── expected_assertions.yaml # known support/lift live here only
```

`HISTORY_BOOTSTRAP` is a delivery role, not a provenance value: synthetic
snapshots keep `source_kind=SYNTHETIC_TEST` so the fact that they are synthetic
is never erased. `BACKFILL` is reserved for genuinely backfilled real state.

`delivery.history_until_exclusive` marks the target boundary, so history is
strictly before the target and a chain cannot support its own prior history.

## Tests

```bash
.venv/bin/python -m pytest tests            # all
.venv/bin/python -m pytest tests -m "not realdata"   # skip the 680 MB exports
```

Tests are organized by the layers in `docs/docs/13-testing-and-expected-contracts.md`.
Layer 1 asserts the frozen source counts literally, and Layer 6 pins the
forbidden shortcuts (prefix mapping, directed adjacency, synthetic validation).

## Verified source profile

Reproduced by the loaders and asserted in `tests/test_layer1_parsers.py`:

```text
alarm_data.csv   8,714 records / 96 columns / 26,508 physical lines
                 2,824 chaining_id, 2,072 singleton (73.3711%)
                 max chain 1,072 (id 6907125), 309 device_code
                 node_reference fill 98.0606%
                 dirty: 2 future timestamps, 360 end < start
topoIP           201,977 rows / 16 columns, SITE_ROUTER source 90.3860%
                 99,781 unique devices, 176 self-adjacency rows dropped
```

## Non-negotiable behavior

- Raw values are preserved; dirty data is flagged, never repaired.
- `topoIP` edges stay `IP_ADJACENCY` with `directed=False`.
- Exact-mapped IP alarm pairs can report bounded undirected `Dep_hop`
  proximity when the topoIP content fingerprint is carried with the replay.
  This is not an upstream/downstream or causal dependency statement.
- Real-data navigation profiles remain semantically separate:
  - `ALARM_ONLY` reports topology `UNAVAILABLE`.
  - `IP_NETWORK` projects only undirected `ADJACENT_TO` records.
  - `IT_SERVICES` projects directed `SOURCE_RELATION` records such as
    `SERVICE_HAS_MODULE`; these are not verified dependency/causal edges.
- The IT source can contain cycles and multi-parent links. The UI read model
  returns a bounded tree projection with deterministic technical primary paths
  and cycle/reference badges; the primary path is not ownership semantics.
- Real IT source relations do not enable `Dep_upstream`, ancestor, dominator,
  propagation, scope-overlap, or any other P2 dependency capability.
- Every topology-navigation response carries a first-class profile capability
  artifact. `ALARM_ONLY` is unavailable; IP exposes only undirected adjacency;
  IT exposes directed source relations with `dependency_semantics=UNVERIFIED`.
  The navigation endpoint itself does not establish a complete alarm-resource
  mapping contract. Separately, the offline mapper supports exact identity
  matches: the current IP export has partial `device_code` coverage, while IT
  has only limited matches to canonical resource IDs. Those partial matches do
  not promote topology into Explain P2.
- `topoIT` aliases are still `UNAVAILABLE` for production alarm mapping until a
  source-backed, exact and unambiguous mapping contract is supplied; names and
  prefixes are never used as a heuristic bridge.
- Mapping is exact-identity or verified-alias only. The Golden DEA resources
  (`DEHL01`, `DEHT01`, `HLC9102DEA01`, `HHT9603DEA01`) resolve to `UNMAPPED`
  even though `HLC9102*` / `HHT9603*` prefixes exist in the export.
- Aggregate characteristics are never expanded into pair edges.
- Missing pair metadata is `UNKNOWN`, never `NEUTRAL`.
- Golden fixtures are read-only; variants are clones with `SYNTHETIC_TEST` provenance.
- `SYNTHETIC_TEST` / `BACKFILL` can never validate.
- Failure domains stay hyperedges; `clique_project: true` is refused.
- A TimeWindow veto keeps `raw_score=-999999999` plus `system_semantic=VETO`;
  raw score `2.0` is preserved, never clamped into `[0,1]`.
- `coverage_scope` is batch/export level, never repeated per pair.
- Every `M_pair` carries `attribute_ref`, so a raw score is interpretable.
- The mock never emits `H.support` / `H.lift`; downstream computes them.
