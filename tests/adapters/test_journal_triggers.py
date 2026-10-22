"""The database is the last line of defence: these tests bypass the domain
and the ORM validation entirely and write raw SQL."""

from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction

from tally.adapters.models import Account, JournalEntry, JournalLine, Tenant
from tests.domain.strategies import NOW


def raw_entry(tenant: Tenant, *lines: tuple[Account, str]) -> int:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO journal_entries"
            " (tenant_id, occurred_at, posted_at, source_type, source_id)"
            " VALUES (%s, %s, now(), 'raw', 'x') RETURNING id",
            [tenant.id, NOW],
        )
        entry_id: int = cur.fetchone()[0]
        for account, amount in lines:
            cur.execute(
                "INSERT INTO journal_lines (tenant_id, entry_id, account_id, amount, currency)"
                " VALUES (%s, %s, %s, %s, 'USD')",
                [tenant.id, entry_id, account.id, Decimal(amount)],
            )
    return entry_id


@pytest.mark.django_db(transaction=True)
def test_balanced_raw_insert_commits(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, rev = ledger
    with transaction.atomic():
        entry_id = raw_entry(tenant, (ar, "10"), (rev, "-10"))
    assert JournalLine.objects.filter(entry_id=entry_id).count() == 2


@pytest.mark.django_db(transaction=True)
def test_unbalanced_raw_insert_fails_at_commit(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, rev = ledger
    with pytest.raises(IntegrityError, match="unbalanced: lines in USD sum to 0.010000"):
        with transaction.atomic():
            raw_entry(tenant, (ar, "10.01"), (rev, "-10"))
            # Still inside the transaction: the deferred trigger has not fired yet.
            assert JournalLine.objects.count() == 2
    assert JournalEntry.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_entry_without_two_lines_fails_at_commit(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, _ = ledger
    with pytest.raises(IntegrityError, match="has 0 line"):
        with transaction.atomic():
            raw_entry(tenant)
    with pytest.raises(IntegrityError, match="has 1 line"):
        with transaction.atomic():
            raw_entry(tenant, (ar, "10"))


@pytest.mark.django_db(transaction=True)
def test_zero_line_is_rejected_immediately(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, rev = ledger
    with pytest.raises(IntegrityError, match="ck_line_amount_nonzero"):
        with transaction.atomic():
            raw_entry(tenant, (ar, "0"), (rev, "0"))


@pytest.mark.django_db(transaction=True)
def test_journal_is_append_only(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, rev = ledger
    with transaction.atomic():
        entry_id = raw_entry(tenant, (ar, "10"), (rev, "-10"))

    statements = [
        "UPDATE journal_lines SET amount = amount + 1 WHERE entry_id = %s",
        "DELETE FROM journal_lines WHERE entry_id = %s",
        "UPDATE journal_entries SET source_id = 'edited' WHERE id = %s",
        "DELETE FROM journal_entries WHERE id = %s",
    ]
    for sql in statements:
        with pytest.raises(IntegrityError, match="append-only"), connection.cursor() as cur:
            cur.execute(sql, [entry_id])

    # The ORM is caught too.
    with pytest.raises(IntegrityError, match="append-only"):
        JournalEntry.objects.filter(id=entry_id).update(source_id="edited")
    with pytest.raises(IntegrityError, match="append-only"):
        JournalLine.objects.filter(entry_id=entry_id).delete()

    assert JournalLine.objects.filter(entry_id=entry_id).count() == 2
