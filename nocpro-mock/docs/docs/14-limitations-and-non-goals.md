# Limitations & Non-goals

## Not a NocPro clone

The mock does not promise byte-for-byte or algorithm-for-algorithm reproduction of NocPro chaining.

Observed outputs are replayed where available.

## Not a Louvain internals simulator

No fake:
- `A_ij`,
- ΔQ,
- node movement,
- modularity trace.

## Not an oracle

Synthetic scenario truth is only truth for that scenario.

It is not evidence about production NocPro correctness.

## Topology limitation

Current topoIP is useful for IP adjacency/freshness tests but does not cover the Golden DEA resources and does not expose active path semantics.

## topoIT limitation

Visible multi-layer topology is promising, but full archive schema is not frozen until the 7z content is extracted and verified.

## Alarm archive limitation

Large alarm archive is not profiled in this docs release.

## Evolution limitation

One export is not automatically a real snapshot sequence.

Synthetic evolution must be clearly labeled.

## Metadata limitation

`cah.chaining_explain` and `is_root_alarm` columns exist in the current alarm schema but are empty in the verified export. Do not fabricate values.
