"""The dunning workflow. This module runs inside Temporal's sandbox, so it imports only
the SDK and the standard library; the activities it names live in tally.adapters.dunning."""

from datetime import timedelta

from temporalio import workflow

TASK_QUEUE = "tally-dunning"
# Retry collection three and seven days after the failure; cancel at fourteen.
SCHEDULE = [timedelta(days=3), timedelta(days=4), timedelta(days=7)]
ACTIVITY_TIMEOUT = timedelta(seconds=30)


@workflow.defn
class DunningWorkflow:
    @workflow.run
    async def run(self, invoice_id: int) -> str:
        for step, delay in enumerate(SCHEDULE, start=1):
            await workflow.sleep(delay)
            if await workflow.execute_activity(
                "invoice_is_paid", invoice_id, start_to_close_timeout=ACTIVITY_TIMEOUT
            ):
                return "paid"
            if step < len(SCHEDULE):
                await workflow.execute_activity(
                    "retry_collection", invoice_id, start_to_close_timeout=ACTIVITY_TIMEOUT
                )
        await workflow.execute_activity(
            "cancel_subscription", invoice_id, start_to_close_timeout=ACTIVITY_TIMEOUT
        )
        return "canceled"
