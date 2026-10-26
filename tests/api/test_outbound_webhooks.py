"""Outbound webhooks end to end: outbox row in the business transaction, delivery to a
local receiver with a verifiable signature, backoff, dead letter, redelivery."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
import stripe
from freezegun import freeze_time

from tally.adapters import billing, outbox
from tally.adapters.models import OutboxMessage, Subscription, WebhookEndpoint
from tally.adapters.tasks import deliver_due_webhooks
from tests.api.conftest import Idem, Receiver
from tests.conftest import NOW


def verify(secret: str, body: bytes, header: str) -> bool:
    """Stripe's own verifier accepts our header: the recipe is theirs."""
    try:
        stripe.WebhookSignature.verify_header(body, header, secret, tolerance=300)
    except stripe.SignatureVerificationError:
        return False
    return True


@pytest.mark.django_db
def test_issuing_an_invoice_queues_a_signed_delivery_that_verifies(
    subscription: Subscription, endpoint: WebhookEndpoint, receiver: Receiver
) -> None:
    invoice = billing.issue_invoice(subscription, NOW)
    message = OutboxMessage.objects.get(event_type="invoice.issued")
    assert message.endpoint_id == endpoint.id
    assert message.payload["invoice_id"] == invoice.id
    assert message.payload["amount"] == "49.000000"  # Decimal travels as a string

    assert deliver_due_webhooks() == 2  # the journal entry's own entry.posted goes out too

    headers, body = next(r for r in receiver.requests if r[0]["X-Tally-Event"] == "invoice.issued")
    assert verify(endpoint.secret, body, headers["X-Tally-Signature"])
    assert not verify("whsec_wrong", body, headers["X-Tally-Signature"])
    assert not verify(endpoint.secret, body + b" ", headers["X-Tally-Signature"])
    envelope = json.loads(body)
    assert (envelope["id"], envelope["type"]) == (message.id, "invoice.issued")
    assert envelope["data"]["invoice_id"] == invoice.id
    assert headers["X-Tally-Event"] == "invoice.issued"
    message.refresh_from_db()
    assert message.delivered_at is not None and message.last_status == 200


def test_signature_older_than_five_minutes_does_not_verify() -> None:
    body = b'{"id":1}'
    header = outbox.sign("s", body, at=1_000_000)
    with freeze_time(datetime.fromtimestamp(1_000_300, tz=UTC)):
        assert verify("s", body, header)
    with freeze_time(datetime.fromtimestamp(1_000_301, tz=UTC)):
        assert not verify("s", body, header)


@pytest.mark.django_db
def test_payment_and_state_changes_are_published_too(
    subscription: Subscription, endpoint: WebhookEndpoint
) -> None:
    invoice = billing.issue_invoice(subscription, NOW)
    billing.mark_failed(invoice.id)
    billing.mark_paid(invoice.id, NOW)
    types = list(OutboxMessage.objects.order_by("id").values_list("event_type", flat=True))
    assert types.count("entry.posted") == 2  # the invoice entry and the payment entry
    assert [t for t in types if t != "entry.posted"] == [
        "invoice.issued",
        "subscription.past_due",
        "subscription.active",
        "invoice.paid",
    ]


@pytest.mark.django_db
def test_disabled_endpoints_and_other_tenants_get_nothing(
    subscription: Subscription, endpoint: WebhookEndpoint, other_tenant: Any
) -> None:
    endpoint.disabled_at = NOW
    endpoint.save()
    WebhookEndpoint.objects.create(tenant=other_tenant, url="http://x.test", secret="s")
    billing.issue_invoice(subscription, NOW)
    assert OutboxMessage.objects.count() == 0


@pytest.mark.django_db
def test_five_failures_follow_the_backoff_then_dead_letter_then_redeliver(
    subscription: Subscription,
    endpoint: WebhookEndpoint,
    receiver: Receiver,
    client: Idem,
) -> None:
    receiver.status = 500
    with freeze_time("2026-02-01 09:00:00") as clock:
        billing.issue_invoice(subscription, datetime(2026, 2, 1, 9, tzinfo=UTC))
        OutboxMessage.objects.filter(event_type="entry.posted").delete()  # one message to follow
        message = OutboxMessage.objects.get()
        # attempt 1 now, then 1 min, 5 min, 30 min, 2 h later: the fifth failure parks it
        expected_gaps = [0, 60, 300, 1800, 7200]
        for n, gap in enumerate(expected_gaps, start=1):
            clock.tick(gap - 1)
            assert deliver_due_webhooks() == 0  # one second early: not due yet
            clock.tick(1)
            assert deliver_due_webhooks() == 1
            message.refresh_from_db()
            assert message.attempts == n
            assert message.last_status == 500
        assert message.dead_at is not None
        clock.tick(7 * 24 * 3600)
        assert deliver_due_webhooks() == 0  # dead letters are not retried
        assert len(receiver.requests) == 5

        dead = client.get(f"/api/webhook-endpoints/{endpoint.id}/dead-letters").json()
        assert [d["id"] for d in dead] == [message.id]
        assert dead[0]["attempts"] == 5 and dead[0]["last_status"] == 500

        receiver.status = 200
        response = client.post(
            f"/api/webhook-endpoints/{endpoint.id}/dead-letters/{message.id}/redeliver"
        )
        assert response.status_code == 202
        assert deliver_due_webhooks() == 1
        message.refresh_from_db()
        assert message.delivered_at is not None and message.dead_at is None
        assert client.get(f"/api/webhook-endpoints/{endpoint.id}/dead-letters").json() == []


@pytest.mark.django_db
def test_unreachable_host_counts_as_a_failure(subscription: Subscription) -> None:
    WebhookEndpoint.objects.create(
        tenant=subscription.tenant, url="http://127.0.0.1:9/hooks", secret="s"
    )
    billing.issue_invoice(subscription, NOW)
    OutboxMessage.objects.filter(event_type="entry.posted").delete()  # one message to follow
    assert deliver_due_webhooks() == 1
    message = OutboxMessage.objects.get()
    assert message.delivered_at is None
    assert message.attempts == 1 and message.last_status is None and message.last_error


@pytest.mark.django_db
def test_endpoint_api_shows_the_secret_once_and_scopes_by_tenant(
    client: Idem, other_client: Idem
) -> None:
    created = client.post(
        "/api/webhook-endpoints", {"url": "https://acme.test/hooks"}, format="json"
    )
    assert created.status_code == 201
    assert created.json()["secret"].startswith("whsec_")
    listed = client.get("/api/webhook-endpoints").json()
    assert [e["url"] for e in listed] == ["https://acme.test/hooks"]
    assert "secret" not in listed[0]
    assert other_client.get("/api/webhook-endpoints").json() == []
    endpoint_id = created.json()["id"]
    assert other_client.get(f"/api/webhook-endpoints/{endpoint_id}/dead-letters").status_code == 404
    assert (
        client.post(f"/api/webhook-endpoints/{endpoint_id}/dead-letters/1/redeliver").status_code
        == 404
    )
    bad = client.post("/api/webhook-endpoints", {"url": "not a url"}, format="json")
    assert bad.status_code == 400
