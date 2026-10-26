"""Run the Temporal worker for the dunning workflow (task queue tally-dunning)."""

import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from temporalio.client import Client

from tally.adapters import dunning


class Command(BaseCommand):
    help = "Temporal worker: dunning workflow and its activities."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.TEMPORAL_ADDRESS:
            raise CommandError("TEMPORAL_ADDRESS is not set")

        async def main() -> None:
            client = await Client.connect(settings.TEMPORAL_ADDRESS)
            self.stdout.write(
                f"dunning worker on {settings.TEMPORAL_ADDRESS}, queue {dunning.TASK_QUEUE}"
            )
            await dunning.run_worker(client)

        asyncio.run(main())
