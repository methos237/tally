"""The database's balance check honours a declared conversion, as the last line of defence
behind the domain rule."""

import json

import pytest
from django.db import connection, transaction
from django.db.utils import IntegrityError

from tally.adapters.models import Account, Tenant

CONVERSION = json.dumps({"base": "USD", "rates": {"EUR": "1.08"}})


def raw_entry(
    tenant: Tenant, usd: Account, eur: Account, usd_amount: str, conversion: str | None
) -> None:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO journal_entries"
            " (tenant_id, occurred_at, posted_at, source_type, source_id, conversion)"
            " VALUES (%s, now(), now(), 'raw', '1', %s) RETURNING id",
            [tenant.id, conversion],
        )
        entry_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO journal_lines (tenant_id, entry_id, account_id, amount, currency) VALUES"
            " (%s, %s, %s, 100, 'EUR'), (%s, %s, %s, %s, 'USD')",
            [tenant.id, entry_id, eur.id, tenant.id, entry_id, usd.id, usd_amount],
        )


@pytest.fixture
def eur(tenant: Tenant) -> Account:
    return Account.objects.create(
        tenant=tenant, code="1210", name="EUR receivable", type="asset", currency="EUR"
    )


@pytest.fixture
def usd(tenant: Tenant) -> Account:
    return Account.objects.create(
        tenant=tenant, code="4000", name="Revenue", type="revenue", currency="USD"
    )


@pytest.mark.django_db(transaction=True)
def test_converted_entry_commits_when_the_base_total_is_zero(
    tenant: Tenant, usd: Account, eur: Account
) -> None:
    with transaction.atomic():
        raw_entry(tenant, usd, eur, "-108", CONVERSION)  # 100 EUR * 1.08


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("usd_amount", "conversion", "message"),
    [
        ("-107", CONVERSION, "unbalanced after conversion to USD: 1"),
        ("-108", json.dumps({"base": "USD", "rates": {}}), "null means a missing rate"),
        ("-108", None, "lines in EUR sum to 100"),
    ],
)
def test_trigger_rejects_at_commit(
    tenant: Tenant,
    usd: Account,
    eur: Account,
    usd_amount: str,
    conversion: str | None,
    message: str,
) -> None:
    with pytest.raises(IntegrityError, match=message), transaction.atomic():
        raw_entry(tenant, usd, eur, usd_amount, conversion)
