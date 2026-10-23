"""Outbound webhooks end to end: outbox row in the business transaction, delivery to a
local receiver with a verifiable signature, backoff, dead letter, redelivery."""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from freezegun import freeze_time

from tally.adapters import billing, outbox
from tally.adapters.models import OutboxMessage, Subscription, WebhookEndpoint
from tally.adapters.tasks import deliver_due_webhooks
from tests.adapters.test_billing import NOW
from tests.api.conftest import Idem


class Receiver:
    """A tenant's endpoint on localhost. Records every request; `status` is what it answers."""

    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, str], bytes]] = []
        self.status = 200
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                receiver.requests.append((dict(self.headers), body))
                self.send_response(receiver.status)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hooks"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    r = Receiver()
    yield r
    r.close()


@pytest.fixture
def endpoint(subscription: Subscription, receiver: Receiver) -> WebhookEndpoint:
    return WebhookEndpoint.objects.create(
        tenant=subscription.tenant, url=receiver.url, secret=WebhookEndpoint.new_secret()
    )


@pytest.mark.django_db
def test_issuing_an_invoice_queues_a_signed_delivery_that_verifies(
    subscription: Subscription, endpoint: WebhookEndpoint, receiver: Receiver
) -> None:
    invoice = billing.issue_invoice(subscription, NOW)
    message = OutboxMessage.objects.get()
    assert (message.event_type, message.endpoint_id) == ("invoice.issued", endpoint.id)
    assert message.payload["invoice_id"] == invoice.id
    assert message.payload["amount"] == "49.000000"  # Decimal travels as a string

    assert deliver_due_webhooks() == 1

    headers, body = receiver.requests[0]
    assert outbox.verify(endpoint.secret, body, headers["X-Tally-Signature"])
    assert not outbox.verify("whsec_wrong", body, headers["X-Tally-Signature"])
    assert not outbox.verify(endpoint.secret, body + b" ", headers["X-Tally-Signature"])
    envelope = json.loads(body)
    assert (envelope["id"], envelope["type"]) == (message.id, "invoice.issued")
    assert envelope["data"]["invoice_id"] == invoice.id
    assert headers["X-Tally-Event"] == "invoice.issued"
    message.refresh_from_db()
    assert message.delivered_at is not None and message.last_status == 200


@pytest.mark.django_db
def test_signature_older_than_five_minutes_does_not_verify() -> None:
    body = b'{"id":1}'
    header = outbox.sign("s", body, at=1_000_000)
    assert outbox.verify("s", body, header, now=1_000_000 + 300)
    assert not outbox.verify("s", body, header, now=1_000_000 + 301)


@pytest.mark.django_db
def test_payment_and_state_changes_are_published_too(
    subscription: Subscription, endpoint: WebhookEndpoint
) -> None:
    invoice = billing.issue_invoice(subscription, NOW)
    billing.mark_failed(invoice.id)
    billing.mark_paid(invoice.id, NOW)
    types = list(OutboxMessage.objects.order_by("id").values_list("event_type", flat=True))
    assert types == [
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
        message = OutboxMessage.objects.get()
        # attempt 1 now, then 1 min, 5 min, 30 min, 2 h later: the fifth failure parks it
        expected_gaps = [0, 60, 300, 1800, 7200]
        for n, gap in enumerate(expected_gaps, start=1):
            clock.tick(gap)
            assert deliver_due_webhooks() == 0
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
    assert deliver_due_webhooks() == 0
    message = OutboxMessage.objects.get()
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
