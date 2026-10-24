"""The demo's payment is the production path: collect through stripe-mock, then the signed
webhook marks the invoice paid."""

from datetime import UTC, datetime

import pytest
from django.test import Client

from tally.adapters import billing, stripe_gateway
from tally.adapters.management.commands.demo_payment import succeeded_event
from tally.adapters.models import Invoice, Subscription


@pytest.mark.django_db
def test_demo_event_pays_the_invoice_through_the_webhook(
    subscription: Subscription, settings: object
) -> None:
    settings.STRIPE_WEBHOOK_SECRET = "whsec_demo"  # type: ignore[attr-defined]
    invoice = billing.issue_invoice(subscription, datetime(2026, 2, 1, 9, tzinfo=UTC))
    stripe_gateway.collect(invoice)  # stripe-mock
    invoice.refresh_from_db()
    assert invoice.stripe_payment_intent_id

    payload, signature = succeeded_event(invoice)
    response = Client().post(
        "/webhooks/stripe",
        payload,
        content_type="application/json",
        headers={"Stripe-Signature": signature},
    )
    assert response.status_code == 200
    assert Invoice.objects.get(id=invoice.id).status == "paid"
