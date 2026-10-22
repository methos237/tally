"""Post random balanced entries through the use case, then prove the incremental
projection equals a fresh fold over the journal and equals a full replay."""

import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command

from tally.adapters.models import Account, AccountBalance, JournalLine, Tenant
from tally.adapters.repositories import DjangoJournalRepository
from tally.application.journal import PostEntry, ReverseEntry
from tally.domain.journal import JournalEntry, Line
from tally.domain.money import Currency, Money

START = datetime(2026, 1, 1, tzinfo=UTC)


def random_entry(
    rng: random.Random, tenant: Tenant, accounts: list[Account], n: int
) -> JournalEntry:
    amounts = [
        Decimal(rng.randint(-10_000_000, 10_000_000)) / 100 for _ in range(rng.randint(1, 5))
    ]
    amounts = [a for a in amounts if a != 0] or [Decimal("1")]
    amounts.append(-sum(amounts))
    if amounts[-1] == 0:
        amounts[-1:] = [Decimal("7"), Decimal("-7")]
    lines = tuple(Line(rng.choice(accounts).id, Money(a, Currency.USD)) for a in amounts)
    return JournalEntry(tenant.id, START + timedelta(hours=n), "random", str(n), lines)


def fold_from_journal(tenant: Tenant) -> dict[int, Decimal]:
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for line in JournalLine.objects.filter(tenant=tenant):
        totals[line.account_id] += line.amount
    return dict(totals)


def projection(tenant: Tenant) -> dict[int, Decimal]:
    return {b.account_id: b.balance for b in AccountBalance.objects.filter(tenant=tenant)}


@pytest.mark.django_db(transaction=True)
def test_incremental_projection_equals_fold_and_replay() -> None:
    rng = random.Random(20261022)
    tenant = Tenant.objects.create(name="acme")
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
        ReverseEntry(repo, clock=lambda: START)(tenant.id, e.id)

    expected = fold_from_journal(tenant)
    assert projection(tenant) == expected
    assert sum(expected.values()) == 0

    AccountBalance.objects.filter(tenant=tenant).update(balance=Decimal("999"))  # corrupt it
    call_command("replay_balances")
    assert projection(tenant) == expected


@pytest.mark.django_db(transaction=True)
def test_as_of_tracks_the_latest_posted_entry() -> None:
    tenant = Tenant.objects.create(name="acme")
    a = Account.objects.create(tenant=tenant, code="1", name="a", type="asset", currency="USD")
    b = Account.objects.create(tenant=tenant, code="2", name="b", type="asset", currency="USD")
    repo = DjangoJournalRepository()
    first = PostEntry(repo)(
        JournalEntry(
            tenant.id,
            START,
            "t",
            "1",
            (
                Line(a.id, Money(Decimal(1), Currency.USD)),
                Line(b.id, Money(Decimal(-1), Currency.USD)),
            ),
        )
    )
    second = PostEntry(repo)(
        JournalEntry(
            tenant.id,
            START,
            "t",
            "2",
            (
                Line(a.id, Money(Decimal(2), Currency.USD)),
                Line(b.id, Money(Decimal(-2), Currency.USD)),
            ),
        )
    )
    assert first.posted_at is not None and second.posted_at is not None
    assert AccountBalance.objects.get(account=a).as_of == max(first.posted_at, second.posted_at)
    assert AccountBalance.objects.get(account=a).balance == Decimal("3")
