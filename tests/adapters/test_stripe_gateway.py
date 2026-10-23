"""Against stripe-mock: request shapes and the ids we store. `live` tests hit test mode."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from freezegun import freeze_time

from tally.adapters import billing, stripe_gateway
from tally.adapters.models import Invoice, Subscription
from tally.adapters.tasks import bill_due_subscriptions, collect_invoice
from tally.domain.money import Currency, Money
from tests.conftest import LIVE_KEY, NOW


@pytest.mark.parametrize(
    ("amount", "currency", "minor"),
    [("49.00", "USD", 4900), ("0.01", "EUR", 1), ("1000", "JPY", 1000), ("12.345", "GBP", 1234)],
)
def test_minor_units(amount: str, currency: str, minor: int) -> None:
    assert stripe_gateway.minor_units(Money(Decimal(amount), Currency(currency))) == minor


@pytest.mark.django_db
def test_customer_is_created_once_and_its_id_kept(subscription: Subscription) -> None:
    first = stripe_gateway.ensure_customer(subscription.customer)
    subscription.customer.refresh_from_db()
    assert subscription.customer.stripe_customer_id == first
    assert first.startswith("cus_")
    assert (
        stripe_gateway.ensure_customer(subscription.customer) == first
    )  # mock would mint a new id


@pytest.mark.django_db
def test_collect_stores_the_payment_intent_id_before_confirming(
    subscription: Subscription,
) -> None:
    invoice = billing.issue_invoice(subscription, NOW)
    intent = stripe_gateway.collect(invoice)
    invoice.refresh_from_db()
    assert invoice.stripe_payment_intent_id is not None
    assert invoice.stripe_payment_intent_id.startswith("pi_")
    assert intent.object == "payment_intent"
    assert invoice.status == "open"  # only the webhook marks it paid


@pytest.mark.django_db
def test_collect_task_skips_an_invoice_that_is_no_longer_open(subscription: Subscription) -> None:
    invoice = billing.issue_invoice(subscription, NOW)
    billing.mark_paid(invoice.id, NOW)
    assert collect_invoice(invoice.id) == "paid"
    invoice.refresh_from_db()
    assert invoice.stripe_payment_intent_id is None


@pytest.mark.django_db
def test_billing_run_hands_each_new_invoice_to_collection(subscription: Subscription) -> None:
    with freeze_time("2026-02-01"):
        assert bill_due_subscriptions() == 1
    invoice = Invoice.objects.get()
    assert invoice.stripe_payment_intent_id is not None


@pytest.mark.live
@pytest.mark.skipif(not LIVE_KEY, reason="STRIPE_TEST_SECRET_KEY not set")
@pytest.mark.django_db
def test_live_test_card_is_charged_in_stripe_test_mode(
    subscription: Subscription, settings: Any
) -> None:
    settings.STRIPE_API_BASE = ""
    settings.STRIPE_TEST_SECRET_KEY = LIVE_KEY
    stripe_gateway.client.cache_clear()
    try:
        invoice = billing.issue_invoice(subscription, datetime.now(UTC))
        assert collect_invoice(invoice.id) == "succeeded"
        invoice.refresh_from_db()
        intent = stripe_gateway.client().v1.payment_intents.retrieve(
            invoice.stripe_payment_intent_id or ""
        )
        assert (intent.status, intent.amount, intent.currency) == ("succeeded", 4900, "usd")
        assert intent.metadata["tally_invoice_id"] == str(invoice.id)
    finally:
        stripe_gateway.client.cache_clear()
