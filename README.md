# Tally

Billing and ledger platform in Python: a double-entry ledger with a provable balancing invariant, idempotent posting under concurrency, subscription billing against Stripe test mode, webhooks in both directions, statement reconciliation, a nightly partner report orchestrated by Airflow, and a Vue 3 operations console.

A tenant posts financial events through an API. Every event becomes a balanced journal entry or is rejected with the reason. Subscriptions invoice on a schedule and collect through Stripe; the ledger, not Stripe, is the source of truth. Bank statements are imported and reconciled against the journal, and anything that does not match becomes an exception an operator resolves from the console. Every write is idempotent, every account mutation is locked in a fixed order, and the journal cannot be edited after the fact: corrections are reversing entries. Everything runs in Docker Compose with no cloud account and no card on file.

**Status.** Phases 0 (skeleton, compose, CI), 1 (domain and journal) and 2 (posting API) are done. This README describes the target system; the phase list at the end records what has landed. Nothing described here should be read as finished until its phase is ticked.

## Ten-minute tour

The intended path once Phase 6 lands:

```bash
docker compose up -d --wait                  # Postgres 5435, Redis 6380, S3 (RustFS) 9000, stripe-mock 12111, Jaeger 16687
make dev                                     # migrations, seed, Django 8001, Celery worker + Beat
scripts/post-entry.sh                        # one balanced entry with an Idempotency-Key, then the same key again
scripts/post-entry.sh --unbalanced           # 422 problem details naming the currency and the difference
scripts/stripe-listen.sh                     # forward Stripe test-mode webhooks; triggers payment_intent.succeeded
curl -s localhost:8001/api/accounts/1200/balance | jq   # cash moved, accounts receivable cleared
docker compose --profile batch up -d         # Airflow 8081
airflow dags trigger partner_daily_report    # CSV per tenant lands in S3 bucket reports/
open http://localhost:5173                   # console: journal, balances, subscriptions, dead letters, reconciliation
```

## Architecture

```
Tenant systems ──► POST /entries, /subscriptions, /statements   (X-Api-Key, Idempotency-Key)
                    │  rate limiter (Redis token bucket)         problem+json on every error
                    ▼
            Django + DRF  (tally/api)
                    │
            application use cases ── ports ──► adapters (Django ORM, Stripe gateway, webhook sender)
                    │
            domain (pure Python: Money, Account, JournalEntry, posting and matching rules)
                    │
            Postgres 17: journal_entries, journal_lines (append-only, balancing trigger),
                         account_balances (projection), idempotency_records, outbox,
                         subscriptions, invoices, statements, reconciliation_exceptions
                    ▲
   Celery workers ──┤  bill_due_subscriptions (Beat), deliver_webhooks (outbox), expire_idempotency,
                    │  process_stripe_event
   Stripe test mode ──► POST /webhooks/stripe (signature verified, deduplicated)
   Airflow ─────────── partner_daily_report ──► S3 bucket reports/ (RustFS) ──► report.ready webhook

Console (Vue 3, Vite, Tailwind, Pinia, Storybook, Cypress) ──► session-authenticated JSON endpoints
```

| Directory | Role | Port |
|---|---|---|
| `tally/domain` | Pure Python: money, accounts, journal entries, posting invariant, matching rules. Imports nothing from Django | – |
| `tally/application` | Use cases (`PostEntry`, `ReverseEntry`, `BillSubscription`, `ReconcileStatement`) over repository ports | – |
| `tally/adapters` | Django models and repositories, Stripe gateway, webhook sender, Redis rate limiter | – |
| `tally/api` | Django REST Framework views, serializers, OpenAPI | 8001 |
| `console/` | Vue 3 operations console | 5173 |
| `airflow/` | `partner_daily_report` DAG | 8081 |

## Stack

Python 3.13 · Django 6.0 · Django REST Framework 3.18 · Celery 5.6 + Redis 7 · PostgreSQL 17 · Stripe (test mode) · Airflow · RustFS (S3 API) · Hypothesis · pytest · import-linter · Vue 3.5 · Vite 8 · TypeScript 6 · Tailwind CSS 4 · Pinia 4 · Storybook · Cypress · OpenTelemetry · GitHub Actions

