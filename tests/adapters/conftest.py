from collections import defaultdict
from decimal import Decimal

import pytest

from tally.adapters.models import Account, AccountBalance, JournalLine, Tenant


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="acme")


@pytest.fixture
def ledger(tenant: Tenant) -> tuple[Tenant, Account, Account]:
    """One tenant with accounts receivable (1200) and revenue (4000), both USD."""
    ar = Account.objects.create(tenant=tenant, code="1200", name="AR", type="asset", currency="USD")
    rev = Account.objects.create(
        tenant=tenant, code="4000", name="Revenue", type="revenue", currency="USD"
    )
    return tenant, ar, rev


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
