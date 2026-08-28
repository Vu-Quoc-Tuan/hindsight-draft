# Testing & Expected Contracts

## Layer 1 — Parser tests

Alarm CSV:
- parses exactly 8,714 records from current export,
- supports 26,508 physical lines,
- preserves quoted multiline content.

topoIP:
- parses exactly 201,977 rows,
- keeps all 16 columns,
- parses `update_time_vipa`.

## Layer 2 — Normalization tests

- raw values preserved,
- future timestamp flagged,
- end-before-start flagged,
- no silent repair,
- missing fields become explicit null/quality flags.

## Layer 3 — Golden tests

2214039:
- member_count = 58,
- rule count = 3,
- merge = OR,
- characteristic 1653 has FULL_PAIR_SPACE sanity,
- 435/378 remain aggregate characteristics,
- no exact pair edges synthesized,
- topology mapping remains UNMAPPED.

## Layer 4 — Synthetic scenario tests

- same seed => same output,
- synthetic resources use SYN-* IDs,
- synthetic source never becomes real validation,
- directed hierarchy enables only hierarchy capability,
- active-path scenario stores explicit paths,
- H_domain stays a set/hyperedge.

## Layer 5 — Contract equivalence

Direct Snapshot and Kafka adapter (when added) must produce identical canonical state for the same scenario.

## Layer 6 — Negative tests

Must fail:
- mapping `DEHL01` to `HLC9102*` by prefix,
- treating undirected topoIP as active path,
- inserting raw score 2.0 into normalized evidence,
- using NocPro 72 historical pairs as behavioral H,
- changing Golden fixture to make an expected Explain verdict pass.
