import pytest
from rest_framework.test import APIClient

from tally.adapters.models import Account, Tenant
from tests.api.conftest import entry_body

Ledger = tuple[Tenant, Account, Account]


@pytest.mark.django_db
def test_accounts_list_is_scoped_to_the_tenant(
    client: APIClient, other_client: APIClient, ledger: Ledger
) -> None:
    codes = [a["code"] for a in client.get("/api/accounts").json()["results"]]
    assert codes == ["1200", "4000"]
    assert other_client.get("/api/accounts").json()["results"] == []


@pytest.mark.django_db(transaction=True)
def test_balance_now_and_as_of(client: APIClient, ledger: Ledger) -> None:
    for day, amount in ((1, "10"), (2, "20"), (3, "40")):
        client.post(
            "/api/entries",
            entry_body(
                ("1200", amount), ("4000", f"-{amount}"), occurred_at=f"2026-01-0{day}T12:00:00Z"
            ),
            format="json",
        )
    now = client.get("/api/accounts/1200/balance").json()
    assert now["balance"] == "70.000000" and now["currency"] == "USD" and now["as_of"]

    as_of = client.get("/api/accounts/1200/balance?as_of=2026-01-02T23:59:59Z").json()
    assert as_of["balance"] == "30.000000" and as_of["as_of"] == "2026-01-02T23:59:59Z"

    before = client.get("/api/accounts/4000/balance?as_of=2025-12-31T00:00:00Z").json()
    assert before["balance"] == "0.000000"


@pytest.mark.django_db
def test_balance_errors(client: APIClient, other_client: APIClient, ledger: Ledger) -> None:
    assert client.get("/api/accounts/9999/balance").status_code == 404
    assert other_client.get("/api/accounts/1200/balance").status_code == 404
    bad = client.get("/api/accounts/1200/balance?as_of=2026-01-01")
    assert bad.status_code == 422 and bad.json()["as_of"] == "2026-01-01"
    empty = client.get("/api/accounts/1200/balance").json()
    assert empty["balance"] == "0.000000" and empty["as_of"] is None


@pytest.mark.django_db
def test_openapi_is_public_and_documents_the_key(anon: APIClient) -> None:
    response = anon.get("/openapi.json")
    assert response.status_code == 200
    doc = response.json()
    assert doc["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-Api-Key",
    }
    assert {
        "/api/entries",
        "/api/entries/{entry_id}/reverse",
        "/api/accounts/{code}/balance",
    } <= set(doc["paths"])
    assert anon.get("/docs").status_code == 200
