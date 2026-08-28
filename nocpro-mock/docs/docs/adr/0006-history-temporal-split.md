# ADR-MOCK-0006 — History bootstrap precedes the target snapshot

- Status: Accepted

## Decision

Synthetic/backfill history is built only from periods before the target snapshot.

Target snapshot does not enter history before it is emitted/evaluated.

## Invariant

A scenario cannot use the target chain itself to manufacture prior-history support.
