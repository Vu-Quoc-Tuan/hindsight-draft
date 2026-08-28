# Data Classification & Provenance

Every emitted object must distinguish **origin**, **runtime use**, and **validation independence**.

## source_kind

```text
REAL_LIVE
REAL_EXPORT_REPLAY
SYNTHETIC_TEST
BACKFILL
```

Rules:
- `SYNTHETIC_TEST` never validates.
- `BACKFILL` means bootstrap/train/backfill state; it never validates.
- Historical real observations replayed as observations use `REAL_EXPORT_REPLAY`, not BACKFILL merely because they are old.
- REAL_LIVE / REAL_EXPORT_REPLAY only pass the first gate; they are not automatically independent.

## provenance_class

```text
SYSTEM_FACT
POST_HOC
BEHAVIORAL
EXTERNAL_OPERATIONAL
```

Mock primarily emits upstream facts/context; it must not reclassify downstream POST_HOC analysis.

## chaining_usage

```text
CONFIRMED_USED
CONFIRMED_NOT_USED
UNKNOWN
```

`chaining_usage` is resolved in context:

```text
source_id
source_version
chaining_config_version
executed_rule_set / attribute_set (if known)
snapshot/run context
```

Do not attach one global USED/NOT_USED flag to an entire topology store if different rules/configurations may use it differently.

Missing complete executed configuration => `UNKNOWN`.

## quality_status

```text
PASS
FAIL
UNKNOWN
```

The mock may compute source-quality inputs (freshness, mapping status, coverage), but final thresholds are config-versioned.

Missing required quality => UNKNOWN.

## System metadata types

```text
M_pair
  exact pair raw system score/veto/status

M_chain_rule
  rule / connector-extender / merge

M_chain_characteristic
  aggregate characteristic / pair_count / coverage_scope

M_attribute_config
  type / content / algorithmType / filterName / weight
```

Never put raw pair score inside `M_attribute_config`.

## system_pair_status

```text
EVALUATED
NOT_EVALUATED
UNKNOWN
```

Missing record defaults to UNKNOWN.

## coverage_scope

```text
FULL_PAIR_SPACE
BOUNDED_COMPARISON
UNKNOWN
```

Coverage scope is per characteristic/attribute export, not a blanket property of a whole chain.
