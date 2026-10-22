from collections import defaultdict
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from tally.adapters.models import Account, AccountBalance, JournalEntry, JournalLine, Tenant


@pytest.mark.django_db(transaction=True)
def test_seed_demo_is_deterministic_balanced_and_idempotent() -> None:
    call_command("seed_demo", stdout=StringIO())

    assert Tenant.objects.count() == 2
    assert Account.objects.count() == 24
    assert JournalEntry.objects.count() == 2 * 401
    for tenant in Tenant.objects.all():
        assert sum(line.amount for line in JournalLine.objects.filter(tenant=tenant)) == 0

    fold: dict[int, Decimal] = defaultdict(Decimal)
    for line in JournalLine.objects.all():
        fold[line.account_id] += line.amount
    assert {b.account_id: b.balance for b in AccountBalance.objects.all()} == dict(fold)

    # Same seed, same journal: the first invoice is always the same amount.
    first = JournalEntry.objects.filter(source_type="invoice").order_by("id").first()
    assert first is not None
    assert first.lines.order_by("id").first().amount == Decimal("570.27")  # type: ignore[union-attr]

    out = StringIO()
    call_command("seed_demo", stdout=out)
    assert "already exist" in out.getvalue()
    assert JournalEntry.objects.count() == 2 * 401
