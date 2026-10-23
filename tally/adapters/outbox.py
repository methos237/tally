"""Outbound webhooks: outbox rows written in the business transaction, delivered by a
Beat sweep with HMAC signature and a fixed backoff, dead-lettered after five failures.

Signature recipe (the one integrators verify, same as Stripe's):
    X-Tally-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, f"{t}.{body}")>
Reject if |now - t| > 300 s or the digest differs.
"""

import hashlib
import hmac
import json
import time
from datetime import timedelta
from typing import Any
from urllib import error, request

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from tally.adapters.models import OutboxMessage, WebhookEndpoint

SIGNATURE_HEADER = "X-Tally-Signature"
BACKOFF = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2)]
TIMEOUT_SECONDS = 10


def publish(tenant_id: int, event_type: str, data: dict[str, Any]) -> list[OutboxMessage]:
    """Queue `event_type` for every enabled endpoint of the tenant. Call inside the
    transaction that produces the event so the two commit or roll back together."""
    payload = json.loads(json.dumps(data, cls=DjangoJSONEncoder))  # Decimal/datetime -> str
    return OutboxMessage.objects.bulk_create(
        OutboxMessage(
            tenant_id=tenant_id,
            endpoint=endpoint,
            event_type=event_type,
            payload=payload,
            next_attempt_at=timezone.now(),
        )
        for endpoint in WebhookEndpoint.objects.filter(
            tenant_id=tenant_id, disabled_at__isnull=True
        )
    )


def sign(secret: str, body: bytes, at: int) -> str:
    digest = hmac.new(secret.encode(), f"{at}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={at},v1={digest}"


def verify(
    secret: str, body: bytes, header: str, now: int | None = None, tolerance: int = 300
) -> bool:
    """The receiver side of the recipe; tests use it, integrators copy it."""
    parts = dict(part.split("=", 1) for part in header.split(","))
    at = int(parts["t"])
    if abs((now or int(time.time())) - at) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, body, at), header)


def body_of(message: OutboxMessage) -> bytes:
    envelope = {
        "id": message.id,
        "type": message.event_type,
        "created_at": message.created_at,
        "data": message.payload,
    }
    return json.dumps(
        envelope, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":")
    ).encode()


def attempt(message: OutboxMessage) -> bool:
    """One HTTP POST. Updates attempts, schedule, dead-letter state. Returns success."""
    body = body_of(message)
    req = request.Request(
        message.endpoint.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(message.endpoint.secret, body, int(time.time())),
            "X-Tally-Event": message.event_type,
            "X-Tally-Delivery": str(message.id),
        },
    )
    now = timezone.now()
    message.attempts += 1
    try:
        with request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            message.last_status, message.last_error = response.status, ""
        message.delivered_at = now
    except error.HTTPError as exc:
        message.last_status, message.last_error = exc.code, exc.reason
    except (error.URLError, TimeoutError, OSError) as exc:
        message.last_status, message.last_error = None, str(exc)
    if message.delivered_at is None:
        if message.attempts >= OutboxMessage.MAX_ATTEMPTS:
            message.dead_at = now
        else:
            message.next_attempt_at = now + BACKOFF[message.attempts - 1]
    message.save()
    return message.delivered_at is not None


def redeliver(message: OutboxMessage) -> None:
    """Take a dead letter back into the queue with a fresh attempt budget."""
    message.dead_at = None
    message.attempts = 0
    message.next_attempt_at = timezone.now()
    message.save(update_fields=["dead_at", "attempts", "next_attempt_at"])
