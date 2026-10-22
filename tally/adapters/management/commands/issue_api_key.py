from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from tally.adapters.models import ApiKey, Tenant


class Command(BaseCommand):
    help = "Issue an API key for a tenant. The key is printed once and never stored."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="tenant name")
        parser.add_argument("--name", default="default", help="label for this key")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.get(name=options["tenant"])
        _, plaintext = ApiKey.issue(tenant, options["name"])
        self.stdout.write(plaintext)
