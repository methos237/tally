"""Row-level security: bound to one tenant, the connection cannot read or write another
tenant's rows even through a query that forgets to filter; unbound, it sees everything."""

from collections.abc import Iterator

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import Client

from tally.adapters import rls
from tally.adapters.models import Account, ApiKey, JournalEntry, Tenant
from tests.api.conftest import client_for
from tests.conftest import chart_for


@pytest.fixture
def two_tenants(tenant: Tenant, other_tenant: Tenant) -> tuple[Tenant, Tenant]:
    chart_for(tenant)
    chart_for(other_tenant)
    client_for(ApiKey.issue(tenant, "a")).post_entry(("1200", "5.000000"), ("4000", "-5.000000"))
    client_for(ApiKey.issue(other_tenant, "b")).post_entry(
        ("1200", "7.000000"), ("4000", "-7.000000")
    )
    return tenant, other_tenant


@pytest.fixture(autouse=True)
def unbound() -> Iterator[None]:
    rls.unbind()
    yield
    rls.unbind()


@pytest.mark.django_db
def test_every_tenant_table_has_the_policy() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_policies WHERE policyname = 'tenant_wall' ORDER BY tablename"
        )
        assert [row[0] for row in cursor.fetchall()] == sorted(rls.TABLES)
        cursor.execute(
            "SELECT table_name FROM information_schema.columns"
            " WHERE column_name = 'tenant_id' AND table_schema = 'public' ORDER BY 1"
        )
        assert [row[0] for row in cursor.fetchall()] == sorted(rls.TABLES)


@pytest.mark.django_db
def test_bound_connection_sees_one_tenant_even_without_a_filter(
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    a, b = two_tenants
    assert JournalEntry.objects.count() == 2  # unbound: everything
    rls.bind(a.id)
    assert rls.bound_tenant() == a.id
    assert set(JournalEntry.objects.values_list("tenant_id", flat=True)) == {a.id}
    assert Account.objects.filter(tenant=b).count() == 0  # the other tenant is invisible
    assert Account.objects.filter(tenant=a).count() == 2


@pytest.mark.django_db(transaction=True)
def test_bound_connection_cannot_write_another_tenants_row(
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    a, b = two_tenants
    rls.bind(a.id)
    with pytest.raises(DatabaseError, match="row-level security"), transaction.atomic():
        Account.objects.create(tenant=b, code="9999", name="smuggled", type="asset", currency="USD")
    rls.unbind()
    assert not Account.objects.filter(code="9999").exists()


@pytest.mark.django_db
def test_requests_bind_their_tenant_and_the_middleware_unbinds(
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    a, _ = two_tenants
    response = client_for(ApiKey.issue(a, "c")).get("/api/entries")
    assert response.status_code == 200
    assert [e["lines"][0]["amount"] for e in response.json()["results"]] == ["5.000000"]
    assert rls.bound_tenant() is None  # the connection was handed back clean
    assert Client().get("/health").status_code == 200