Prerequisites: Docker with Compose v2, uv 0.12+, Node 26, Stripe CLI, a Stripe account in test mode (free, no card). Copy `.env.example` to `.env`; the defaults work against compose without a Stripe key.

```bash
docker compose up -d --wait   # Postgres, Redis, stripe-mock, RustFS with the reports bucket
make dev                      # migrate, Django on 8001, Celery worker and Beat
make test                     # pytest against the compose Postgres
uv run python manage.py seed_demo       # two tenants, 90 days of entries
uv run python manage.py replay_balances # rebuild the balance projection
make lint                     # ruff, mypy, import-linter
cd console && npm ci && npm run dev   # Vite on 5173, proxies /api and /health to 8001
```

## The ledger

Double entry means every event is recorded twice: once where value came from and once where it went. An invoice for 149.00 debits accounts receivable (an asset grows) and credits revenue (income is recognized). The payment that settles it debits cash and credits receivable. Each side is a `Line` with a signed amount; debits are positive, credits negative, and the lines of one `JournalEntry` always sum to zero. Because every entry is zero-sum, the sum of all balances across the chart is zero at every instant, and any balance can be recomputed from the journal alone.

An `Account` has a type (asset, liability, equity, revenue, expense), a code, a currency and a tenant. A `JournalEntry` has at least two `Line`s; within one entry the amounts sum to zero per currency, no line is zero, and every line is in its account's currency. That is the invariant, and it is enforced three times:

| Where | How | Why it is there |
|---|---|---|
| Domain | `post(entry, accounts)` in `tally/domain/journal.py` checks line count, zero lines, account ownership and currency, then balance, in that order, and raises `SingleLineEntry`, `ZeroLine`, `AmountOutOfRange`, `UnknownAccount`, `CurrencyMismatch` or `UnbalancedEntry` carrying the currency and the difference | The rule is one pure function. Hypothesis generates balanced entries and balanced entries nudged by a known delta; the property is that every balanced entry posts and every nudged one is rejected with exactly that delta. CI runs 1,000 examples |
| Database | A `CHECK (amount <> 0)` on `journal_lines`, and a deferred constraint trigger on both `journal_entries` and `journal_lines` that, at commit, rejects any entry with fewer than two lines or a nonzero sum per currency | Protects the journal from code that bypasses the domain. The tests write raw SQL and prove an unbalanced insert fails at `COMMIT`, after the rows were visible inside the transaction |
| API | 422 problem details naming the currency and the difference | The caller learns exactly what to fix |

**Append-only.** `journal_entries` and `journal_lines` carry `BEFORE UPDATE OR DELETE` triggers that raise, so neither the ORM nor a `psql` session can edit history. A mistake is corrected by a reversing entry: `ReverseEntry` negates every line of the original and links the new entry to it; the link is a unique column, so the database itself refuses a second reversal and the repository reports it as `AlreadyReversed`. An auditor reads the original, the reversal and the correction, not a row that quietly changed.

**Projection.** Balances are not stored on accounts. `account_balances(account_id, balance, as_of)` is a projection: every post upserts the touched accounts inside the same transaction, and `manage.py replay_balances` truncates the table and rebuilds it with one `GROUP BY` over the journal. A test posts random entries, reverses some, corrupts the projection, and asserts the rebuild equals both the incremental table and a fresh fold in Python.

**What "event sourced" means here.** The journal is the event log and the balance is derived state that can be thrown away and recomputed. That is event sourcing in its plain form, and it applies to the ledger only. Tenants, accounts, plans and subscriptions are ordinary rows that are updated in place. The README says so to avoid overselling the word.

**Money.** `Money(amount: Decimal, currency)` quantizes to six decimal places with `ROUND_HALF_EVEN` on construction, the one place rounding happens; display rounds to the currency's exponent (2 for USD, EUR, GBP; 0 for JPY). Floats are refused with `TypeError`, non-finite values with `ValueError`. Lines must fit `numeric(18,6)`, so `post()` rejects any line at or beyond 10^12 with `AmountOutOfRange` rather than letting the database truncate it. Mixed-currency arithmetic raises `CurrencyMismatch`.

