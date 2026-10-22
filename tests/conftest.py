import os
from collections import defaultdict
from decimal import Decimal

import pytest
from hypothesis import settings

from tally.adapters.models import Account, AccountBalance, JournalLine, Tenant

settings.register_profile("ci", max_examples=1000, deadline=None)
settings.register_profile("dev", max_examples=100)
settings.load_profile("ci" if os.environ.get("CI") else "dev")

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
