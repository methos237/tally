"""account_balances projection: incremental apply and full replay.

Both statements are the same fold (sum of journal_lines.amount per account),
once scoped to one entry and once over the whole journal, so a test can post
random entries and assert the incremental table equals a rebuild.
"""

from django.db import connection, transaction

from tally.adapters import models

FOLD = """
INSERT INTO account_balances (account_id, tenant_id, balance, as_of)
SELECT l.account_id, l.tenant_id, sum(l.amount), max(e.posted_at)
  FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
 {where}
 GROUP BY l.account_id, l.tenant_id
"""

UPSERT = (
    FOLD.format(where="WHERE l.entry_id = %s")
    + """
ON CONFLICT (account_id) DO UPDATE
   SET balance = account_balances.balance + EXCLUDED.balance,
       as_of = GREATEST(account_balances.as_of, EXCLUDED.as_of)
"""
)

REPLAY = FOLD.format(where="")


def apply(entry: models.JournalEntry) -> None:
    """Fold one posted entry into the projection. Call inside the posting transaction."""
    with connection.cursor() as cur:
        cur.execute(UPSERT, [entry.id])


def replay() -> int:
    """Rebuild the whole projection from the journal. Returns rows written."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("TRUNCATE account_balances")
        cur.execute(REPLAY)
        return int(cur.rowcount)
