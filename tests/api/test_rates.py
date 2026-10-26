"""Multi-currency through the API: declared rates, the exchange_rates table, 422s."""

from decimal import Decimal

import pytest

from tally.adapters.models import Account, Tenant
from tests.api.conftest import Idem, entry_body

EUR_LINES = (("1210", "100.00"), ("4000", "-108.00"))


@pytest.fixture
def mixed(ledger: tuple[Tenant, Account, Account]) -> Tenant:
    tenant = ledger[0]
    Account.objects.create(
        tenant=tenant, code="1210", name="EUR receivable", type="asset", currency="EUR"
    )
    return tenant


def body(*lines: tuple[str, str], conversion: dict | None, eur_first: bool = True) -> dict:
    b = entry_body(*lines)
    b["lines"][0]["currency"] = "EUR"
    if conversion is not None:
        b["conversion"] = conversion
    return b


@pytest.mark.django_db
def test_declared_rate_posts_and_is_stored_on_the_entry(client: Idem, mixed: Tenant) -> None:
    response = client.post(
        "/api/entries",
        body(*EUR_LINES, conversion={"base": "USD", "rates": {"EUR": "1.08"}}),
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["conversion"] == {"base": "USD", "rates": {"EUR": "1.08000000"}}
    assert client.get("/api/accounts/1210/balance").json()["balance"] == "100.000000"
    assert client.get("/api/accounts/4000/balance").json()["balance"] == "-108.000000"


@pytest.mark.django_db
def test_rates_table_fills_the_conversion(client: Idem, mixed: Tenant) -> None:
    assert (
        client.post(
            "/api/rates",
            {"currency": "EUR", "base": "USD", "rate": "1.10", "as_of": "2026-10-01"},
            format="json",
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/rates",
            {"currency": "EUR", "base": "USD", "rate": "1.08", "as_of": "2026-11-01"},
            format="json",
        ).status_code
        == 201
    )
    assert [r["rate"] for r in client.get("/api/rates").json()] == ["1.08000000", "1.10000000"]

    # occurred_at is 2026-11-03: the 1.08 row applies
    response = client.post(
        "/api/entries", body(*EUR_LINES, conversion={"base": "USD"}), format="json"
    )
    assert response.status_code == 201, response.json()
    assert response.json()["conversion"]["rates"] == {"EUR": "1.08000000"}


@pytest.mark.django_db
def test_wrong_offset_is_422_with_the_converted_difference(client: Idem, mixed: Tenant) -> None:
    response = client.post(
        "/api/entries",
        body(
            ("1210", "100.00"),
            ("4000", "-107.00"),
            conversion={"base": "USD", "rates": {"EUR": "1.08"}},
        ),
        format="json",
    )
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"].endswith("posting/UnbalancedEntry")
    assert (problem["currency"], Decimal(problem["difference"])) == ("USD", Decimal("1"))


@pytest.mark.django_db
def test_missing_rate_is_422(client: Idem, mixed: Tenant) -> None:
    response = client.post(
        "/api/entries", body(*EUR_LINES, conversion={"base": "USD"}), format="json"
    )
    assert response.status_code == 422
    assert response.json()["type"].endswith("posting/MissingRate")
    assert "EUR" in response.json()["detail"]


@pytest.mark.django_db
def test_no_conversion_means_each_currency_balances_alone(client: Idem, mixed: Tenant) -> None:
    response = client.post("/api/entries", body(*EUR_LINES, conversion=None), format="json")
    assert response.status_code == 422
    assert response.json()["currency"] == "EUR"


@pytest.mark.django_db
def test_rates_are_tenant_scoped(client: Idem, other_client: Idem) -> None:
    client.post(
        "/api/rates",
        {"currency": "EUR", "base": "USD", "rate": "1.08", "as_of": "2026-10-01"},
        format="json",
    )
    assert other_client.get("/api/rates").json() == []
