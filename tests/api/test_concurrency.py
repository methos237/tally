"""200 entries from 20 threads against two accounts, half of them listing the
accounts in the opposite order: the end state must equal exactly what was posted.

Note what this does and does not prove. The balance upsert is one statement, so
Postgres keeps it correct on its own; the ordered SELECT ... FOR UPDATE exists so
that any read-modify-write inside a posting transaction (now or in later phases)
acquires account locks in one global order and cannot deadlock. The second test
pins that SQL shape."""

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tally.adapters.models import AccountBalance, JournalEntry, Tenant
from tally.adapters.repositories import DjangoJournalRepository
from tally.application.journal import PostEntry
from tests.api.conftest import client_for, in_threads
from tests.conftest import Ledger
from tests.domain.strategies import entry

THREADS, PER_THREAD = 20, 10


@pytest.mark.django_db(transaction=True)
def test_twenty_threads_on_two_accounts_leave_exact_balances(api_key: str, ledger: Ledger) -> None:
    tenant, ar, rev = ledger
    Tenant.objects.filter(id=tenant.id).update(rate_limit_per_minute=10_000)  # not under test here
    failures: list[object] = []

    def worker(n: int) -> None:
        client = client_for(api_key)
        lines = [("1200", str(n + 1)), ("4000", f"-{n + 1}")]
        if n % 2:
            lines.reverse()  # opposite lock order from the even threads
        for i in range(PER_THREAD):
            response = client.post_entry(*lines, source={"type": "load", "id": f"{n}-{i}"})
            if response.status_code != 201:
                failures.append(response.content)

    in_threads(THREADS, worker)

    assert failures == []
    assert JournalEntry.objects.count() == THREADS * PER_THREAD
    expected = Decimal(sum((n + 1) * PER_THREAD for n in range(THREADS)))
    assert AccountBalance.objects.get(account=ar).balance == expected
    assert AccountBalance.objects.get(account=rev).balance == -expected


@pytest.mark.django_db
def test_posting_locks_the_touched_accounts_in_id_order(ledger: Ledger) -> None:
    tenant, ar, rev = ledger
    high, low = max(ar.id, rev.id), min(ar.id, rev.id)
    with CaptureQueriesContext(connection) as queries:
        PostEntry(DjangoJournalRepository())(
            entry((high, "1"), (low, "-1"), tenant_id=tenant.id)  # listed high first on purpose
        )
    locks = [q["sql"] for q in queries.captured_queries if "FOR UPDATE" in q["sql"]]
    assert len(locks) == 1
    assert '"accounts"' in locks[0] and 'ORDER BY "accounts"."id" ASC FOR UPDATE' in locks[0]
    assert locks[0].index(str(low)) < locks[0].index(str(high)) or f"IN ({low}, {high})" in locks[0]
