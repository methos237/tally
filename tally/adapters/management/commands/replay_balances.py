from typing import Any

from django.core.management.base import BaseCommand

from tally.adapters import projections


class Command(BaseCommand):
    help = "Rebuild account_balances from the journal."

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(f"account_balances rebuilt: {projections.replay()} accounts")