**Layers.** `tally/domain` imports nothing from Django; `import-linter` fails CI if it does. `tally/application` holds `PostEntry` and `ReverseEntry` over a `JournalRepository` Protocol and is tested against an in-memory fake. `tally/adapters` implements the port with the Django ORM, owns the migrations and triggers, and ships `seed_demo`: two tenants, a 12-account chart each, and 400 deterministic entries over 90 days.

## Posting API

Every request carries `X-Api-Key`; every write also carries `Idempotency-Key`. Keys are issued per tenant and shown once:

```bash
uv run python manage.py seed_demo                      # two tenants, chart of accounts, 90 days of entries
uv run python manage.py issue_api_key --tenant "Acme Corp" --name laptop   # prints tk_...
```

```http
POST /api/entries
X-Api-Key: tk_...
Idempotency-Key: 7f3c1a2e-...
Content-Type: application/json

{"occurred_at": "2026-11-03T14:02:00Z", "source": {"type": "invoice", "id": "inv_1042"},
 "lines": [{"account": "1200", "amount": "149.00", "currency": "USD"},
           {"account": "4000", "amount": "-149.00", "currency": "USD"}]}
```

```bash
KEY=$(uv run python manage.py issue_api_key --tenant "Acme Corp")
curl -s localhost:8001/api/entries -H "X-Api-Key: $KEY" -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' \
  -d '{"occurred_at":"2026-11-03T14:02:00Z","source":{"type":"invoice","id":"inv_1042"},
       "lines":[{"account":"1200","amount":"149.00","currency":"USD"},
                {"account":"4000","amount":"-149.00","currency":"USD"}]}' | jq
curl -s localhost:8001/api/accounts/1200/balance -H "X-Api-Key: $KEY" | jq
```

| Endpoint | Behaviour |
|---|---|
| `POST /api/entries` | Validates shape (400), resolves account codes for the tenant, runs the domain posting rule (422 with the typed reason), posts in one transaction, returns 201 with the stored entry |
| `GET /api/entries` | Cursor-paginated, newest first; filters `source_type`, `source_id`, `account` |
| `GET /api/entries/{id}` | The entry with its lines, `reverses` and `reversed_by` links |
| `POST /api/entries/{id}/reverse` | Posts the negated entry linked to the original; a second reversal is 409 |
| `GET /api/accounts` | The tenant's chart of accounts |
| `GET /api/accounts/{code}/balance?as_of=` | Projection balance, or an exact fold over the journal up to `as_of` |
| `GET /api/me` | Confirms a key and names the tenant |
| `GET /openapi.json`, `GET /docs` | OpenAPI 3 document and Redoc, no key required |

Amounts are strings with six decimal places on the wire; a JSON number is rejected so a float can never reach the ledger.

| Concern | Behaviour |
|---|---|
| Idempotency | Every write needs an `Idempotency-Key` (400 without one). The key, a SHA-256 of method, path and body, and the response are stored in `idempotency_records` in the same transaction as the business write. Same key and same body: the stored response is replayed with `Idempotent-Replayed: true`. Same key and a different body: 422. A failed attempt rolls back with its record, so a corrected retry is accepted. Concurrent requests with one key block on the unique index and replay. Keys expire after 24 hours (Celery Beat, hourly) |
| Locking | Posting locks the touched accounts with `SELECT ... FOR UPDATE` ordered by account id, so two entries naming the same accounts in opposite order cannot deadlock. 20 threads post 200 entries at two accounts in alternating order and the final balances are exact |
| Consistency | Entries are read-your-writes; replays are byte-identical; the balance projection is updated in the posting transaction today and its lag is defined so Phase 6 can measure it. [`docs/consistency.md`](docs/consistency.md) spells out which reads see what |
| Rate limiting | Token bucket per API key in Redis, one atomic Lua script, default 100 requests per minute with a per-tenant override. Every authenticated response carries `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset`; exhaustion is a 429 problem with `Retry-After` |
| Tenancy | Keys resolve to a tenant; every query filters by it. Another tenant's entry or account is a 404, never a 403 |
| Authentication | `X-Api-Key` checked against an Argon2 hash; only an 8-character prefix is stored in the clear for lookup. Missing, unknown or revoked keys are 401 with `WWW-Authenticate: X-Api-Key` |
| Errors | RFC 9457 problem details everywhere (`application/problem+json`), one handler. Domain rejections are `type: .../posting/UnbalancedEntry` and friends; an unbalanced entry names the currency and the difference |

