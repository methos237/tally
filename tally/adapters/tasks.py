from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from tally.adapters.models import IdempotencyRecord

IDEMPOTENCY_TTL = timedelta(hours=24)


@shared_task
def expire_idempotency() -> int:
    """Delete idempotency records older than the TTL. Returns rows deleted."""
    cutoff = timezone.now() - IDEMPOTENCY_TTL
    deleted, _ = IdempotencyRecord.objects.filter(created_at__lt=cutoff).delete()
    return deleted
