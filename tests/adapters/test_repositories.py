from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tally.adapters.models import Account, JournalLine, Tenant
from tally.adapters.repositories import DjangoJournalRepository
from tally.application.journal import PostEntry, ReverseEntry
from tally.domain.journal import JournalEntry, Line, UnknownAccount
from tally.domain.money import Currency, Money

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def ledger() -> tuple[Tenant, Account, Account]:
    tenant = Tenant.objects.create(name="acme")
    ar = Account.objects.create(tenant=tenant, code="1200", name="AR", type="asset", currency="USD")
    rev = Account.objects.create(
        tenant=tenant, code="4000", name="Revenue", type="revenue", currency="USD"
    )
    return tenant, ar, rev


def entry(tenant: Tenant, *lines: tuple[Account, str]) -> JournalEntry:
    return JournalEntry(
        tenant.id,
        NOW,
        "invoice",
        "inv_1",
        tuple(Line(a.id, Money(Decimal(amt), Currency.USD)) for a, amt in lines),
    )


@pytest.mark.django_db(transaction=True)
def test_post_and_reverse_through_the_database(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, rev = ledger
    repo = DjangoJournalRepository()

    posted = PostEntry(repo)(entry(tenant, (ar, "149.00"), (rev, "-149.00")))
    assert posted.id is not None and posted.posted_at is not None
    assert repo.get(tenant.id, posted.id) == posted

    reversal = ReverseEntry(repo, clock=lambda: NOW)(tenant.id, posted.id)
    assert reversal.reverses_id == posted.id
    fetched = repo.get(tenant.id, posted.id)
    assert fetched is not None and fetched.reversed_by_id == reversal.id
    assert JournalLine.objects.filter(tenant=tenant).count() == 4
    assert sum(line.amount for line in JournalLine.objects.filter(tenant=tenant)) == 0


@pytest.mark.django_db
def test_other_tenants_accounts_are_invisible(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, _ = ledger
    other = Tenant.objects.create(name="other")
    foreign = Account.objects.create(
        tenant=other, code="4000", name="Revenue", type="revenue", currency="USD"
    )
    with pytest.raises(UnknownAccount):
        PostEntry(DjangoJournalRepository())(entry(tenant, (ar, "1"), (foreign, "-1")))


@pytest.mark.django_db
def test_get_filters_by_tenant(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, rev = ledger
    repo = DjangoJournalRepository()
    posted = PostEntry(repo)(entry(tenant, (ar, "1"), (rev, "-1")))
    assert posted.id is not None
    assert repo.get(tenant.id + 1, posted.id) is None
