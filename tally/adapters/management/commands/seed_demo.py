"""Deterministic demo data: two tenants, a 12-account chart each, 400 entries over 90 days.

Everything goes through PostEntry, so the projection is exercised the same way
the API will exercise it. Re-running is a no-op once the tenants exist; the
journal is append-only, so there is nothing to reset short of dropping the DB.
"""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from tally.adapters.models import Account, Tenant
from tally.adapters.repositories import DjangoJournalRepository
from tally.application.journal import PostEntry
from tally.domain.journal import JournalEntry, Line
from tally.domain.money import Currency, Money

TENANTS = ["Acme Corp", "Globex"]
START = datetime(2026, 7, 24, tzinfo=UTC)  # 90 days before the demo date
DAYS = 90
ENTRIES = 400

CHART = [
    ("1000", "Cash", "asset"),
    ("1200", "Accounts receivable", "asset"),
    ("1500", "Prepaid expenses", "asset"),
    ("2000", "Accounts payable", "liability"),
    ("2100", "Deferred revenue", "liability"),
    ("2200", "Taxes payable", "liability"),
    ("3000", "Owner equity", "equity"),
    ("4000", "Subscription revenue", "revenue"),
    ("4100", "Usage revenue", "revenue"),
    ("5000", "Cost of goods sold", "expense"),
    ("6000", "Operating expenses", "expense"),
    ("6100", "Payment processing fees", "expense"),
]

# (source_type, debit account, credit account, min, max) in whole currency units
PATTERNS = [
    ("invoice", "1200", "4000", 49, 2_000),
    ("usage", "1200", "4100", 5, 400),
    ("payment", "1000", "1200", 49, 2_000),
    ("fee", "6100", "1000", 1, 60),
    ("expense", "6000", "1000", 20, 1_500),
    ("prepaid", "1500", "1000", 100, 1_200),
    ("bill", "5000", "2000", 50, 900),
]


class Command(BaseCommand):
    help = "Seed two demo tenants with a chart of accounts and 90 days of entries."

    def handle(self, *args: Any, **options: Any) -> None:
        if Tenant.objects.filter(name__in=TENANTS).exists():
            self.stdout.write("demo tenants already exist; nothing to do")
            return
        rng = random.Random(20261022)
        post = PostEntry(DjangoJournalRepository())
        for name in TENANTS:
            with transaction.atomic():
                tenant = Tenant.objects.create(name=name)
                accounts = {
                    code: Account.objects.create(
                        tenant=tenant, code=code, name=label, type=type_, currency="USD"
                    )
                    for code, label, type_ in CHART
                }
                opening = JournalEntry(
                    tenant.id,
                    START,
                    "opening",
                    "1",
                    (
                        Line(accounts["1000"].id, Money(Decimal(50_000), Currency.USD)),
                        Line(accounts["3000"].id, Money(Decimal(-50_000), Currency.USD)),
                    ),
                )
                post(opening)
                for n in range(ENTRIES):
                    source, debit, credit, low, high = rng.choice(PATTERNS)
                    amount = Decimal(rng.randint(low * 100, high * 100)) / 100
                    occurred = START + timedelta(minutes=rng.randint(0, DAYS * 24 * 60))
                    post(
                        JournalEntry(
                            tenant.id,
                            occurred,
                            source,
                            f"{source}_{n + 1:04d}",
                            (
                                Line(accounts[debit].id, Money(amount, Currency.USD)),
                                Line(accounts[credit].id, Money(-amount, Currency.USD)),
                            ),
                        )
                    )
            self.stdout.write(f"{name}: {len(CHART)} accounts, {ENTRIES + 1} entries")
