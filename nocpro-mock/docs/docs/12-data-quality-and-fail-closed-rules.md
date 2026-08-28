# Data Quality & Fail-Closed Rules

## Alarm CSV

Required quality flags:

```text
MULTILINE_CONTENT
TIMESTAMP_FUTURE_OUTLIER
END_BEFORE_START
UNPARSEABLE_TIMESTAMP
MISSING_REQUIRED_ID
MISSING_DEVICE_CODE
MISSING_NODE_REFERENCE
```

Preserve raw and parsed values.

No silent correction.

## Topology

Required mapping/status behavior:

```text
UNMAPPED
AMBIGUOUS
EXACT
VERIFIED_ALIAS
```

Do not choose the “closest-looking” resource.

## Quality status

For validation-oriented source metadata:

```text
PASS
FAIL
UNKNOWN
```

Missing required freshness/coverage/mapping info => UNKNOWN.

Thresholds live in versioned config, not hardcoded in dataset generator.

## Missing system pair metadata

```text
missing -> UNKNOWN -> unavailable
```

Not NEUTRAL.

## Archives

Detect by magic bytes, not extension.

If file starts with 7z signature, invoke the correct extractor or mark source unavailable.

Do not claim full archive inspection if extraction failed.
