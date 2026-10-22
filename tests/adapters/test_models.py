from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError

from tally.adapters.models import Account, JournalEntry, JournalLine, Tenant


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="acme")


@pytest.mark.django_db
def test_account_code_is_unique_per_tenant(tenant: Tenant) -> None:
    Account.objects.create(tenant=tenant, code="1200", name="AR", type="asset", currency="USD")
    other = Tenant.objects.create(name="other")
    Account.objects.create(tenant=other, code="1200", name="AR", type="asset", currency="USD")
    with pytest.raises(IntegrityError):
        Account.objects.create(tenant=tenant, code="1200", name="dup", type="asset", currency="USD")


@pytest.mark.django_db
def test_entry_with_lines_round_trips(tenant: Tenant) -> None:
    ar = Account.objects.create(tenant=tenant, code="1200", name="AR", type="asset", currency="USD")
    rev = Account.objects.create(
        tenant=tenant, code="4000", name="Revenue", type="revenue", currency="USD"
    )
    entry = JournalEntry.objects.create(
        tenant=tenant,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_type="invoice",
        source_id="inv_1",
    )
    JournalLine.objects.create(
        tenant=tenant, entry=entry, account=ar, amount=Decimal("149.00"), currency="USD"
    )
    JournalLine.objects.create(
        tenant=tenant, entry=entry, account=rev, amount=Decimal("-149.00"), currency="USD"
    )

    fetched = JournalEntry.objects.get(tenant=tenant, source_type="invoice", source_id="inv_1")
    assert sum(line.amount for line in fetched.lines.all()) == 0
    assert fetched.posted_at is not None
    assert fetched.reverses is None
