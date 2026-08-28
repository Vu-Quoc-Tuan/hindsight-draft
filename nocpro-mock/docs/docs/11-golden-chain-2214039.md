# Golden Scenario — Chain 2214039

## Purpose

Primary Gray-box integration fixture.

Tests:
- raw alarm normalization,
- observed chain membership,
- rule/merge metadata replay,
- aggregate characteristic typing,
- SYSTEM_FACT vs downstream post-hoc separation,
- two-block candidate visibility,
- fail-closed topology mapping.

## Observed facts

```text
chain_id = 2214039
member_count = 58
event_span = 14:30:02 -> 14:30:24
duration = 22s
```

Rules:

```text
CORE_CHAINING_REMOTE_NODE
  connector = 34/58
  extender = 6

CORE_CHAINING_REFERENCE_NODE
  connector = 58/58

CORE_CHAINING_DEFAULT
  connector = 18/58

merge = OR
```

Characteristics:

```text
1653 pair time <600s
435 pair node_reference = DEHL01
378 pair node_reference = DEHT01
153 pair same alarm_name
72 pair historical grouping
36 pair device_code = DEHL01
36 pair device_code = DEHT01
...
```

## Derived assertions

These are **derived sanity checks**, not automatically system facts:

```text
C(58,2) = 1653
=> characteristic <600s covers full pair space

C(30,2) = 435
C(28,2) = 378
30+28 = 58
=> aggregate reference counts are consistent with two complete blocks 30/28

C(18,2) = 153
=> same-name count is consistent with a complete block of 18

C(9,2) = 36
=> each device-code count is consistent with a block of 9
```

## Expected mock output

Golden must emit:
- chain/members,
- M_chain_rule,
- M_chain_characteristic,
- exact original alarm fields available in fixture,
- source provenance.

Golden must NOT emit unless sourced:
- exact M_pair score vectors,
- simiDict,
- A_ij,
- ΔQ,
- node movement,
- semantics of connector/extender beyond source labels.

## Topology

Current topoIP has no exact mapping for the relevant DEA resources.

Expected:

```text
mapping_status = UNMAPPED
```

Do not attach a synthetic topology to the Golden fixture.

If dependency testing is required, use a synthetic clone with SYN-* resources.

## Not an over-merge ground truth

Expected downstream behavior may include:
- detect two dominant reference blocks,
- generate a reference/entity candidate cut,
- show contrastive separation.

Do not assert:

```text
overmerge = true
NocPro is wrong
```

without external ground truth.
