# Tally

Billing and ledger platform in Python: a double-entry ledger with a provable balancing invariant, idempotent posting under concurrency, subscription billing against Stripe test mode, webhooks in both directions, statement reconciliation, a nightly partner report orchestrated by Airflow, and a Vue 3 operations console.

A tenant posts financial events through an API. Every event becomes a balanced journal entry or is rejected with the reason. Subscriptions invoice on a schedule and collect through Stripe; the ledger, not Stripe, is the source of truth. Bank statements are imported and reconciled against the journal, and anything that does not match becomes an exception an operator resolves from the console. Every write is idempotent, every account mutation is locked in a fixed order, and the journal cannot be edited after the fact: corrections are reversing entries. Everything runs in Docker Compose with no cloud account and no card on file.

**Status.** Phase 0 (skeleton, compose, CI) is done. This README describes the target system; the phase list at the end records what has landed. Nothing described here should be read as finished until its phase is ticked.

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
make lint                     # ruff, mypy, import-linter
cd console && npm ci && npm run dev   # Vite on 5173, proxies /api and /health to 8001
```

## The ledger

Double entry. An `Account` has a type (asset, liability, equity, revenue, expense) and a currency. A `JournalEntry` has at least two `Line`s; within one entry the signed amounts sum to zero per currency, and no line is zero. That is the invariant, and it is enforced three times:

| Where | How | Why it is there |
|---|---|---|
| Domain | `post(entry)` raises `UnbalancedEntry`, `SingleLineEntry`, `ZeroLine` or `CurrencyMismatch` | The rule lives in one pure function with Hypothesis property tests generating thousands of balanced and unbalanced entries |
| Database | A deferred constraint trigger over `journal_lines` rejects the transaction at commit if any entry is unbalanced | Protects the journal from code paths that bypass the domain, including a raw SQL insert |
| API | 422 problem details naming the currency and the difference | The caller learns exactly what to fix |

**Append-only.** `journal_entries` and `journal_lines` carry a `BEFORE UPDATE OR DELETE` trigger that raises. A mistake is corrected by a reversing entry linked to the original. Balances are not stored on accounts; `account_balances` is a projection updated incrementally on every post and rebuilt from the journal by `manage.py replay_balances`. A test posts random entries and asserts the incremental projection equals a fresh fold over the journal. This is event sourcing in its plain form: the journal is the event log and the balance is derived. Tenants, plans and subscriptions are ordinary rows; the README says what is and is not event sourced so the word is not oversold.

**Money.** `Decimal` with a currency, stored as `numeric(18,6)`, displayed with the currency's exponent, rounded `ROUND_HALF_EVEN` at the one place rounding is allowed. Floats never touch money. Mixed-currency arithmetic raises.

## Posting API

```http
POST /api/entries
X-Api-Key: tk_live_...
Idempotency-Key: 7f3c1a2e-...
Content-Type: application/json

{"occurred_at": "2026-11-03T14:02:00Z", "source": {"type": "invoice", "id": "inv_1042"},
 "lines": [{"account": "1200", "amount": "149.00", "currency": "USD"},
           {"account": "4000", "amount": "-149.00", "currency": "USD"}]}
```

| Concern | Behaviour |
|---|---|
| Idempotency | Every write needs an `Idempotency-Key`. The key, a hash of the request and the response are stored in the same transaction as the business write. Same key and same body: the stored response is replayed with `Idempotent-Replayed: true`. Same key and a different body: 422. Keys expire after 24 hours |
| Locking | Posting locks the touched accounts with `SELECT ... FOR UPDATE` ordered by account id, so two entries touching the same accounts in opposite order cannot deadlock. A test fires 200 entries from 20 threads at two accounts and asserts the final balances |
| Consistency | Entries are read-your-writes for the posting client. The balance projection is eventually consistent with a bounded lag exposed as a metric. `docs/consistency.md` spells out which reads see what |
| Rate limiting | Token bucket per API key in Redis (one atomic Lua script), `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` headers, 429 problem details. Default 100 requests per minute per key, per-tenant override |
| Tenancy | Every table carries `tenant_id`; repositories always filter by it. Another tenant's entry is a 404, never a 403 |
| Errors | RFC 9457 problem details everywhere, one handler, typed problem classes |

## Billing and Stripe

A `Subscription` moves through `trialing`, `active`, `past_due`, `canceled`. Celery Beat runs `bill_due_subscriptions` every minute; each due subscription gets an `Invoice` (unique on subscription and period start, so a rerun cannot double-bill) and a journal entry debiting accounts receivable and crediting revenue. Collection goes through a Stripe PaymentIntent in test mode. A paid invoice posts cash against receivable. Stripe moves the test money; the ledger keeps the books.

**Inbound webhooks.** `POST /webhooks/stripe` verifies `Stripe-Signature` with the SDK, rejects timestamps older than five minutes, deduplicates on `event.id`, returns 200 immediately and hands the event to Celery. A tampered signature is rejected; the same event delivered twice is processed once.

**Outbound webhooks.** Tenants register endpoints with a secret. Events (`invoice.paid`, `entry.posted`, `reconciliation.exception`, `report.ready`) are written to an outbox table in the same transaction as the business write. A Celery task delivers them with `X-Tally-Signature: t=<timestamp>,v1=<hmac-sha256>` and retries at 1 minute, 5 minutes, 30 minutes, 2 hours and 12 hours before parking the delivery in a dead-letter list with the last response. The console shows dead letters and offers redelivery.

CI never calls Stripe. The SDK is wrapped by one gateway module; tests run against `stripe-mock` and recorded events. Tests marked `live` use the Stripe CLI against test mode and are skipped without a key.

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
- [ ] 1 Domain and journal: the balancing invariant
- [ ] 2 Posting API: idempotency, locking, rate limiting
- [ ] 3 Subscriptions, Stripe, webhooks in and out
- [ ] 4 Reconciliation and the nightly partner report
- [ ] 5 Vue 3 operations console
- [ ] 6 Observability, demo script, README polish
- [ ] 7 Stretch: Kotlin posting service, Temporal dunning workflow, multi-currency, Postgres row-level security

## Out of scope, on purpose

Real money movement (test mode only), currency conversion, tax, dunning emails, a public deployment, multi-tenant SaaS concerns such as self-serve signup and billing of the tenants themselves. Each would be a layer on top; none changes the ledger design shown here.

## License

Copyright (C) 2026 James Knox Polk

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE).
