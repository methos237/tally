import pytest
from rest_framework.test import APIClient

from tally.adapters.models import Account, AccountBalance, JournalEntry, Tenant
from tests.api.conftest import entry_body

PROBLEM = "application/problem+json"
Ledger = tuple[Tenant, Account, Account]


@pytest.mark.django_db(transaction=True)
def test_post_balanced_entry_returns_201_and_moves_balances(
    client: APIClient, ledger: Ledger
) -> None:
    _, ar, rev = ledger
    response = client.post(
        "/api/entries", entry_body(("1200", "149.00"), ("4000", "-149.00")), format="json"
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["source"] == {"type": "invoice", "id": "inv_1042"}
    assert body["lines"] == [
        {"account": "1200", "amount": "149.000000", "currency": "USD"},
        {"account": "4000", "amount": "-149.000000", "currency": "USD"},
    ]
    assert body["reverses"] is None and body["reversed_by"] is None
    assert AccountBalance.objects.get(account=ar).balance == 149
    assert AccountBalance.objects.get(account=rev).balance == -149


@pytest.mark.django_db
def test_unbalanced_entry_is_422_naming_currency_and_difference(
    client: APIClient, ledger: Ledger
) -> None:
    response = client.post(
        "/api/entries", entry_body(("1200", "149.00"), ("4000", "-148.99")), format="json"
    )
    assert response.status_code == 422
    assert response["Content-Type"] == PROBLEM
    body = response.json()
    assert body["type"].endswith("/posting/UnbalancedEntry")
    assert body["currency"] == "USD" and body["difference"] == "0.010000"
    assert JournalEntry.objects.count() == 0


@pytest.mark.django_db
def test_single_line_zero_line_and_unknown_code_are_422(client: APIClient, ledger: Ledger) -> None:
    one = client.post("/api/entries", entry_body(("1200", "1")), format="json")
    assert one.status_code == 422 and one.json()["type"].endswith("/posting/SingleLineEntry")

    zero = client.post(
        "/api/entries", entry_body(("1200", "0"), ("4000", "1"), ("1200", "-1")), format="json"
    )
    assert zero.status_code == 422 and zero.json()["type"].endswith("/posting/ZeroLine")

    unknown = client.post("/api/entries", entry_body(("1200", "1"), ("9999", "-1")), format="json")
    assert unknown.status_code == 422 and unknown.json()["account"] == "9999"


@pytest.mark.django_db
def test_malformed_body_is_400_with_field_errors(client: APIClient, ledger: Ledger) -> None:
    response = client.post(
        "/api/entries",
        {"occurred_at": "yesterday", "lines": [{"account": "1200", "amount": "x"}]},
        format="json",
    )
    assert response.status_code == 400
    assert response["Content-Type"] == PROBLEM
    errors = response.json()["errors"]
    assert set(errors) == {"occurred_at", "source", "lines"}


@pytest.mark.django_db
def test_float_amounts_are_rejected(client: APIClient, ledger: Ledger) -> None:
    body = entry_body(("1200", "1"), ("4000", "-1"))
    body["lines"][0]["amount"] = 1.0  # type: ignore[index]
    response = client.post("/api/entries", body, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_list_is_cursor_paginated_newest_first_and_filterable(
    client: APIClient, ledger: Ledger
) -> None:
    for n in range(3):
        client.post(
            "/api/entries",
            entry_body(
                ("1200", "1"),
                ("4000", "-1"),
                occurred_at=f"2026-01-0{n + 1}T00:00:00Z",
                source={"type": "invoice" if n else "payment", "id": str(n)},
            ),
            format="json",
        )
    page = client.get("/api/entries?page_size=2").json()
    assert [e["occurred_at"] for e in page["results"]] == [
        "2026-01-03T00:00:00Z",
        "2026-01-02T00:00:00Z",
    ]
    assert page["next"] and page["previous"] is None
    rest = client.get(page["next"]).json()
    assert [e["occurred_at"] for e in rest["results"]] == ["2026-01-01T00:00:00Z"]
    assert rest["next"] is None

    assert len(client.get("/api/entries?source_type=payment").json()["results"]) == 1
    assert len(client.get("/api/entries?account=4000").json()["results"]) == 3
    assert client.get("/api/entries?account=none").json()["results"] == []


@pytest.mark.django_db
def test_another_tenants_entry_is_404_not_403(
    client: APIClient, other_client: APIClient, ledger: Ledger
) -> None:
    created = client.post("/api/entries", entry_body(("1200", "1"), ("4000", "-1")), format="json")
    entry_id = created.json()["id"]
    assert client.get(f"/api/entries/{entry_id}").status_code == 200

    response = other_client.get(f"/api/entries/{entry_id}")
    assert response.status_code == 404
    assert response["Content-Type"] == PROBLEM
    assert (
        other_client.post(f"/api/entries/{entry_id}/reverse", {}, format="json").status_code == 404
    )
    assert other_client.get("/api/entries").json()["results"] == []


@pytest.mark.django_db(transaction=True)
def test_reverse_posts_negated_entry_once(client: APIClient, ledger: Ledger) -> None:
    _, ar, _ = ledger
    entry_id = client.post(
        "/api/entries", entry_body(("1200", "10"), ("4000", "-10")), format="json"
    ).json()["id"]

    response = client.post(
        f"/api/entries/{entry_id}/reverse", {"occurred_at": "2026-11-04T00:00:00Z"}, format="json"
    )
    assert response.status_code == 201, response.content
    reversal = response.json()
    assert reversal["reverses"] == entry_id
    assert reversal["source"] == {"type": "reversal", "id": str(entry_id)}
    assert [line["amount"] for line in reversal["lines"]] == ["-10.000000", "10.000000"]
    assert client.get(f"/api/entries/{entry_id}").json()["reversed_by"] == reversal["id"]
    assert AccountBalance.objects.get(account=ar).balance == 0

    again = client.post(f"/api/entries/{entry_id}/reverse", {}, format="json")
    assert again.status_code == 409
    assert again.json()["entry"] == entry_id
