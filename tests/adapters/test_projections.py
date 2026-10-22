"""Post random balanced entries through the use case, then prove the incremental
projection equals a fresh fold over the journal and equals a full replay."""

import random
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command

from tally.adapters.models import Account, AccountBalance, Tenant
from tally.adapters.repositories import DjangoJournalRepository
from tally.application.journal import PostEntry, ReverseEntry
from tally.domain.journal import JournalEntry, Line
from tally.domain.money import Currency, Money
from tests.adapters.conftest import fold_from_journal, projection
from tests.domain.strategies import NOW, entry


def random_entry(
    rng: random.Random, tenant: Tenant, accounts: list[Account], n: int
) -> JournalEntry:
    amounts = [
        Decimal(rng.randint(-10_000_000, 10_000_000)) / 100 for _ in range(rng.randint(1, 5))
    ]
    amounts = [a for a in amounts if a != 0] or [Decimal("1")]
    amounts.append(-sum(amounts, Decimal(0)))
    if amounts[-1] == 0:
        amounts[-1:] = [Decimal("7"), Decimal("-7")]
    lines = tuple(Line(rng.choice(accounts).id, Money(a, Currency.USD)) for a in amounts)
    return JournalEntry(tenant.id, NOW + timedelta(hours=n), "random", str(n), lines)


@pytest.mark.django_db(transaction=True)
def test_incremental_projection_equals_fold_and_replay(tenant: Tenant) -> None:
    rng = random.Random(20261022)
    accounts = [
        Account.objects.create(
            tenant=tenant, code=str(1000 + i), name=f"A{i}", type="asset", currency="USD"
        )
        for i in range(6)
    ]
    repo = DjangoJournalRepository()
    posted = [PostEntry(repo)(random_entry(rng, tenant, accounts, n)) for n in range(60)]
    for e in rng.sample(posted, 10):
        assert e.id is not None
        ReverseEntry(repo)(tenant.id, e.id, occurred_at=NOW)

    expected = fold_from_journal(tenant)
    assert projection(tenant) == expected
    assert sum(expected.values()) == 0

    AccountBalance.objects.filter(tenant=tenant).update(balance=Decimal("999"))  # corrupt it
    call_command("replay_balances")
    assert projection(tenant) == expected


@pytest.mark.django_db(transaction=True)
def test_as_of_tracks_the_latest_posted_entry(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, a, b = ledger
    repo = DjangoJournalRepository()
    first = PostEntry(repo)(entry((a.id, "1"), (b.id, "-1"), tenant_id=tenant.id))
    second = PostEntry(repo)(entry((a.id, "2"), (b.id, "-2"), tenant_id=tenant.id))
    assert first.posted_at is not None and second.posted_at is not None
    assert AccountBalance.objects.get(account=a).as_of == max(first.posted_at, second.posted_at)
    assert AccountBalance.objects.get(account=a).balance == Decimal("3")
