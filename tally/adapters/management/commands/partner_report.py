"""manage.py partner_report --date 2026-10-22 [--tenant 1] [--notify]

Writes one CSV per tenant to the reports bucket; with --notify also queues a
report.ready webhook per tenant. The local and backfill entry point; the Airflow DAG
does the same work through POST /internal/reports/{day}.
"""

from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from tally.adapters import reports


class Command(BaseCommand):
    help = "Write the partner daily report CSV per tenant to the S3 bucket."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--date", type=date.fromisoformat, required=True)
        parser.add_argument("--tenant", type=int, help="one tenant id; default all")
        parser.add_argument("--notify", action="store_true", help="queue report.ready webhooks")

    def handle(self, *args: Any, **options: Any) -> None:
        for key in reports.write_all(options["date"], options["tenant"]):
            self.stdout.write(key)
        if options["notify"]:
            reports.notify_all(options["date"], options["tenant"])
