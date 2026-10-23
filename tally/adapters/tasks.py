from datetime import timedelta

import stripe
from celery import shared_task
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from tally.adapters import billing, outbox, stripe_gateway
from tally.adapters.models import (
    IdempotencyRecord,
    Invoice,
    OutboxMessage,
    StripeEvent,
    Subscription,
)
from tally.domain.billing import InvoiceStatus, SubscriptionStatus

IDEMPOTENCY_TTL = timedelta(hours=24)


@shared_task
def expire_idempotency() -> int:
    """Delete idempotency records older than the TTL. Returns rows deleted."""
    cutoff = timezone.now() - IDEMPOTENCY_TTL
    deleted, _ = IdempotencyRecord.objects.filter(created_at__lt=cutoff).delete()
    return deleted


@shared_task
def bill_due_subscriptions() -> int:
    """Invoice every active or past-due subscription whose paid-through date has passed.
    One period per run; a subscription several periods behind catches up a minute at a
    time. Returns invoices issued."""
    now = timezone.now()
    due = (
        Subscription.objects.filter(
            status__in=[SubscriptionStatus.ACTIVE.value, SubscriptionStatus.PAST_DUE.value]
        )
        .filter(Q(billed_through__isnull=True) | Q(billed_through__lte=now))
        .select_related("plan")
    )
    issued = 0
    for subscription in due:
        try:
            invoice = billing.issue_invoice(subscription, now)
        except IntegrityError as exc:
            if "uq_invoice_subscription_period" not in str(exc):
                raise
            continue  # an overlapping run already invoiced this period
        issued += 1
        collect_invoice.delay(invoice.id)
    return issued


@shared_task
def collect_invoice(invoice_id: int) -> str:
    """Charge an open invoice through Stripe. Returns the PaymentIntent status; the
    webhook, not this task, marks the invoice paid or the subscription past due."""
    invoice = Invoice.objects.select_related("subscription__customer").get(id=invoice_id)
    if invoice.status != InvoiceStatus.OPEN:
        return invoice.status
    try:
        return stripe_gateway.collect(invoice).status
    except stripe.CardError as exc:
        return exc.code or "card_declined"  # Stripe also sends payment_intent.payment_failed


@shared_task
def process_stripe_event(row_id: int) -> str:
    """Apply one verified, deduplicated Stripe event. Returns what was done."""
    row = StripeEvent.objects.get(id=row_id)
    if row.processed_at is not None:
        return "already processed"
    intent_id = row.payload["data"]["object"]["id"]
    invoice = Invoice.objects.filter(stripe_payment_intent_id=intent_id).first()
    if invoice is None:
        outcome = f"no invoice for {intent_id}"  # e.g. a `stripe trigger` fixture; nothing to book
    elif row.type == "payment_intent.succeeded":
        billing.mark_paid(invoice.id, timezone.now())
        outcome = f"invoice {invoice.id} paid"
    elif row.type == "payment_intent.payment_failed":
        billing.mark_failed(invoice.id)
        outcome = f"invoice {invoice.id} payment failed"
    else:
        outcome = f"ignored {row.type}"
    row.processed_at = timezone.now()
    row.save(update_fields=["processed_at"])
    return outcome


@shared_task
def deliver_due_webhooks() -> int:
    """Fan out every outbox message whose time has come. Returns messages dispatched."""
    due = OutboxMessage.objects.filter(
        delivered_at__isnull=True, dead_at__isnull=True, next_attempt_at__lte=timezone.now()
    ).values_list("id", flat=True)
    for message_id in due:
        deliver_webhook.delay(message_id)
    return len(due)


@shared_task
def deliver_webhook(message_id: int) -> bool:
    """One delivery attempt under a row lock, so overlapping sweeps never double-post."""
    with transaction.atomic():
        message = (
            OutboxMessage.objects.select_for_update(skip_locked=True)
            .select_related("endpoint")
            .filter(
                id=message_id,
                delivered_at__isnull=True,
                dead_at__isnull=True,
                next_attempt_at__lte=timezone.now(),
            )
            .first()
        )
        return message is not None and outbox.attempt(message)
