from datetime import timedelta

from celery import shared_task
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

from tally.adapters import billing
from tally.adapters.models import IdempotencyRecord, Subscription
from tally.domain.billing import SubscriptionStatus

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
            billing.issue_invoice(subscription, now)
        except IntegrityError:
            continue  # an overlapping run already invoiced this period
        issued += 1
    return issued
