import os
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import settings

from tally.adapters.models import (
    Account,
    AccountBalance,
    Customer,
    JournalLine,
    Plan,
    Subscription,
    Tenant,
)

settings.register_profile("ci", max_examples=1000, deadline=None)
settings.register_profile("dev", max_examples=100)
settings.load_profile("ci" if os.environ.get("CI") else "dev")

LIVE_KEY = os.environ.get("STRIPE_TEST_SECRET_KEY", "")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """`live` tests hit Stripe test mode and are skipped without a key."""
    skip = pytest.mark.skip(reason="STRIPE_TEST_SECRET_KEY not set")
    for item in items:
        if "live" in item.keywords and not LIVE_KEY:
            item.add_marker(skip)


Ledger = tuple[Tenant, Account, Account]


def chart_for(tenant: Tenant) -> tuple[Account, Account]:
    """The canonical two-account chart: accounts receivable 1200 and revenue 4000, USD."""
    ar = Account.objects.create(tenant=tenant, code="1200", name="AR", type="asset", currency="USD")
    rev = Account.objects.create(
        tenant=tenant, code="4000", name="Revenue", type="revenue", currency="USD"
    )
    return ar, rev


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="acme")


@pytest.fixture
def ledger(tenant: Tenant) -> Ledger:
    return (tenant, *chart_for(tenant))


def fold_from_journal(tenant: Tenant | None = None) -> dict[int, Decimal]:
    """The oracle: balance per account computed in Python straight from journal_lines."""
    lines = JournalLine.objects.filter(tenant=tenant) if tenant else JournalLine.objects.all()
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for line in lines:
        totals[line.account_id] += line.amount
    return dict(totals)


def projection(tenant: Tenant | None = None) -> dict[int, Decimal]:
    rows = AccountBalance.objects.filter(tenant=tenant) if tenant else AccountBalance.objects.all()
    return {b.account_id: b.balance for b in rows}


@pytest.fixture
def subscription(tenant: Tenant) -> Subscription:
    """An active monthly subscription that has never been billed, with the three billing
    accounts (1000 cash, 1200 receivable, 4000 revenue) on the tenant."""
    for code, name, type_ in [
        ("1000", "Cash", "asset"),
        ("1200", "Accounts receivable", "asset"),
        ("4000", "Subscription revenue", "revenue"),
    ]:
        Account.objects.create(tenant=tenant, code=code, name=name, type=type_, currency="USD")
    plan = Plan.objects.create(
        tenant=tenant,
        code="pro",
        name="Pro",
        amount=Decimal("49.00"),
        currency="USD",
        interval="month",
    )
    customer = Customer.objects.create(tenant=tenant, name="Wile E.", email="wile@acme.test")
    return Subscription.objects.create(
        tenant=tenant, customer=customer, plan=plan, started_at=datetime(2026, 1, 31, tzinfo=UTC)
    )
