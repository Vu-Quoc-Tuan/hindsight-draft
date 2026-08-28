# Synthetic Augmentation Policy

Synthetic data is allowed and expected — but only as **explicit scenario augmentation**, never as silent completion of real data.

## Three dataset classes

```text
REAL EXPORT
  scale, distribution, parser, replay

GOLDEN OBSERVED FIXTURE
  integration fidelity and system metadata correctness

SYNTHETIC SCENARIO
  known ground truth / capability edge cases
```

## Golden immutability rule

Never modify a Golden fixture in place.

If a capability is missing, clone:

```text
base_fixture = golden_2214039
scenario_id = synthetic_2214039_dependency_variant
```

Then mutate with provenance.

## What SHOULD be mocked

### 1. Directed hierarchy

Needed to test CommonDependency `SHARED_ANCESTOR`.

Use synthetic resource names and explicit directed edges.

### 2. Active path

Needed to test `SHARED_ACTIVE_PATH`.

Store the path as first-class path data, not inferred shortest path.

### 3. Failure domains

Mock SRLG/power/rack/service-instance membership as hyperedges.

### 4. Operational context

Mock:
- maintenance,
- ticket,
- operator label,
- fault injection.

All synthetic. They test code paths, not real validation.

### 5. History

Mock controlled episodes with known:
- support,
- lift,
- family/type backoff,
- target snapshot exclusion.

Mark bootstrap as BACKFILL.

### 6. Evolution

Mock deterministic snapshot sequences:
- continue,
- grow,
- shrink,
- split,
- merge,
- recombination,
- chain-ID change with same membership,
- singleton → multi-member and reverse.

### 7. System pair metadata

Mock:
- score 2.0,
- veto -999999999,
- EVALUATED,
- NOT_EVALUATED,
- UNKNOWN,
- FULL_PAIR_SPACE vs BOUNDED_COMPARISON.

This tests Gray-box adapter typing.

## What SHOULD NOT be mocked into real fixtures

- missing DEA topology for chain 2214039,
- exact NocPro pair scores,
- exact Louvain edges,
- ΔQ,
- root-cause labels,
- `cah.chaining_explain`,
- active paths not present in source,
- ticket/maintenance that did not actually exist.

## Generation metadata

Every synthetic object includes:

```text
scenario_id
seed
generator_version
generation_rule
base_fixture_id (optional)
source_kind = SYNTHETIC_TEST
```

## Naming

Use obvious synthetic identifiers:

```text
SYN-CORE-01
SYN-AGG-HN-01
SYN-DEA-HN-01
SRLG-SYN-001
TICKET-SYN-001
```

Never reuse real-looking IDs to make the demo appear more realistic.
