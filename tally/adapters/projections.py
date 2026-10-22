"""account_balances projection: incremental apply and full replay.

Both paths write the same fold (sum of journal_lines.amount per account), so a
test can post random entries and assert the incremental table equals a rebuild.
"""

from collections.abc import Iterable

from django.db import connection

from tally.adapters import models

UPSERT = """
INSERT INTO account_balances (account_id, tenant_id, balance, as_of)
VALUES (%s, %s, %s, %s)
ON CONFLICT (account_id) DO UPDATE
   SET balance = account_balances.balance + EXCLUDED.balance,
       as_of = GREATEST(account_balances.as_of, EXCLUDED.as_of)
"""

REPLAY = """
INSERT INTO account_balances (account_id, tenant_id, balance, as_of)
SELECT l.account_id, l.tenant_id, sum(l.amount), max(e.posted_at)
  FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
 GROUP BY l.account_id, l.tenant_id
"""


def apply(entry: models.JournalEntry, lines: Iterable[models.JournalLine]) -> None:
    """Fold one posted entry into the projection. Call inside the posting transaction."""
    with connection.cursor() as cur:
        cur.executemany(
            UPSERT,
            [(line.account_id, entry.tenant_id, line.amount, entry.posted_at) for line in lines],
        )


def replay() -> int:
    """Rebuild the whole projection from the journal. Returns rows written."""
    with connection.cursor() as cur:
        cur.execute("TRUNCATE account_balances")
        cur.execute(REPLAY)
        return int(cur.rowcount)
