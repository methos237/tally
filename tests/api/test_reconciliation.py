"""Upload, reconcile, resolve: the statement API end to end against a seeded ledger."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from tally.adapters import billing
from tally.adapters.models import (
    JournalEntry,
    OutboxMessage,
    ReconciliationException,
    Statement,
    Subscription,
    WebhookEndpoint,
)
from tests.api.conftest import Idem
from tests.conftest import balance

BANK_CSV = """Date,Description,Reference,Amount
2026-02-01,Card settlement,pi_live_1,49.00
2026-02-03,Card settlement,,49.00
2026-02-04,Bank fee,FEE-77,-15.00
"""
PROCESSOR_CSV = """id,created,amount,currency,description
pi_live_1,2026-02-01T10:00:00Z,49.00,usd,payment
"""


@pytest.fixture
def ledger_with_two_payments(subscription: Subscription) -> Subscription:
    """Two paid invoices: 2026-02-01 (intent pi_live_1) and 2026-02-05 (no intent)."""
    first = billing.issue_invoice(subscription, datetime(2026, 2, 1, tzinfo=UTC))
    first.stripe_payment_intent_id = "pi_live_1"
    first.save()
    billing.mark_paid(first.id, datetime(2026, 2, 1, 12, tzinfo=UTC))
    second = billing.issue_invoice(subscription, datetime(2026, 2, 5, tzinfo=UTC))
    billing.mark_paid(second.id, datetime(2026, 2, 5, 12, tzinfo=UTC))
    return subscription


def upload(client: Idem, csv: str = BANK_CSV) -> Any:
    return client.post("/api/statements", csv, content_type="text/csv")


@pytest.mark.django_db
def test_upload_parses_the_bank_layout(client: Idem, ledger_with_two_payments: Any) -> None:
    response = upload(client)
    assert response.status_code == 201
    body = response.json()
    assert (body["source"], body["period_start"], body["period_end"]) == (
        "bank",
        "2026-02-01",
        "2026-02-04",
    )
    assert [line["amount"] for line in body["lines"]] == ["49.000000", "49.000000", "-15.000000"]
    assert body["lines"][0]["currency"] == "USD"  # the tenant's cash currency
    assert body["reconciled_at"] is None and body["exceptions"] == []


@pytest.mark.django_db
def test_upload_parses_the_processor_layout(client: Idem, ledger_with_two_payments: Any) -> None:
    body = upload(client, PROCESSOR_CSV).json()
    assert body["source"] == "processor"
    assert body["lines"][0]["reference"] == "pi_live_1"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "csv",
    [
        "Foo,Bar\n1,2\n",
        "Date,Description,Reference,Amount\n",
        "Date,Description,Reference,Amount\nnope,x,y,1\n",
    ],
)
def test_bad_csv_is_422_and_stores_nothing(
    client: Idem, ledger_with_two_payments: Any, csv: str
) -> None:
    assert upload(client, csv).status_code == 422
    assert Statement.objects.count() == 0


@pytest.mark.django_db
def test_reconcile_matches_by_reference_then_window_and_excepts_the_rest(
    client: Idem, ledger_with_two_payments: Subscription
) -> None:
    WebhookEndpoint.objects.create(
        tenant=ledger_with_two_payments.tenant, url="http://x.test", secret="s"
    )
    statement_id = upload(client).json()["id"]
    body = client.post(f"/api/statements/{statement_id}/reconcile").json()

    rules = [line["match_rule"] for line in body["lines"]]
    assert rules == ["reference", "amount_window", ""]
    assert body["lines"][0]["matched_entry"] != body["lines"][1]["matched_entry"]
    assert [(e["line_no"], e["reason"], e["difference"]) for e in body["exceptions"]] == [
        (3, "unmatched", "-15.000000")
    ]
    assert body["reconciled_at"] is None
    assert list(OutboxMessage.objects.values_list("event_type", flat=True)) == [
        "reconciliation.exception"
    ]

    again = client.post(f"/api/statements/{statement_id}/reconcile").json()
    assert len(again["exceptions"]) == 1  # a rerun does not duplicate exceptions


@pytest.mark.django_db
def test_adjusting_entry_balances_and_reconciles_the_statement(
    client: Idem, ledger_with_two_payments: Subscription
) -> None:
    tenant = ledger_with_two_payments.tenant
    fees = tenant.accounts.create(code="6100", name="Fees", type="expense", currency="USD")
    statement_id = upload(client).json()["id"]
    client.post(f"/api/statements/{statement_id}/reconcile")
    exception = ReconciliationException.objects.get()
    cash_before = balance(tenant.id, "1000")

    response = client.post(
        f"/api/reconciliation-exceptions/{exception.id}/resolve",
        {"action": "adjust", "account": "6100"},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolution"] == "adjusted" and body["adjusting_entry"] is not None
    entry = JournalEntry.objects.get(id=body["adjusting_entry"])
    assert (entry.source_type, entry.source_id) == ("adjustment", str(exception.id))
    assert sum(line.amount for line in entry.lines.all()) == 0
    assert balance(tenant.id, "1000") == cash_before - Decimal("15")
    assert balance(tenant.id, fees.code) == Decimal("15")
    assert client.get(f"/api/statements/{statement_id}").json()["reconciled_at"] is not None

    assert client.get("/api/reconciliation-exceptions?status=open").json() == []
    assert len(client.get("/api/reconciliation-exceptions?status=resolved").json()) == 1
    again = client.post(
        f"/api/reconciliation-exceptions/{exception.id}/resolve",
        {"action": "explain", "explanation": "late"},
        format="json",
    )
    assert again.status_code == 409


@pytest.mark.django_db
def test_explaining_resolves_without_an_entry(client: Idem, ledger_with_two_payments: Any) -> None:
    statement_id = upload(client).json()["id"]
    client.post(f"/api/statements/{statement_id}/reconcile")
    exception = ReconciliationException.objects.get()
    body = client.post(
        f"/api/reconciliation-exceptions/{exception.id}/resolve",
        {"action": "explain", "explanation": "monthly bank fee, booked separately"},
        format="json",
    ).json()
    assert (body["resolution"], body["adjusting_entry"]) == ("explained", None)
    assert JournalEntry.objects.filter(source_type="adjustment").count() == 0
    missing = client.post(
        f"/api/reconciliation-exceptions/{exception.id}/resolve",
        {"action": "adjust"},
        format="json",
    )
    assert missing.status_code == 400


@pytest.mark.django_db
def test_other_tenant_sees_404(
    client: Idem, other_client: Idem, ledger_with_two_payments: Any
) -> None:
    statement_id = upload(client).json()["id"]
    assert other_client.get(f"/api/statements/{statement_id}").status_code == 404
    assert other_client.post(f"/api/statements/{statement_id}/reconcile").status_code == 404
    assert other_client.get("/api/reconciliation-exceptions").json() == []
