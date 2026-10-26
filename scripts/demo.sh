#!/usr/bin/env bash
# Tally in one go: compose up, seed, post an entry and replay it, pay an invoice through
# stripe-mock and the webhook, run the Airflow report DAG, print balances and a trace link.
# Needs Docker and uv. Leaves compose running; stops the Django and Celery processes it started.
set -euo pipefail
cd "$(dirname "$0")/.."
started=$(date +%s)
step() { printf '\n\033[1m[%3ss] %s\033[0m\n' "$(( $(date +%s) - started ))" "$*"; }

API=http://localhost:8001
cp -n .env.example .env 2>/dev/null || true   # compose defaults: stripe-mock, RustFS, Jaeger
set -a; . ./.env; set +a
export STRIPE_WEBHOOK_SECRET="${STRIPE_WEBHOOK_SECRET:-whsec_demo}" INTERNAL_TOKEN="${INTERNAL_TOKEN:-dev-internal-token}"
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}"  # an older .env may lack it

step "compose up (Postgres, Redis, stripe-mock, RustFS, Jaeger, Airflow)"
# --wait fails on the one-shot bucket job exiting 0, so run it on its own afterwards.
docker compose --profile batch up -d --wait postgres redis stripe-mock s3 jaeger airflow
docker compose up s3-init 2>&1 | tail -1

step "migrate and seed"
uv sync --locked -q
uv run python manage.py migrate -v0
uv run python manage.py seed_demo

step "start Django, Celery worker and Beat"
NORELOAD=1 LOG_LEVEL=warning scripts/serve.sh >/tmp/tally-demo-serve.log 2>&1 &
trap 'kill %1 2>/dev/null' EXIT   # serve.sh stops its three processes on TERM
curl -sf --retry 30 --retry-connrefused --retry-delay 1 "$API/health" >/dev/null
KEY=$(uv run python manage.py issue_api_key --tenant "Acme Corp" --name demo | tail -1)
auth=(-H "X-Api-Key: $KEY" -H "Content-Type: application/json")

step "post an entry, then replay the same Idempotency-Key"
body='{"occurred_at":"2026-10-24T09:00:00Z","source":{"type":"demo","id":"1"},"lines":[{"account":"1200","amount":"120.000000","currency":"USD"},{"account":"4000","amount":"-120.000000","currency":"USD"}]}'
idem="demo-$(date +%s)"
curl -s "${auth[@]}" -H "Idempotency-Key: $idem" -d "$body" -D - -o /dev/null "$API/api/entries" | grep -E "^HTTP|Idempotent-Replayed"
curl -s "${auth[@]}" -H "Idempotency-Key: $idem" -d "$body" -D - -o /dev/null "$API/api/entries" | grep -E "^HTTP|Idempotent-Replayed"

step "pay an invoice: PaymentIntent on stripe-mock, signed webhook back to the API"
uv run python manage.py demo_payment --tenant "Acme Corp"

step "settle yesterday and run the partner_daily_report DAG"
uv run python manage.py shell -c "from tally.adapters.tasks import settle_yesterday; print('settled', settle_yesterday())"
run_id="demo_$(date +%s)"
docker compose exec -T airflow airflow dags trigger partner_daily_report --run-id "$run_id" >/dev/null 2>&1
for _ in $(seq 1 60); do
  state=$(docker compose exec -T airflow airflow dags state partner_daily_report "$run_id" 2>/dev/null | tail -1)
  [[ "$state" == "success" || "$state" == "failed" ]] && break
  sleep 3
done
echo "dag run $run_id: $state"
curl -s "${auth[@]}" "$API/api/reports" | python3 -c "import sys,json; [print(f'report {r[\"day\"]} {r[\"size\"]} bytes') for r in json.load(sys.stdin)[:3]]"

step "balances"
for code in 1000 1200 4000; do
  curl -s "${auth[@]}" "$API/api/accounts/$code/balance" | python3 -c "import sys,json; b=json.load(sys.stdin); print(f'{b[\"account\"]}: {b[\"balance\"]} {b[\"currency\"]}')"
done

step "done in $(( $(date +%s) - started ))s"
echo "traces:   http://localhost:16687/search?service=tally"
echo "airflow:  http://localhost:8081   console: $API (ops / ops-demo, after 'make console')"
echo "metrics:  curl -H 'X-Internal-Token: $INTERNAL_TOKEN' $API/internal/metrics"
