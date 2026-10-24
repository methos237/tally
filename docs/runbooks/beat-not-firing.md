# Beat not firing

## Symptom

Nothing bills (`bill_due_subscriptions`), nothing delivers (`deliver_due_webhooks`),
yesterday never settled (the Airflow sensor waits forever), `tally_celery_queue_depth`
stays at zero and `tally_webhook_deliveries{state="pending"}` grows.

## How scheduling works

Celery Beat with `django_celery_beat.schedulers:DatabaseScheduler` reads the schedule from
`CELERY_BEAT_SCHEDULE` in settings (`expire-idempotency` hourly, `bill-due-subscriptions`
every 60 s, `deliver-due-webhooks` every 10 s, `settle-yesterday` at 00:05 UTC) and writes
each run into `django_celery_beat_periodictask.last_run_at`. One Beat process per
deployment; two would double-schedule (the invoice unique constraint and the
`select_for_update(skip_locked=True)` on deliveries make that safe, but wasteful).

## Confirm

```bash
rtk psql postgresql://tally:tally@localhost:5435/tally -c "
  SELECT name, enabled, last_run_at, total_run_count FROM django_celery_beat_periodictask
  ORDER BY last_run_at DESC NULLS LAST"
ps aux | grep -E "celery -A tally (beat|worker)" | grep -v grep
```

| What you see | Meaning |
|---|---|
| No `beat` process | Beat is down (`make dev` runs it; in other setups it is its own process) |
| `last_run_at` current, queue depth rising, pending deliveries rising | Beat fine, worker down or stuck |
| `enabled = false` on a task | Someone disabled it in the database; Beat honours that |
| Beat log: `redis.exceptions.ConnectionError` | Broker unreachable: compose Redis on 6380 down, or `REDIS_URL` wrong |

## Fix

1. Start what is missing: `make dev` starts Django, one worker (`--pool solo`) and Beat.
   Standalone: `uv run celery -A tally beat -l info` and `uv run celery -A tally worker -l info`.
2. Disabled task: `UPDATE django_celery_beat_periodictask SET enabled = true WHERE name = '...'`.
3. Catch up after an outage: the next tick does it. `bill_due_subscriptions` invoices every
   elapsed period; `deliver_due_webhooks` sends everything whose `next_attempt_at` has passed;
   `settle_yesterday` only marks the previous day, so settle older days by hand with
   `POST /internal/settlement/<day>` (header `X-Internal-Token`) and rerun the DAG for them
   (`airflow backfill create ...`, see the README).
4. Broker down: `docker compose up -d --wait redis`. Beat reconnects on its own.

## Prevent

Alert when `max(last_run_at)` for `deliver-due-webhooks` is older than one minute, and on
`tally_webhook_deliveries{state="pending"} > 0` for more than five minutes.
