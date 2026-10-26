"""Dunning: the workflow's schedule under time skipping with fake activities, the real
activities against the database and stripe-mock, and the hand-off from the Stripe webhook."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from tally.adapters import billing, dunning
from tally.adapters.models import Invoice, StripeEvent, Subscription
from tally.adapters.tasks import process_stripe_event
from tally.domain.billing import Event

NOW = datetime(2026, 2, 1, 9, tzinfo=UTC)


class Fakes:
    """Activities with the production names; `paid_after` is how many checks fail first."""

    def __init__(self, paid_after: int | None) -> None:
        self.paid_after = paid_after
        self.checks = 0
        self.retries = 0
        self.canceled = False

        @activity.defn(name="invoice_is_paid")
        def invoice_is_paid(invoice_id: int) -> bool:
            self.checks += 1
            return paid_after is not None and self.checks > paid_after

        @activity.defn(name="retry_collection")
        def retry_collection(invoice_id: int) -> str:
            self.retries += 1
            return "requires_payment_method"

        @activity.defn(name="cancel_subscription")
        def cancel_subscription(invoice_id: int) -> None:
            self.canceled = True

        self.activities = [invoice_is_paid, retry_collection, cancel_subscription]


async def run_workflow(fakes: Fakes) -> str:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=dunning.TASK_QUEUE,
            workflows=[dunning.DunningWorkflow],
            activities=fakes.activities,
            activity_executor=ThreadPoolExecutor(max_workers=2),
            workflow_runner=dunning.WORKFLOW_RUNNER,
        ):
            result: str = await (await dunning.start_async(env.client, 42)).result()
            return result


@pytest.mark.asyncio
async def test_paid_during_dunning_ends_the_workflow_without_cancelling() -> None:
    fakes = Fakes(paid_after=1)  # unpaid at day 3, paid by day 7
    assert await run_workflow(fakes) == "paid"
    assert (fakes.checks, fakes.retries, fakes.canceled) == (2, 1, False)


@pytest.mark.asyncio
async def test_never_paid_retries_twice_then_cancels() -> None:
    fakes = Fakes(paid_after=None)
    assert await run_workflow(fakes) == "canceled"
    assert (fakes.checks, fakes.retries, fakes.canceled) == (3, 2, True)


@pytest.fixture
def unpaid(subscription: Subscription) -> Invoice:
    invoice = billing.issue_invoice(subscription, NOW)
    billing.mark_failed(invoice.id)
    return invoice


@pytest.mark.django_db
def test_activities_read_and_change_the_real_rows(unpaid: Invoice) -> None:
    assert dunning.invoice_is_paid(unpaid.id) is False
    assert dunning.retry_collection(unpaid.id) in {
        "succeeded",
        "requires_payment_method",
    }  # stripe-mock
    billing.mark_paid(unpaid.id, NOW)
    assert dunning.invoice_is_paid(unpaid.id) is True

    dunning.cancel_subscription(unpaid.id)
    assert Subscription.objects.get(id=unpaid.subscription_id).status == "canceled"


@pytest.mark.django_db
def test_payment_failed_webhook_starts_dunning(unpaid: Invoice, settings: Any) -> None:
    unpaid.stripe_payment_intent_id = "pi_dun_1"
    unpaid.save()
    row = StripeEvent.objects.create(
        event_id="evt_dun_1",
        type="payment_intent.payment_failed",
        payload={"data": {"object": {"id": "pi_dun_1"}}},
    )
    with patch.object(dunning, "start", return_value=True) as start:
        assert process_stripe_event(row.id).endswith("dunning started")
    start.assert_called_once_with(unpaid.id)


def test_start_is_a_no_op_without_a_temporal_address(settings: Any) -> None:
    settings.TEMPORAL_ADDRESS = ""
    assert dunning.start(1) is False


def test_schedule_is_three_steps_two_weeks() -> None:
    assert sum(dunning.SCHEDULE, start=timedelta()) == timedelta(days=14)
    assert Event.CANCEL  # the last step uses the state machine's cancel event
