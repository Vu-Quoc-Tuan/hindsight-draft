# Review History Runtime Hardening Design

## Goal

Repair the two findings from the live verification without weakening provenance
scope or changing review authorization: resolve the known temporal synthetic
snapshot profile from explicit catalog provenance, and prevent the in-process
POST test path from stalling on a synchronous FastAPI dependency.

## Profile resolution and unavailable UX

- Preserve the existing source and source-kind checks and all stronger profile
  evidence already present on the active snapshot or persisted ingest row.
- Add an explicit catalog mapping from the known temporal scenario provenance
  source ID `synthetic_temporal_topology_v1` to `IT_SERVICES`; do not infer this
  from a digest, snapshot-name fragment, or `SYNTHETIC_TEST` source kind.
- Read scenario source IDs from the active package's provenance manifest only
  when existing explicit profile fields do not resolve the profile. Accept the
  provenance mapping only when it resolves to one profile and does not conflict
  with other known profile evidence. Unknown, missing, or conflicting evidence
  remains unavailable (`409 REVIEW_HISTORY_SOURCE_PROFILE_UNAVAILABLE`).
- In the history view, translate that stable API detail into a Vietnamese
  message explaining that the snapshot lacks an unambiguous source profile and
  must be ingested with explicit provenance. Do not suggest a connection retry
  for this deterministic metadata condition; retain retry behavior for other
  errors.

## FastAPI reviewer dependency

- Keep `get_reviewer_principal` synchronous for its existing direct callers and
  unit tests.
- Add a thin `async def` dependency adapter for FastAPI routes. It calls the
  existing resolver, which only reads request headers and environment values;
  it does not perform blocking I/O.
- Use the adapter consistently for routes that depend on reviewer identity, so
  in-process POST tests do not send this trivial resolver through the AnyIO
  worker-thread path. Do not change identity-mode, role, scope, or HTTP error
  semantics.

## Alternatives considered

1. **Recommended:** map only explicitly cataloged provenance IDs, preserve
   fail-closed behavior otherwise, clarify the UI, and use the async dependency
   adapter. This fixes the known case without adding a schema migration or
   trusting generated snapshot IDs.
2. Change only the UI and override the identity dependency in the hanging test.
   This is smaller, but leaves the known catalog-backed snapshot unusable and
   does not prevent the same test-transport stall on other reviewer routes.
3. Add a new profile field to the snapshot contract and producer. This is a
   stronger long-term contract, but requires coordinated schema/producer work
   and re-ingestion of existing snapshots; it is outside this focused repair.

## Boundaries and verification

- No database migration, live database update, Kafka publish, or container
  restart is part of this change.
- Add backend regressions for the known provenance mapping, ambiguous/unknown
  provenance remaining fail-closed, and the unknown-job POST returning 404.
- Add frontend coverage for the specific unavailable-profile message and
  generic retryable errors.
- Run the focused API and web tests, relevant lint/build checks, and a read-only
  API check if the already-running service can use the updated code without a
  restart. Report separately if deployment/runtime validation remains pending.
