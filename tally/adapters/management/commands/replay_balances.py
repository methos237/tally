from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from tally.adapters import projections


class Command(BaseCommand):
    help = "Rebuild account_balances from the journal."

    def handle(self, *args: Any, **options: Any) -> None:
        with transaction.atomic():
            rows = projections.replay()
        self.stdout.write(f"account_balances rebuilt: {rows} accounts")