## Billing and Stripe

Tally owns the subscription engine and the books; Stripe only collects. Stripe's own Billing product is deliberately not used: the point of this repo is the engine.

```
                 payment_succeeded
        ┌──────────────────────────────┐
        ▼                              │
   ┌─────────┐  payment_failed   ┌──────────┐
   │ active  │ ────────────────► │ past_due │
   └─────────┘                   └──────────┘
        │ cancel                      │ cancel
        ▼                              ▼
   ┌──────────────────────────────────────┐
   │              canceled                 │   (terminal)
   └──────────────────────────────────────┘
```

The state machine is a transition table in `tally/domain/billing.py`; a Hypothesis test walks every `(status, event)` pair and checks it is either in the table or rejected. Subscriptions bill in advance: `billed_through` null or past means due. Celery Beat runs `bill_due_subscriptions` every minute; each due subscription gets an `Invoice` (unique on subscription and period start, so an overlapping run cannot double-bill) and a journal entry debiting accounts receivable 1200 and crediting revenue 4000. Periods clamp to month end, so the 31st bills on the 28th and never skips a month.

**What Stripe does, what the ledger does.** `collect_invoice` creates one Stripe `Customer` per Tally customer and one `PaymentIntent` per invoice, confirmed server-side with the `4242` test card, off session, redirects disabled, with `idempotency_key=tally-invoice-{id}` so a retried task cannot charge twice. The intent id is stored on the invoice; a webhook resolves to an invoice by that id, never by metadata. A paid invoice posts cash 1000 against receivable 1200 and reactivates a past-due subscription; a failed payment moves the subscription to `past_due`. One module, `tally/adapters/stripe_gateway.py`, builds the `StripeClient` from settings and is the only place that imports the SDK.

**Inbound webhooks.** `POST /webhooks/stripe` verifies `Stripe-Signature` with the SDK (HMAC-SHA256, timestamps older than five minutes rejected), inserts `event.id` into `stripe_events`, returns 200 and hands the row to `process_stripe_event`. A tampered signature is a 400 and nothing is stored; the same event delivered twice is acknowledged and processed once; an intent Tally never created (a `stripe trigger` fixture, say) is acknowledged and books nothing.

**Outbound webhooks.** Tenants register endpoints with `POST /api/webhook-endpoints` and receive the secret once. Events (`invoice.issued`, `invoice.paid`, `subscription.past_due`, `subscription.active`) are written to `webhook_outbox` in the same transaction as the business write, so they commit or roll back with it. `deliver_due_webhooks` sweeps every ten seconds and posts the envelope `{"id", "type", "created_at", "data"}` with:

```
X-Tally-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>
X-Tally-Event: invoice.paid
X-Tally-Delivery: <message id>
```

To verify: split the header, recompute the digest over `t` + `.` + the raw body with your secret, compare with `hmac.compare_digest`, and reject if `t` is more than 300 seconds from now. The test suite verifies deliveries with exactly this recipe (`tally.adapters.outbox.verify`). Retries follow 1 minute, 5 minutes, 30 minutes, 2 hours; the fifth failure parks the message in the dead-letter list at `GET /api/webhook-endpoints/{id}/dead-letters` with the last status and error, and `POST .../dead-letters/{id}/redeliver` puts it back in the queue.

**Local loop.** `stripe login` once, then `scripts/stripe-listen.sh` forwards sandbox events to `localhost:8001/webhooks/stripe` and prints the `whsec_` for `STRIPE_WEBHOOK_SECRET`. CI never calls Stripe: tests run against `stripe-mock` and hand-built events in the recorded shape. Tests marked `live` pay a real test-mode invoice with the `4242` card and are skipped without `STRIPE_TEST_SECRET_KEY` (use a restricted key with Customers and PaymentIntents write).

## Reconciliation and the nightly report

A `Statement` is imported from CSV (bank or processor layout). Matching rules in the domain run in order: exact reference and amount, then amount within a three-day window, then nothing. Every line ends matched or excepted exactly once (a Hypothesis property). Exceptions carry a reason and are resolved from the console by posting an adjusting entry or recording an explanation. A statement is reconciled when no line is left unexplained.

