# Projection lag

## Symptom

`tally_projection_lag_seconds` is above zero, or `GET /api/accounts/{code}/balance`
disagrees with summing the journal for that account.

## What the number means

`account_balances` is a projection folded from `journal_lines` inside the posting
transaction. Lag is `max(journal_entries.posted_at) - account_balances.as_of` across accounts
(`docs/consistency.md`). In the current design it is zero by construction; any positive
value means the fold was bypassed or the table was changed outside the posting path.

## Confirm

```bash
curl -s -H "X-Internal-Token: $INTERNAL_TOKEN" localhost:8001/internal/metrics | grep tally_projection_lag
rtk psql postgresql://tally:tally@localhost:5435/tally -c "
  SELECT a.code, b.balance, b.as_of, s.total, s.last_posted
  FROM account_balances b JOIN accounts a ON a.id = b.account_id
  JOIN LATERAL (SELECT sum(l.amount) total, max(e.posted_at) last_posted
                FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
                WHERE l.account_id = b.account_id) s ON true
  WHERE s.total <> b.balance OR s.last_posted > b.as_of"
```

Rows returned are the accounts whose projection is wrong or stale.

## Fix

The journal is the source of truth; the projection is disposable.

```bash
uv run python manage.py replay_balances
```

Rebuilds every balance from the journal in one statement. Safe to run while posting
continues (the upsert takes the greater `as_of`). Then rescrape `/internal/metrics`; lag returns to 0.

## Find the cause

- A deploy that moved the fold out of the posting transaction: expected lag, bounded by
  the worker's catch-up; document the new bound in `docs/consistency.md`.
- Manual SQL against `account_balances`: the only legitimate writer is
  `tally/adapters/projections.py`.
- Entries inserted outside `PostEntry` (direct SQL bypassing the use case): the append-only
  and balance triggers still hold, but the projection never heard about them. Replay fixes
  the numbers; fix the writer.
