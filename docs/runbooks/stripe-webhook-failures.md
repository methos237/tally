# Stripe webhook failures

## Symptom

Invoices stay `open` after `collect_invoice` ran; Stripe's dashboard (Developers,
Webhooks) shows failed deliveries to `/webhooks/stripe`; or `stripe listen` prints
`[400]` or `[500]` lines.

## How the path works

Stripe posts to `POST /webhooks/stripe`. Tally verifies `Stripe-Signature` with
`STRIPE_WEBHOOK_SECRET` (5 minute tolerance), inserts `event.id` into `stripe_events`,
answers 200, and `process_stripe_event` applies it from Celery. Only the webhook marks an
invoice paid or a subscription past due; the charge itself never does.

## Confirm

```bash
rtk psql postgresql://tally:tally@localhost:5435/tally -c "
  SELECT event_id, type, received_at, processed_at FROM stripe_events
  ORDER BY received_at DESC LIMIT 20"
```

| What you see | Meaning |
|---|---|
| Stripe shows 400, nothing in `stripe_events` | Signature rejected: wrong `STRIPE_WEBHOOK_SECRET`, or the body was altered by a proxy |
| Stripe shows connection errors | Django unreachable from Stripe (local: `stripe listen` not running) |
| Rows with `processed_at IS NULL` | Received but not applied: the Celery worker is down or the task failed (worker log) |
| Rows processed, invoice still open | The intent id does not match an invoice: the event was for a PaymentIntent Tally did not create (`stripe trigger` fixtures do this on purpose) |

## Fix

1. Secret mismatch: `scripts/stripe-listen.sh` prints the `whsec_` for the local forwarder;
   for a dashboard endpoint copy the signing secret from Stripe. Put it in `.env`, restart
   `make dev`. Stripe retries failed deliveries for up to three days on its own.
2. Unprocessed rows: start the worker (`make dev`), or requeue by hand:

   ```bash
   uv run python manage.py shell -c "
   from tally.adapters.models import StripeEvent
   from tally.adapters.tasks import process_stripe_event
   for r in StripeEvent.objects.filter(processed_at__isnull=True): process_stripe_event.delay(r.id)"
   ```

   Processing is idempotent: a row already processed returns `already processed`.
3. Missed events entirely (Stripe gave up): Developers, Events, Resend on the event. The
   unique `event_id` makes a resend harmless.
4. Verify the invoice moved: `GET /api/invoices?status=open` for the tenant, and the
   `payment` journal entry exists (`GET /api/entries?source_type=payment&source_id=<invoice id>`).

## Prevent

Alert on `stripe_events` rows older than five minutes with `processed_at IS NULL`, and on
the Stripe dashboard's endpoint error rate. Keep `STRIPE_WEBHOOK_SECRET` per environment;
the local forwarder and a dashboard endpoint have different secrets.
