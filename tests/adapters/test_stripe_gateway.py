"""Against stripe-mock: request shapes and the ids we store. `live` tests hit test mode."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from freezegun import freeze_time

from tally.adapters import billing, stripe_gateway
from tally.adapters.models import Invoice, Subscription
from tally.adapters.tasks import bill_due_subscriptions, collect_invoice
from tally.domain.money import Currency, Money
from tests.adapters.test_billing import NOW, balance
from tests.conftest import LIVE_KEY


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
def test_collect_stores_the_payment_intent_id(subscription: Subscription) -> None:
    invoice = billing.issue_invoice(subscription, NOW)
    intent = stripe_gateway.collect(invoice)
    invoice.refresh_from_db()
    assert invoice.stripe_payment_intent_id == intent.id
    assert intent.id.startswith("pi_")


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
@pytest.mark.django_db
def test_live_test_card_pays_the_invoice_and_posts_cash(
    subscription: Subscription, settings: object
) -> None:
    settings.STRIPE_API_BASE = ""  # type: ignore[attr-defined]
    settings.STRIPE_TEST_SECRET_KEY = LIVE_KEY  # type: ignore[attr-defined]
    now = datetime.now(UTC)
    invoice = billing.issue_invoice(subscription, now)
    assert collect_invoice(invoice.id) == "succeeded"
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    assert balance(subscription.tenant_id, "1000") == Decimal("49")
    assert balance(subscription.tenant_id, "1200") == Decimal(0)