`partner_daily_report` is an Airflow DAG with a settlement sensor, a report task and an outbox task. The report itself is `manage.py partner_report --date --tenant`, which writes a CSV per tenant to an S3 bucket (RustFS in compose), so the job is testable without Airflow and Airflow contributes what it is good at: scheduling, retries, SLAs, backfill.

## Console

Vue 3 with `<script setup>` and TypeScript, Vite, Pinia, Tailwind CSS, a typed client generated from the API's OpenAPI document. The component library (`TallyTable`, `MoneyCell`, `StatusBadge`, `JournalLines`, `ExceptionCard`, `Pagination`) is documented in Storybook and published to GitHub Pages. Pages: dashboard, journal browser, account balances, subscriptions and invoices, webhook endpoints with dead letters, reconciliation workbench, reports. Cypress drives the main flows against the compose stack with `cypress-axe` checking WCAG 2.2 AA on every page.

## Design decisions

- **Domain package that imports nothing from Django.** `tally/domain` holds the rules; `import-linter` fails CI if it imports Django, DRF, Celery or Stripe. The ORM, the payment processor and the queue are adapters. That is hexagonal architecture named plainly, and it is what makes the invariant testable in microseconds with Hypothesis.
- **Append-only journal with reversing entries, not editable rows.** An auditor can replay the ledger. The cost is a projection table and a rebuild command, both small.
- **Trigger in the database as the last line.** Application code is the first line and the tested one; the trigger exists for the day something bypasses it.
- **Idempotency record in the same transaction as the write.** Writing it before or after leaves a window where a retry either loses the response or double-posts.
- **Lock ordering over retries.** Ordering account locks by id costs one `sort`; retrying deadlocks costs a retry loop in every caller.
- **Ledger as the source of truth, Stripe as the processor.** Stripe knows about charges. Only the ledger knows that a charge settled an invoice that recognized revenue.
- **Outbox for outbound webhooks.** A webhook sent from inside a request either fires for a transaction that rolls back or is lost when the process dies after commit. The outbox closes both.
- **Airflow for one DAG.** Two or three tasks is enough to use it truthfully, and the job stays a management command so nobody needs Airflow to test it.
- **Vue, not React.** React is already proven elsewhere; the console is here to prove Vue 3, Pinia, Storybook and Cypress with the same care.
- **Zero cost.** Compose for everything, Stripe test mode, RustFS instead of S3. No cloud account is created for this project.
- **RustFS, not MinIO.** MinIO withdrew its free container images in September 2026. RustFS speaks the same S3 API on the same ports, so `boto3` and the report job do not know the difference.

## Tests

Planned, enforced in CI from Phase 0:

| Level | Where | What |
|---|---|---|
| Property (Hypothesis) | domain | every balanced entry posts, every unbalanced one is rejected with the right error; matching assigns every statement line exactly once |
| Unit | domain, application | money arithmetic, state machine transitions, use cases with fake repositories |
| Database | adapters | append-only trigger, balancing trigger at commit, projection equals replay |
| Concurrency | api | 20 threads on two accounts, idempotent replay under concurrent same-key requests |
| Integration | api, Celery | Stripe webhooks with recorded events and tampered signatures against `stripe-mock`, outbound delivery and dead-lettering against a local receiver |
| DAG | airflow | import and structure tests, one `airflow dags test` run |
| End to end | console | Cypress flows, `cypress-axe`, Lighthouse budgets |

## Phases

Each phase is a branch merged by pull request and tracked as a GitHub issue.

- [x] 0 Skeleton, compose, CI
- [x] 1 Domain and journal: the balancing invariant
- [x] 2 Posting API: idempotency, locking, rate limiting
- [x] 3 Subscriptions, Stripe, webhooks in and out
- [ ] 4 Reconciliation and the nightly partner report
- [ ] 5 Vue 3 operations console
- [ ] 6 Observability, demo script, README polish
- [ ] 7 Stretch: Kotlin posting service, Temporal dunning workflow, multi-currency, Postgres row-level security

## Out of scope, on purpose

Real money movement (test mode only), currency conversion, tax, dunning emails, a public deployment, multi-tenant SaaS concerns such as self-serve signup and billing of the tenants themselves. Each would be a layer on top; none changes the ledger design shown here.

## License

Copyright (C) 2026 James Knox Polk

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE).
