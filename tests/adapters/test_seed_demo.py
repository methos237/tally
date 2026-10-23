from io import StringIO

import pytest
from django.core.management import call_command

from tally.adapters.models import (
    Account,
    Invoice,
    JournalEntry,
    Plan,
    ReconciliationException,
    Statement,
    Subscription,
    Tenant,
)
from tests.conftest import fold_from_journal, projection


@pytest.mark.django_db(transaction=True)
def test_seed_demo_is_balanced_and_idempotent() -> None:
    call_command("seed_demo", stdout=StringIO())

    assert Tenant.objects.count() == 2
    assert Account.objects.count() == 24
    assert (Plan.objects.count(), Subscription.objects.count()) == (6, 25)
    invoices, paid = Invoice.objects.count(), Invoice.objects.filter(status="paid").count()
    assert invoices > 25 and 0 < paid < invoices
    assert Subscription.objects.filter(status="past_due").count() == 2
    assert JournalEntry.objects.count() == 2 * 401 + invoices + paid
    assert Statement.objects.count() == 2
    for statement in Statement.objects.all():
        reasons = sorted(statement.exceptions.values_list("reason", flat=True))
        assert reasons == ["amount_differs", "unmatched", "unmatched"]
        assert statement.reconciled_at is None
        assert statement.lines.filter(matched_entry__isnull=True).count() == 3
    assert ReconciliationException.objects.filter(resolved_at__isnull=False).count() == 0
    for tenant in Tenant.objects.all():
        assert sum(fold_from_journal(tenant).values()) == 0
    assert projection() == fold_from_journal()

    out = StringIO()
    call_command("seed_demo", stdout=out)
    assert "already exist" in out.getvalue()
    assert JournalEntry.objects.count() == 2 * 401 + invoices + paid
