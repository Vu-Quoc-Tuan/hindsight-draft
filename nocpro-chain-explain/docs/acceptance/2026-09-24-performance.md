# Warm-chain performance acceptance

## Status: NOT RUN against a live acceptance API

No latency numbers are reported here. This implementation session did not
verify an isolated PostgreSQL/Kafka/API stack or receive authorization to
restart a stack and write/delete benchmark rows. Unit tests and SDK setup tests
prove the harness contract only; they are not runtime performance evidence.

## Safe benchmark contract

`benchmarks.run_runtime_review_benchmark` defaults to `read-only`. It verifies
the active snapshot identity through `GET /api/v1/snapshots`, then measures the
identity-pinned `GET /api/v1/chains/{chain_id}/overview-cards` projection. It
does not select a snapshot, submit a job, connect to PostgreSQL, invoke Docker,
or request a provider call. The CLI writes the JSON report only to its selected
output file (default `/tmp/hindsight-warm-chain.json`), outside the repository;
this is not a mutation of the target API/DB. Reports identify injected test responses as
`TEST_INJECTED_RESPONSE`, and production validation remains
`NOT_ESTABLISHED`.

The chain-list GET is intentionally excluded: the current handler may enqueue
snapshot-wide quality precomputation when automatic quality is enabled. Chain
analysis may persist resolved mappings; Deep Dive and Review reads may flush
pending persistence, and Review may invoke provider enrichment. Those paths
must not be mislabeled read-only.

The separate `acceptance-restart` mode requires `--allow-disruption`, an
explicit acceptance Compose project and database URL, exact container/project
labels, loopback-published API/PostgreSQL ports, and a matching
`current_database()`. It refuses to call the compatible latest-Review route if
the API container has a non-empty `AI_API_KEY` or `AI_BASE_URL`; that route may
flush pending Review persistence. It creates and removes uniquely named
benchmark Review rows and restarts only the verified API service. That mode
was not run.

## Verification performed

- Backend marker suite excluding real-data/PostgreSQL/Docker/E2E/Kafka-marked
  cases: **1,213 passed, 6 skipped, 48 deselected**.
- Benchmark/observability tests: **20 passed, 1 skipped**; bounded executor
  tests: **7 passed**.
- Evidence backend contract: **63 passed**; 10 selected API regressions passed
  outside the restricted sandbox, including worker-backed chain analysis.
- Web suite: **149 passed**; production build passed; `pnpm lint` passed with
  zero warnings.
- Isolated Chromium topology/evidence E2E: **1 passed**. The mock-backed flow
  asserts one Overview GET across Overview/Chain Detail/Topology, no write
  requests while opening evidence, and no browser console/page errors.
  The separate warm-chain performance E2E was not run because it requires an
  isolated persisted API and completed quality projection.
- Earlier optional OpenTelemetry extra check: **11 passed** in a temporary
  `/tmp` install target; `uv lock --check` passed. These are setup checks, not
  telemetry-export or API-latency proof.
- The browser fixture confirms request consolidation structurally, not its
  production latency impact. No API latency samples, dataset hash,
  workload/background-load measurement, database query count, browser timing,
  or production result is available yet.

## Measurements required to close acceptance

Run the read-only command only against a verified isolated API with its exact
active snapshot ID/version and at least 30 repetitions. Preserve raw timing
samples, READY/PENDING/UNAVAILABLE projection counts, machine CPU/RAM, commit,
provider mode, and background-load conditions. Keep the proposed p95 limits as
explicit pass/fail criteria; do not raise them to fit a result. Separately run
the disruptive recovery scenario only after the exact isolated acceptance
stack and target database have been explicitly approved.
