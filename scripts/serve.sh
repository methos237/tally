#!/usr/bin/env bash
# Django, one Celery worker (solo pool: the OTel exporter thread must not be forked away),
# Beat and the Temporal dunning worker, as one process group that `make dev` and
# scripts/demo.sh both use.
# LOG_LEVEL (default info) applies to Celery; runserver reloads unless NORELOAD=1.
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'kill $(jobs -p) 2>/dev/null' EXIT INT TERM
uv run python manage.py runserver ${NORELOAD:+--noreload} 8001 &
uv run celery -A tally worker -l "${LOG_LEVEL:-info}" --pool solo &
uv run celery -A tally beat -l "${LOG_LEVEL:-info}" &
uv run python manage.py dunning_worker &
wait
