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
docker compose up -d --build api web

NOCPRO_RUN_DOCKER_E2E=1 PYTHONPATH="../nocpro-mock/src" \
  .venv/bin/python -m pytest tests/e2e/test_postgres_migrations_runtime.py -q

snapshot_id="acceptance-real-$(date -u +%Y%m%dT%H%M%SZ)"
raw_alarm_csv="../nocpro-mock/datasets/raw/alarm_data.csv"
if [[ -f "$raw_alarm_csv" ]]; then
  MOCK_SNAPSHOT_ID="$snapshot_id" MOCK_SNAPSHOT_VERSION=1 \
    docker compose --profile replay run --rm mock-producer

  deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    state="$(docker compose exec -T postgres psql -U nocpro -d nocpro -At -c \
      "SELECT concat_ws('|', status, tier1a_status, lineage_status, similarity_status) FROM snapshot_ingest WHERE snapshot_id='${snapshot_id}' AND snapshot_version='1';")"
    if [[ "$state" == "COMPLETE|READY|READY|READY" ]]; then
      break
    fi
    sleep 1
  done
  if [[ "${state:-}" != "COMPLETE|READY|READY|READY" ]]; then
    docker compose logs --no-color api
    echo "snapshot ${snapshot_id} failed acceptance readiness: ${state:-missing}" >&2
    exit 1
  fi

  pnpm --dir services/web e2e

  curl -fsS "http://127.0.0.1:${API_HOST_PORT}/api/v1/chains/6907125" \
    -o /tmp/nocpro-acceptance-largest-chain.json \
    -w 'tier1b_chain_1072_seconds=%{time_total}\n'
else
  echo "production_replay_acceptance=SKIPPED_RAW_ALARM_EXPORT_MISSING"
fi

NOCPRO_RUN_DOCKER_E2E=1 PYTHONPATH="../nocpro-mock/src" \
  .venv/bin/python -m pytest tests/e2e/test_docker_failures.py -q

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
