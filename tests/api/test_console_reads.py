"""Read endpoints added for the console: subscriptions, invoices, statements list, reports,
balances on accounts and dead-letter counts on endpoints."""

from datetime import UTC, datetime, timedelta

import pytest
from rest_framework.test import APIClient

from tally.adapters import billing, reconciliation, reports
from tally.adapters.models import OutboxMessage, Subscription, Tenant, WebhookEndpoint

DAY = datetime(2026, 2, 1, 9, tzinfo=UTC)


@pytest.fixture
def invoiced(subscription: Subscription) -> Subscription:
    paid = billing.issue_invoice(subscription, DAY)
    billing.mark_paid(paid.id, DAY + timedelta(hours=1))
    billing.issue_invoice(subscription, DAY + timedelta(days=30))
    return subscription


@pytest.mark.django_db
def test_subscriptions_and_invoices_lists(client: APIClient, invoiced: Subscription) -> None:
    subs = client.get("/api/subscriptions").json()["results"]
    assert [s["customer"] for s in subs] == [invoiced.customer.name]
    assert subs[0]["plan"] == invoiced.plan.code and subs[0]["amount"] == "49.000000"

    invoices = client.get("/api/invoices").json()["results"]
    assert [i["status"] for i in invoices] == ["open", "paid"]  # newest first
    assert invoices[0]["customer"] == invoiced.customer.name
    assert [i["status"] for i in client.get("/api/invoices?status=open").json()["results"]] == [
        "open"
    ]


@pytest.mark.django_db
def test_lists_are_tenant_scoped(other_client: APIClient, invoiced: Subscription) -> None:
    assert other_client.get("/api/subscriptions").json()["results"] == []
    assert other_client.get("/api/invoices").json()["results"] == []
    assert other_client.get("/api/statements").json() == []


@pytest.mark.django_db
def test_accounts_carry_their_projected_balance(client: APIClient, invoiced: Subscription) -> None:
    by_code = {a["code"]: a for a in client.get("/api/accounts").json()["results"]}
    assert by_code["1200"]["balance"] == "49.000000"  # one open invoice outstanding
    assert by_code["4000"]["balance"] == "-98.000000"


@pytest.mark.django_db
def test_statements_list_is_a_summary(client: APIClient, subscription: Subscription) -> None:
    statement = reconciliation.import_statement(  # the subscription fixture adds cash 1000
        subscription.tenant_id, "Date,Description,Reference,Amount\n2026-02-01,fee,F1,-3.00\n"
    )
    rows = client.get("/api/statements").json()
    assert [r["id"] for r in rows] == [statement.id]
    assert "lines" not in rows[0] and rows[0]["reconciled_at"] is None


@pytest.mark.django_db
def test_endpoints_count_their_dead_letters(client: APIClient, tenant: Tenant) -> None:
    endpoint = WebhookEndpoint.objects.create(
        tenant=tenant, url="http://localhost:9/x", secret=WebhookEndpoint.new_secret()
    )
    for dead in (True, False):
        OutboxMessage.objects.create(
            tenant=tenant,
            endpoint=endpoint,
            event_type="invoice.paid",
            payload={},
            next_attempt_at=DAY,
            dead_at=DAY if dead else None,
        )
    rows = client.get("/api/webhook-endpoints").json()
    assert [(r["id"], r["dead_letters"]) for r in rows] == [(endpoint.id, 1)]


@pytest.mark.django_db
def test_reports_list_and_download(
    client: APIClient, other_client: APIClient, tenant: Tenant, invoiced: Subscription, bucket: str
) -> None:
    reports.write(tenant, DAY.date())
    rows = client.get("/api/reports").json()
    assert [r["day"] for r in rows] == ["2026-02-01"]
    assert rows[0]["key"] == f"{tenant.id}/2026-02-01.csv" and rows[0]["size"] > 0

    download = client.get("/api/reports/2026-02-01")
    assert download.status_code == 200 and download["Content-Type"] == "text/csv"
    assert download.content.decode().startswith("section,key,label,count,amount,currency")

    assert other_client.get("/api/reports/2026-02-01").status_code == 404
    assert client.get("/api/reports/2025-01-01").status_code == 404
