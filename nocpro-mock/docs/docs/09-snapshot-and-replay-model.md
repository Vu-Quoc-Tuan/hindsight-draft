# Snapshot & Replay Model

## Primary unit

Mock emits **complete snapshot packages**, matching the downstream snapshot boundary.

## Replay modes

### `snapshot`

Emit one complete snapshot and stop.

### `step`

Emit next snapshot only on command.

Best for Evolution debugging.

### `fast`

Replay temporal sequence with time compression.

### `realtime`

Replay according to observed timestamps when a genuine sequence exists.

## Important restriction

A single alarm export does not automatically provide a historical sequence of NocPro partitions.

Do not fabricate “real evolution” by slicing one export and pretending each slice is an observed NocPro snapshot unless the scenario is explicitly synthetic.

## Direct Snapshot first

Prototype path:

```text
nocpro-mock
  -> canonical JSON snapshot
  -> nocpro-chain-explain Direct Snapshot Adapter
```

Kafka comes later.

## Kafka if added

Kafka must preserve the same canonical semantics.

If multiple topics are used, define snapshot completeness/barrier semantics. Never assume cross-topic ordering.
