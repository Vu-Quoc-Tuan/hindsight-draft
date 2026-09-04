#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_dir"

export COMPOSE_PROJECT_NAME="${NOCPRO_E2E_COMPOSE_PROJECT:-nocpro-acceptance}"
export POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-55432}"
export KAFKA_HOST_PORT="${KAFKA_HOST_PORT:-29092}"
export API_HOST_PORT="${API_HOST_PORT:-8800}"
export WEB_HOST_PORT="${WEB_HOST_PORT:-3300}"
export TIER1A_RECOVERY_INTERVAL_SECONDS="${TIER1A_RECOVERY_INTERVAL_SECONDS:-0.25}"
export NOCPRO_E2E_KAFKA="127.0.0.1:${KAFKA_HOST_PORT}"
export NOCPRO_E2E_DATABASE_URL="postgresql://nocpro:nocpro@127.0.0.1:${POSTGRES_HOST_PORT}/nocpro"
export NOCPRO_E2E_BASE_URL="http://127.0.0.1:${WEB_HOST_PORT}"
export NOCPRO_E2E_API_URL="http://127.0.0.1:${API_HOST_PORT}"

cleanup() {
  if [[ "${KEEP_E2E_STACK:-0}" == "1" ]]; then
    docker compose ps
    return
  fi
  docker compose down --volumes --remove-orphans
}
trap cleanup EXIT

docker compose down --volumes --remove-orphans
if [[ "${NOCPRO_E2E_SKIP_BUILD:-0}" == "1" ]]; then
  # Useful when a verified local image already exists and the registry is
  # temporarily unavailable. CI and normal acceptance still rebuild by default.
  docker compose up -d migrate api web
else
  docker compose up -d --build migrate api web
fi

wait_for_postgres() {
  local deadline=$((SECONDS + 60))
  until docker compose exec -T postgres pg_isready -U nocpro -d nocpro >/dev/null; do
    if (( SECONDS >= deadline )); then
      docker compose logs --no-color postgres migrate api
      echo "PostgreSQL did not become ready for host-side migration acceptance" >&2
      exit 1
    fi
    sleep 1
  done
}

wait_for_snapshot_ready() {
  local snapshot_id="$1"
  local deadline=$((SECONDS + 120))
  local state=""
  while (( SECONDS < deadline )); do
    state="$(docker compose exec -T postgres psql -U nocpro -d nocpro -At -c \
      "SELECT concat_ws('|', status, tier1a_status, lineage_status, similarity_status) FROM snapshot_ingest WHERE snapshot_id='${snapshot_id}' AND snapshot_version='1';")"
    if [[ "$state" == "COMPLETE|READY|READY|READY" ]]; then
      return 0
    fi
    sleep 1
  done
  docker compose logs --no-color api
  echo "snapshot ${snapshot_id} failed acceptance readiness: ${state:-missing}" >&2
  return 1
}

wait_for_postgres

NOCPRO_RUN_DOCKER_E2E=1 PYTHONPATH="../nocpro-mock/src" \
  .venv/bin/python -m pytest tests/e2e/test_postgres_migrations_runtime.py -q

# Exercise recovery/duplicate delivery before the large real replay.  These
# tests deliberately restart the API and must not race unrelated Tier-2 work
# from a previous browser scenario.
NOCPRO_RUN_DOCKER_E2E=1 PYTHONPATH="../nocpro-mock/src" \
  .venv/bin/python -m pytest tests/e2e/test_docker_failures.py -q

snapshot_id="acceptance-real-$(date -u +%Y%m%dT%H%M%SZ)"
raw_alarm_csv="../nocpro-mock/datasets/raw/alarm/alarm_data.csv"
if [[ -f "$raw_alarm_csv" ]]; then
  MOCK_SNAPSHOT_ID="$snapshot_id" MOCK_SNAPSHOT_VERSION=1 \
    docker compose --profile replay run --rm --no-deps mock-producer

  wait_for_snapshot_ready "$snapshot_id"

  # The browser scenarios intentionally depend on different active snapshots:
  # real replay for core WHY/Audit, synthetic P2 for Evolution, and synthetic
  # Counterfactual for Review.  Do not execute the whole suite against the
  # real replay before those later fixtures have been ingested.
  pnpm --dir services/web exec playwright test e2e/operator-flow.spec.ts

  curl -fsS "http://127.0.0.1:${API_HOST_PORT}/api/v1/chains/6907125" \
    -o /tmp/nocpro-acceptance-largest-chain.json \
    -w 'tier1b_chain_1072_seconds=%{time_total}\n'
