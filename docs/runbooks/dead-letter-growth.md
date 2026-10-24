# Dead-letter growth

## Symptom

`tally_webhook_deliveries{state="dead"}` rises; the console dashboard shows a dead-letter
count; a tenant says they stopped receiving `invoice.paid`.

## What a dead letter is

An outbox message that failed five delivery attempts (immediately, then 1 min, 5 min,
30 min, 2 h later). It keeps the last HTTP status or error and waits for a human. Nothing
retries it on its own.

## Confirm

```bash
curl -s -H "X-Internal-Token: $INTERNAL_TOKEN" localhost:8001/internal/metrics | grep tally_webhook_deliveries
rtk psql postgresql://tally:tally@localhost:5435/tally -c "
  SELECT e.url, count(*), min(o.dead_at), max(o.last_status), max(o.last_error)
  FROM webhook_outbox o JOIN webhook_endpoints e ON e.id = o.endpoint_id
  WHERE o.dead_at IS NOT NULL GROUP BY e.url ORDER BY 2 DESC"
```

One endpoint with every dead letter means the tenant's receiver is down or rejecting;
dead letters across every endpoint means the worker could not reach anything (DNS, egress)
or `deliver_webhook` itself is failing (check the worker log for tracebacks).

## Fix

1. Read `last_status` / `last_error`. `None` with "Connection refused" or a timeout is the
   receiver being unreachable; `401`/`400` is usually the tenant verifying with the wrong
   secret (secrets are shown once at `POST /api/webhook-endpoints`; a new endpoint is the
   only way to get a new one).
2. Once the receiver is healthy, redeliver. Console: Webhooks page, pick the endpoint,
   Redeliver per message. API, for every dead letter of one endpoint:

   ```bash
   KEY=tk_...   # the tenant's API key
   for id in $(curl -s -H "X-Api-Key: $KEY" localhost:8001/api/webhook-endpoints/$EP/dead-letters | jq '.[].id'); do
     curl -s -X POST -H "X-Api-Key: $KEY" -H "Idempotency-Key: redeliver-$id" \
       localhost:8001/api/webhook-endpoints/$EP/dead-letters/$id/redeliver
   done
   ```

   Redelivery resets the attempt budget; the next Beat sweep (every 10 s) picks it up.
3. Tenant endpoint permanently gone: disable it (`disabled_at`) so no new messages queue
   for it. Dead letters stay for the record.

## Prevent

Alert on `increase(tally_webhook_deliveries{state="dead"}[1h]) > 0`. Deliveries are
signed and carry `X-Tally-Delivery` (the message id) so tenants can dedupe redeliveries.
