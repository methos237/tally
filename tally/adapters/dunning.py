"""Dunning as a Temporal workflow: what happens after a payment fails.

One workflow per unpaid invoice, started when the subscription goes past_due. It waits,
checks whether the invoice got paid in the meantime (the Stripe webhook marks it), retries
collection, and after the last step cancels the subscription. Temporal keeps the timers
and retries durable across worker restarts; Celery Beat no longer owns this flow.

The workflow itself is in dunning_workflow.py (sandboxed, no Django); this module holds
the activities, the start call and the worker.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from temporalio import activity
from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from tally.adapters import billing, stripe_gateway
from tally.adapters.dunning_workflow import SCHEDULE, TASK_QUEUE, DunningWorkflow
from tally.adapters.models import Invoice
from tally.domain.billing import Event, InvoiceStatus

__all__ = ["SCHEDULE", "TASK_QUEUE", "DunningWorkflow", "start", "start_async", "run_worker"]

# tally/__init__.py imports the Celery app, so a sandboxed re-import of any tally module
# would pull Django in; pass the package through and let the sandbox restrict calls only.
WORKFLOW_RUNNER = SandboxedWorkflowRunner(
    restrictions=SandboxRestrictions.default.with_passthrough_modules("tally")
)


@activity.defn
def invoice_is_paid(invoice_id: int) -> bool:
    return Invoice.objects.get(id=invoice_id).status == InvoiceStatus.PAID


@activity.defn
def retry_collection(invoice_id: int) -> str:
    """Another PaymentIntent for the same invoice; the webhook books the outcome."""
    invoice = Invoice.objects.select_related("subscription__customer").get(id=invoice_id)
    return stripe_gateway.collect(invoice).status


@activity.defn
def cancel_subscription(invoice_id: int) -> None:
    invoice = Invoice.objects.get(id=invoice_id)
    billing.apply_to_subscription(invoice.subscription_id, Event.CANCEL)


ACTIVITIES = [invoice_is_paid, retry_collection, cancel_subscription]


def workflow_id(invoice_id: int) -> str:
    return f"dunning-invoice-{invoice_id}"


async def start_async(client: Client, invoice_id: int) -> WorkflowHandle[DunningWorkflow, str]:
    return await client.start_workflow(
        DunningWorkflow.run, invoice_id, id=workflow_id(invoice_id), task_queue=TASK_QUEUE
    )


def start(invoice_id: int) -> bool:
    """Start dunning for an unpaid invoice from sync code. Idempotent on the workflow id;
    a no-op (False) when TEMPORAL_ADDRESS is unset."""
    if not settings.TEMPORAL_ADDRESS:
        return False

    async def go() -> bool:
        client = await Client.connect(settings.TEMPORAL_ADDRESS)
        try:
            await start_async(client, invoice_id)
        except WorkflowAlreadyStartedError:
            return False
        return True

    return asyncio.run(go())


async def run_worker(client: Client) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        async with Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[DunningWorkflow],
            activities=ACTIVITIES,
            activity_executor=executor,
            workflow_runner=WORKFLOW_RUNNER,
        ):
            await asyncio.Event().wait()  # until the process is stopped