else
  echo "production_replay_acceptance=SKIPPED_RAW_ALARM_EXPORT_MISSING"
fi

# This separately proves the only real topology evidence permitted today:
# exact alarmIP identity mapping + undirected topoIP hop proximity. The result
# remains Dep_hop only; it does not establish any directed dependency claim.
ip_snapshot_id="acceptance-ip-topology-$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -f "../nocpro-mock/datasets/raw/alarm/alarmIP.csv" && -f "../nocpro-mock/datasets/raw/topo/topoIP.csv" ]]; then
  MOCK_IP_SNAPSHOT_ID="$ip_snapshot_id" MOCK_IP_SNAPSHOT_VERSION=1 \
    docker compose --profile replay-ip run --rm --no-deps mock-producer-ip
  wait_for_snapshot_ready "$ip_snapshot_id"
  curl -fsS "http://127.0.0.1:${API_HOST_PORT}/api/v1/chains/6912465/pairs/3960289954/3960289955" \
    | .venv/bin/python -c '
import json
import sys
payload = json.load(sys.stdin)
dep_hop = next((item for item in payload["evidence"] if item.get("channel_family") == "Dep_hop"), None)
assert dep_hop is not None, payload
assert dep_hop["state"] == "SUPPORT", dep_hop
assert dep_hop["source_version"].startswith("sha256:"), dep_hop
'
  echo "ip_topology_dep_hop_acceptance=PASS"
else
  echo "ip_topology_dep_hop_acceptance=SKIPPED_IP_INPUT_MISSING"
fi

ANALYSIS_CONFIG_PATH="/app/config/thresholds/e2e-p2.yaml" \
  docker compose up -d --force-recreate api
deadline=$((SECONDS + 60))
until curl -fsS "http://127.0.0.1:${API_HOST_PORT}/api/v1/health" >/dev/null; do
  if (( SECONDS >= deadline )); then
    docker compose logs --no-color api
    echo "API did not restart with synthetic P2 acceptance config" >&2
    exit 1
  fi
  sleep 1
done
NOCPRO_RUN_DOCKER_E2E=1 PYTHONPATH="../nocpro-mock/src" \
  .venv/bin/python -m pytest tests/e2e/test_synthetic_p2_kafka.py -q
pnpm --dir services/web exec playwright test e2e/evolution.spec.ts

# T_delay's synthetic sequence has authoritative taxonomy only in its explicit
# test adapter.  Run that frozen-model/Pair-WHY suite beside the Kafka stages;
# the production container must still fail closed when no authoritative
# taxonomy source is configured.
PYTHONPATH="../nocpro-mock/src:services/analysis-worker" \
  .venv/bin/python -m pytest \
    tests/test_temporal_delay_model.py tests/test_historical_pair_why.py -q

ANALYSIS_CONFIG_PATH="/app/config/thresholds/e2e-counterfactual.yaml" \
  docker compose up -d --force-recreate api
deadline=$((SECONDS + 60))
until curl -fsS "http://127.0.0.1:${API_HOST_PORT}/api/v1/health" >/dev/null; do
  if (( SECONDS >= deadline )); then
    docker compose logs --no-color api
    echo "API did not restart with synthetic Counterfactual acceptance config" >&2
    exit 1
  fi
  sleep 1
done
NOCPRO_RUN_DOCKER_E2E=1 PYTHONPATH="../nocpro-mock/src" \
  .venv/bin/python -m pytest tests/e2e/test_counterfactual_review.py -q
pnpm --dir services/web exec playwright test e2e/counterfactual-review.spec.ts

echo "acceptance_snapshot=${snapshot_id}"
echo "production_delta_validation=BLOCKED_BY_DATA_AVAILABILITY"
echo "production_delta_implementation=READY"
echo "production_delta_empirical_threshold=NOT_ESTABLISHED"
