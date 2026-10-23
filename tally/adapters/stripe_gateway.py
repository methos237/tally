"""The one module that talks to Stripe. Everything else sees invoices and customers.

Collection only: Tally issues its own invoices and keeps the books; Stripe moves the
test money. One cached StripeClient (no global api_key), amounts in minor units, an
idempotency key per call so a retried task cannot charge twice, and the Stripe ids
stored on our rows before confirmation so a webhook always resolves to an invoice.
"""

from functools import cache

import stripe
from django.conf import settings

from tally.adapters import models
from tally.domain.money import Currency, Money

# The 4242 4242 4242 4242 test card as a ready-made PaymentMethod. A real integration
# would save a card per customer with a SetupIntent; this project only ever runs in
# test mode, so every customer pays with the same test card.
TEST_CARD = "pm_card_visa"


@cache
def client() -> stripe.StripeClient:
    base = settings.STRIPE_API_BASE
    return stripe.StripeClient(
        settings.STRIPE_TEST_SECRET_KEY, base_addresses={"api": base} if base else None
    )


def minor_units(money: Money) -> int:
    """49.00 USD -> 4900; 1000 JPY -> 1000. Exact by construction: Money is quantized."""
    return int(money.amount.scaleb(money.currency.exponent))


def ensure_customer(customer: models.Customer) -> str:
    """The Stripe customer id for this customer, created on first use."""
    if customer.stripe_customer_id:
        return customer.stripe_customer_id
    created = client().v1.customers.create(
        params={
            "name": customer.name,
            "email": customer.email,
            "metadata": {
                "tally_customer_id": str(customer.id),
                "tenant_id": str(customer.tenant_id),
            },
        },
        options={"idempotency_key": f"tally-customer-{customer.id}"},
    )
    customer.stripe_customer_id = created.id
    customer.save(update_fields=["stripe_customer_id"])
    return created.id


def collect(invoice: models.Invoice) -> stripe.PaymentIntent:
    """Create, record, then confirm a PaymentIntent for the invoice.

    Two calls on purpose: the intent id is on the invoice before Stripe can emit any
    payment_intent.* event, so the webhook is the only writer of "paid" and a decline
    (CardError on confirm) still reaches the invoice as payment_intent.payment_failed.
    Off session, dynamic payment methods with redirects disabled (no return_url).
    """
    money = Money(invoice.amount, Currency(invoice.currency))
    intent = client().v1.payment_intents.create(
        params={
            "amount": minor_units(money),
            "currency": money.currency.value.lower(),
            "customer": ensure_customer(invoice.subscription.customer),
            "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"},
            "description": f"Tally invoice {invoice.id}",
            "metadata": {"tally_invoice_id": str(invoice.id)},
        },
        options={"idempotency_key": f"tally-invoice-{invoice.id}-create"},
    )
    invoice.stripe_payment_intent_id = intent.id
    invoice.save(update_fields=["stripe_payment_intent_id"])
    return client().v1.payment_intents.confirm(
        intent.id,
        params={"payment_method": TEST_CARD, "off_session": True},
        options={"idempotency_key": f"tally-invoice-{invoice.id}-confirm"},
    )


def verify(payload: bytes, signature: str | None) -> stripe.Event:
    """Check Stripe-Signature (HMAC-SHA256 over `t.payload`, timestamp within 300 s).
    Raises ValueError for a bad body or a bad signature alike."""
    try:
        event: stripe.Event = stripe.Webhook.construct_event(
            payload, signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError as exc:
        raise ValueError(str(exc)) from exc
    return event
