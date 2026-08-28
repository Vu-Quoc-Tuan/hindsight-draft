# History & Operational Context

## Three different histories

Do not collapse:

```text
NocPro HistorySimilarity / UI characteristic
  -> SYSTEM_FACT

Explain grouping-history H
  -> BEHAVIORAL
  -> computed downstream, not by mock as evidence score

Ticket/incident/maintenance history
  -> EXTERNAL_OPERATIONAL
```

The mock may provide raw historical snapshots/episodes, but it must not compute downstream `H.support/lift` and pretend it is source truth.

## Bootstrap split

For synthetic or replay history:

```text
history window < target snapshot
```

Target snapshot must not be inserted into backfill before it is emitted/evaluated.

## Context scenarios

Mock may generate separate scenarios:
- planned maintenance with scope,
- ticket covering a subset,
- conflicting maintenance windows,
- operator label,
- fault injection with known affected set.

Synthetic context is for testing and cannot become real operational validation.

## Source kind

- real ticket replay => REAL_EXPORT_REPLAY
- synthetic ticket => SYNTHETIC_TEST
- training/backfill state => BACKFILL
