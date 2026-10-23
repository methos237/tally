"""manage.py partner_report --date 2026-10-22 [--tenant 1] [--notify]

Writes one CSV per tenant to the reports bucket; with --notify also queues a
report.ready webhook per tenant. Airflow's DAG calls exactly this.
"""

from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from tally.adapters import reports
from tally.adapters.models import Tenant


class Command(BaseCommand):
    help = "Write the partner daily report CSV per tenant to the S3 bucket."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--date", type=date.fromisoformat, required=True)
        parser.add_argument("--tenant", type=int, help="one tenant id; default all")
        parser.add_argument("--notify", action="store_true", help="queue report.ready webhooks")

    def handle(self, *args: Any, **options: Any) -> None:
        tenants = Tenant.objects.order_by("id")
        if options["tenant"]:
            tenants = tenants.filter(id=options["tenant"])
        for tenant in tenants:
            key = reports.write(tenant, options["date"])
            if options["notify"]:
                reports.notify_ready(tenant, options["date"])
            self.stdout.write(key)
