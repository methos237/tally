# Consistency model

What a caller can rely on after each kind of request, and where the system is
deliberately eventually consistent.

## Strongly consistent

| Read | Guarantee | Why |
|---|---|---|
| `POST /api/entries` response | The entry in the response is committed. A later `GET /api/entries/{id}` from any client returns it | The response is built after the transaction commits |
| `GET /api/entries`, `GET /api/entries/{id}` | Read-committed snapshot of the journal | Append-only table, single Postgres primary |
| Replay of an `Idempotency-Key` | Byte-for-byte the stored response of the first successful attempt | The record is written in the same transaction as the business write, so it either exists with its response or not at all |
| `GET /api/accounts/{code}/balance?as_of=` | Exact fold over the journal up to `as_of` | Computed from `journal_lines` on request, not from the projection |
| Database invariants | No committed entry is unbalanced, has fewer than two lines, or has a zero line. No committed entry or line is ever updated or deleted | Deferred constraint triggers at commit and `BEFORE UPDATE OR DELETE` triggers |

## Eventually consistent

| Read | Guarantee | Lag |
|---|---|---|
| `GET /api/accounts/{code}/balance` without `as_of` | The `account_balances` projection. Updated inside the posting transaction, so in the current design it is read-your-writes for the poster and visible to everyone at commit | Zero today. The design keeps the projection separable: `replay_balances` rebuilds it from the journal, and `as_of` on the balance row records the `posted_at` of the last entry folded in |

Projection lag is defined as `max(journal_entries.posted_at) - account_balances.as_of` per account.
Today it is always zero because the fold runs in the posting transaction; Phase 6 exposes it as
a metric so that moving the fold out of the transaction (for throughput) is an observable change,
not a silent one.

## Concurrency

- Posting locks the touched accounts with `SELECT ... FOR UPDATE` ordered by account id, inside the
  posting transaction. Every transaction takes locks in one global order, so two postings that
  name the same accounts in opposite order cannot deadlock. The 20-thread test in
  `tests/api/test_concurrency.py` posts 200 entries at two accounts in alternating order and
  asserts the exact final balances.
- The projection upsert is one `INSERT ... ON CONFLICT DO UPDATE` statement per entry, which
  Postgres applies atomically per row. The account locks are therefore not what keeps the
  projection correct today; they serialize the insert and the upsert per account. A read that
  must be protected by the lock (a balance check before posting, Phase 3) has to run after the
  repository opens it, inside the same transaction.
- Concurrent requests with the same `Idempotency-Key` block on the unique index of
  `idempotency_records` until the first transaction commits; the rest replay its response.
  Eight threads with one key produce one entry.

## Isolation level

Postgres default, `READ COMMITTED`. Nothing in the API depends on repeatable reads: writes are
guarded by row locks and unique constraints, and list reads are paginated by cursor over an
append-only table, so a page never contains an entry that later disappears.
