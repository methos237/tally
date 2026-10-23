"""POST /webhooks/stripe: signature, timestamp window, dedup, handlers.

Events are built to the recorded shape of payment_intent.* and signed with Stripe's
documented recipe (t=<ts>,v1=HMAC-SHA256(secret, f"{ts}.{body}")), which is the same
recipe tenants get for outbound webhooks.
"""

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from tally.adapters import billing
from tally.adapters.models import Invoice, JournalEntry, StripeEvent, Subscription
from tests.adapters.test_billing import NOW, balance

SECRET = "whsec_test_secret"
URL = "/webhooks/stripe"


def event(type_: str, intent_id: str, event_id: str = "evt_1") -> bytes:
    body = {
        "id": event_id,
        "object": "event",
        "api_version": "2026-09-30.endive",
        "created": int(time.time()),
        "livemode": False,
        "type": type_,
        "data": {"object": {"id": intent_id, "object": "payment_intent", "amount": 4900}},
    }
    return json.dumps(body).encode()


def sign(payload: bytes, secret: str = SECRET, at: int | None = None) -> str:
    ts = at or int(time.time())
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def deliver(client: Client, payload: bytes, signature: str) -> Any:
    return client.post(
        URL, payload, content_type="application/json", headers={"Stripe-Signature": signature}
    )


@pytest.fixture
def open_invoice(subscription: Subscription, settings: Any) -> Invoice:
    settings.STRIPE_WEBHOOK_SECRET = SECRET
    invoice = billing.issue_invoice(subscription, NOW)
    invoice.stripe_payment_intent_id = "pi_test_1"
    invoice.save()
    return invoice


@pytest.mark.django_db
def test_succeeded_marks_the_invoice_paid_and_posts_cash(open_invoice: Invoice) -> None:
    payload = event("payment_intent.succeeded", "pi_test_1")
    response = deliver(Client(), payload, sign(payload))
    assert response.status_code == 200
    open_invoice.refresh_from_db()
    assert open_invoice.status == "paid"
    assert balance(open_invoice.tenant_id, "1000") == Decimal("49")
    assert StripeEvent.objects.get(event_id="evt_1").processed_at is not None


@pytest.mark.django_db
def test_payment_failed_moves_the_subscription_to_past_due(open_invoice: Invoice) -> None:
    payload = event("payment_intent.payment_failed", "pi_test_1")
    assert deliver(Client(), payload, sign(payload)).status_code == 200
    open_invoice.subscription.refresh_from_db()
    assert open_invoice.subscription.status == "past_due"
    open_invoice.refresh_from_db()
    assert open_invoice.status == "open"


@pytest.mark.django_db
def test_tampered_signature_is_rejected_and_nothing_is_stored(open_invoice: Invoice) -> None:
    payload = event("payment_intent.succeeded", "pi_test_1")
    tampered = payload.replace(b"4900", b"4901")
    assert deliver(Client(), tampered, sign(payload)).status_code == 400
    assert deliver(Client(), payload, sign(payload, secret="whsec_other")).status_code == 400
    assert deliver(Client(), payload, "").status_code == 400
    assert StripeEvent.objects.count() == 0
    open_invoice.refresh_from_db()
    assert open_invoice.status == "open"


@pytest.mark.django_db
def test_timestamp_older_than_five_minutes_is_rejected(open_invoice: Invoice) -> None:
    payload = event("payment_intent.succeeded", "pi_test_1")
    stale = sign(payload, at=int(time.time()) - 301)
    assert deliver(Client(), payload, stale).status_code == 400
    assert StripeEvent.objects.count() == 0


@pytest.mark.django_db
def test_the_same_event_delivered_twice_is_processed_once(open_invoice: Invoice) -> None:
    payload = event("payment_intent.succeeded", "pi_test_1")
    first = deliver(Client(), payload, sign(payload))
    second = deliver(Client(), payload, sign(payload))
    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json() == {"received": True, "duplicate": True}
    assert StripeEvent.objects.count() == 1
    assert JournalEntry.objects.filter(source_type="payment").count() == 1


@pytest.mark.django_db
def test_an_intent_we_did_not_create_is_acknowledged_and_ignored(open_invoice: Invoice) -> None:
    payload = event("payment_intent.succeeded", "pi_from_stripe_trigger", event_id="evt_2")
    assert deliver(Client(), payload, sign(payload)).status_code == 200
    assert StripeEvent.objects.get(event_id="evt_2").processed_at is not None
    assert JournalEntry.objects.filter(source_type="payment").count() == 0


@pytest.mark.django_db
def test_get_is_not_allowed(settings: Any) -> None:
    assert Client().get(URL).status_code == 405
