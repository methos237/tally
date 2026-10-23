from datetime import UTC, datetime

import pytest
from django.conf import settings
from freezegun import freeze_time

from tally.adapters.models import Invoice, Subscription
from tally.adapters.tasks import bill_due_subscriptions


def test_beat_runs_billing_every_minute() -> None:
    entry = settings.CELERY_BEAT_SCHEDULE["bill-due-subscriptions"]
    assert entry == {"task": "tally.adapters.tasks.bill_due_subscriptions", "schedule": 60}


@pytest.mark.django_db
def test_a_due_subscription_is_invoiced_once_per_period(subscription: Subscription) -> None:
    with freeze_time("2026-02-01 09:00:00"):
        assert bill_due_subscriptions() == 1
        assert bill_due_subscriptions() == 0  # same minute again: nothing due
    with freeze_time("2026-02-27 23:59:00"):
        assert bill_due_subscriptions() == 0  # paid through the 28th
    with freeze_time("2026-02-28 00:00:00"):
        assert bill_due_subscriptions() == 1

    periods = list(Invoice.objects.order_by("period_start").values_list("period_start", flat=True))
    assert periods == [datetime(2026, 1, 31, tzinfo=UTC), datetime(2026, 2, 28, tzinfo=UTC)]
    subscription.refresh_from_db()
    assert subscription.billed_through == datetime(2026, 3, 28, tzinfo=UTC)


@pytest.mark.django_db
def test_canceled_subscriptions_are_not_billed(subscription: Subscription) -> None:
    subscription.status = "canceled"
    subscription.save()
    with freeze_time("2026-02-01"):
        assert bill_due_subscriptions() == 0
    assert Invoice.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_a_lost_advance_is_caught_by_the_unique_constraint(subscription: Subscription) -> None:
    with freeze_time("2026-02-01"):
        bill_due_subscriptions()
        Subscription.objects.update(billed_through=None)  # simulate the advance being lost
        assert bill_due_subscriptions() == 0
    assert Invoice.objects.count() == 1
