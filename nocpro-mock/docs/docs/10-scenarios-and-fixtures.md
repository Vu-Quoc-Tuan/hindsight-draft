# Scenario & Fixture Model

## Directory classes

```text
datasets/
├── raw/
│   ├── alarms/
│   └── topology/
├── golden/
│   └── chain_2214039/
├── synthetic/
│   ├── dependency_hierarchy/
│   ├── active_path/
│   ├── failure_domain/
│   ├── weak_member/
│   ├── insufficient_data/
│   ├── split_merge/
│   ├── history/
│   └── context/
└── generated/
```

## Scenario schema

Minimum:

```yaml
scenario_id: ...
scenario_version: ...
seed: ...
base_fixture: null
mutations: []
expected_contract_assertions: []
source_kind: SYNTHETIC_TEST
```

## Required scenario set

### Contract / provenance

- raw score out of range
- TimeWindow veto
- M_pair missing => UNKNOWN
- bounded pair coverage
- synthetic source cannot validate

### Topology

- exact mapped adjacency
- unmapped alarm
- ambiguous mapping
- directed hierarchy
- explicit active path
- failure-domain hyperedge

### Membership / data availability

- singleton
- temporal-only + others unavailable
- neutral-vs-unavailable
- two computable role groups
- very large chain shape

### Evolution

- stable membership new chain ID
- grow/shrink
- split
- merge
- recombination

### Data quality

- multiline content
- future timestamp
- end before start
- missing device
- stale topology
