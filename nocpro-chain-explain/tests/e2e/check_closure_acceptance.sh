#!/usr/bin/env bash
# Non-mutating closure preflight.  It never starts, stops, or inspects Docker.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mock_dir="${repo_dir}/../nocpro-mock"

require_file() {
  local path="$1"
  [[ -f "$path" ]] || { echo "MISSING: $path" >&2; exit 1; }
}

require_file "${repo_dir}/docker-compose.yml"
require_file "${repo_dir}/tests/e2e/test_postgres_migrations_runtime.py"
require_file "${repo_dir}/tests/e2e/test_synthetic_p2_kafka.py"
require_file "${repo_dir}/tests/e2e/test_counterfactual_review.py"
require_file "${repo_dir}/migrations/versions/0008_temporal_delay_model.py"
require_file "${mock_dir}/docs/examples/synthetic/temporal_delay_patterns/sequence.yaml"
require_file "${mock_dir}/docs/examples/synthetic/counterfactual_merge/snapshot_000.json"
require_file "${mock_dir}/docs/examples/synthetic/temporal_topology/sequence.yaml"

cat <<'EOF'
closure_acceptance_preflight=READY
docker_action=NOT_STARTED_BY_PREFLIGHT
runtime_acceptance=NOT_RUN
required_scenarios:
  - temporal_delay_patterns_v1
  - synthetic_counterfactual_merge_v1
  - synthetic_temporal_topology_v1
required_stages:
  - Kafka chunk/barrier
  - PostgreSQL READY and persisted artifacts
  - Tier-1A then Tier-1B Pair WHY
  - Tier-2 Audit and Counterfactual Review
  - API restart hydration
  - Chromium/Playwright
execution:
  - bash tests/e2e/run_acceptance.sh
  - T_delay synthetic model/Pair WHY checks run with the explicit authoritative test adapter
note: run_acceptance.sh is the explicit Docker-starting command; this preflight never invokes it.
EOF
