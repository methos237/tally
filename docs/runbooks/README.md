# Runbooks

Each runbook is symptom first: what you see, how to confirm, what to do, how to stop it
recurring. All commands run from the repo root with compose up and `.env` present.

| Symptom | Runbook |
|---|---|
| `tally_webhook_deliveries{state="dead"}` climbing, tenants report missing webhooks | [dead-letter-growth.md](dead-letter-growth.md) |
| `tally_projection_lag_seconds` above zero, balances disagree with the journal | [projection-lag.md](projection-lag.md) |
| Invoices stay `open` after payment, Stripe dashboard shows webhook failures | [stripe-webhook-failures.md](stripe-webhook-failures.md) |
| Nothing bills, nothing delivers, `tally_celery_queue_depth` flat at zero | [beat-not-firing.md](beat-not-firing.md) |

Where to look:

- `/internal/metrics` (header `X-Internal-Token`, value of `INTERNAL_TOKEN`) for the gauges named above
  and request latency per view.
- Jaeger at <http://localhost:16687>, service `tally`: one trace per API request, including the
  outbox write and the Celery delivery that followed it.
- Structured JSON logs on stdout of `make dev` (Django, worker, Beat share the terminal).
