"""Pay one open invoice the way production does, against stripe-mock: collect it (a
PaymentIntent is created and confirmed), then deliver the `payment_intent.succeeded`
webhook that stripe-mock cannot send, signed with STRIPE_WEBHOOK_SECRET, to the running
API. The webhook, not this command, marks the invoice paid."""

import json
import time
from typing import Any
from urllib import request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tally.adapters import billing, outbox, stripe_gateway
from tally.adapters.models import Invoice, Subscription


def succeeded_event(invoice: Invoice) -> tuple[bytes, str]:
    """A payment_intent.succeeded body in Stripe's recorded shape, and its signature."""
    body = {
        "id": f"evt_demo_{invoice.id}",
        "object": "event",
        "api_version": "2026-09-30.endive",
        "created": int(time.time()),
        "livemode": False,
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": invoice.stripe_payment_intent_id, "object": "payment_intent"}},
    }
    payload = json.dumps(body).encode()
    return payload, outbox.sign(settings.STRIPE_WEBHOOK_SECRET, payload, int(time.time()))


class Command(BaseCommand):
    help = "Collect the oldest open invoice of a tenant through stripe-mock and webhook it paid."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--webhook-url", default="http://localhost:8001/webhooks/stripe")

    def handle(self, *args: Any, **options: Any) -> None:
        invoice = (
            Invoice.objects.filter(tenant__name=options["tenant"], status="open")
            .select_related("subscription__customer")
            .order_by("issued_at")
            .first()
        )
        if invoice is None:  # every invoice already paid (a rerun): bill the next period now
            subscription = (
                Subscription.objects.filter(tenant__name=options["tenant"], status="active")
                .order_by("id")
                .first()
            )
            if subscription is None:
                raise CommandError(
                    f"no open invoice or active subscription for {options['tenant']}"
                )
            invoice = billing.issue_invoice(subscription, timezone.now())
        intent = stripe_gateway.collect(invoice)
        self.stdout.write(f"invoice {invoice.id} {invoice.amount} {invoice.currency}: {intent.id}")
        invoice.refresh_from_db()
        payload, signature = succeeded_event(invoice)
        req = request.Request(
            options["webhook_url"],
            data=payload,
            headers={"Content-Type": "application/json", "Stripe-Signature": signature},
        )
        with request.urlopen(req, timeout=10) as response:
            self.stdout.write(f"webhook {response.status}: {response.read().decode()}")
        for _ in range(20):  # the worker applies the event; wait for it
            time.sleep(0.25)
            invoice.refresh_from_db()
            if invoice.status == "paid":
                break
        self.stdout.write(f"invoice {invoice.id}: {invoice.status}")
