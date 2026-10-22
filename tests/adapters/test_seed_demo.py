from io import StringIO

import pytest
from django.core.management import call_command

from tally.adapters.models import Account, JournalEntry, Tenant
from tests.conftest import fold_from_journal, projection


@pytest.mark.django_db(transaction=True)
def test_seed_demo_is_balanced_and_idempotent() -> None:
    call_command("seed_demo", stdout=StringIO())

    assert Tenant.objects.count() == 2
    assert Account.objects.count() == 24
    assert JournalEntry.objects.count() == 2 * 401
    for tenant in Tenant.objects.all():
        assert sum(fold_from_journal(tenant).values()) == 0
    assert projection() == fold_from_journal()

    out = StringIO()
    call_command("seed_demo", stdout=out)
    assert "already exist" in out.getvalue()
    assert JournalEntry.objects.count() == 2 * 401
