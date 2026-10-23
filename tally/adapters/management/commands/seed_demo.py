"""Deterministic demo data: two tenants, a 12-account chart each, 400 entries over 90 days,
3 plans, 10 customers and a dozen subscriptions per tenant invoiced through the demo date,
and one bank statement per tenant that reconciles with exactly three exceptions.

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

from tally.adapters import billing, reconciliation
from tally.adapters.models import Account, Customer, Plan, Subscription, Tenant
from tally.adapters.models import JournalEntry as JournalEntryRow
from tally.adapters.repositories import DjangoJournalRepository
from tally.application.journal import PostEntry
from tally.domain.journal import JournalEntry, Line
from tally.domain.money import Currency, Money

TENANTS = ["Acme Corp", "Globex"]
START = datetime(2026, 7, 24, tzinfo=UTC)  # 90 days before the demo date
DAYS = 90
ENTRIES = 400
DEMO_DATE = START + timedelta(days=DAYS)
PLANS = [
    ("starter", "Starter", "19.00", "month"),
    ("pro", "Pro", "49.00", "month"),
    ("scale", "Scale", "499.00", "year"),
]
CUSTOMERS = 10
SUBSCRIPTIONS = {"Acme Corp": 13, "Globex": 12}

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
                invoices, paid = self.seed_billing(tenant, SUBSCRIPTIONS[name], rng)
                exceptions = self.seed_statement(tenant)
            self.stdout.write(
                f"{name}: {len(CHART)} accounts, {ENTRIES + 1} entries, "
                f"{invoices} invoices ({paid} paid), 1 statement ({exceptions} exceptions)"
            )

    def seed_billing(self, tenant: Tenant, count: int, rng: random.Random) -> tuple[int, int]:
        """Subscriptions started over the 90 days, every elapsed period invoiced; most
        invoices paid, a few left open, one failed so a past_due subscription exists."""
        plans = [
            Plan.objects.create(
                tenant=tenant,
                code=code,
                name=label,
                amount=Decimal(amount),
                currency="USD",
                interval=interval,
            )
            for code, label, amount, interval in PLANS
        ]
        customers = [
            Customer.objects.create(
                tenant=tenant,
                name=f"Customer {n:02d}",
                email=f"billing{n:02d}@{tenant.name.split()[0].lower()}.test",
            )
            for n in range(1, CUSTOMERS + 1)
        ]
        invoices = paid = 0
        for n in range(count):
            started = START + timedelta(days=rng.randint(0, DAYS - 1), hours=rng.randint(8, 18))
            subscription = Subscription.objects.create(
                tenant=tenant,
                customer=rng.choice(customers),
                plan=rng.choice(plans),
                started_at=started,
            )
            while (subscription.billed_through or started) <= DEMO_DATE:
                invoice = billing.issue_invoice(
                    subscription, subscription.billed_through or started
                )
                invoices += 1
                if n == 0 and invoice.period_end > DEMO_DATE:
                    billing.mark_failed(invoice.id)  # the one past_due subscription
                elif rng.random() < 0.85 or invoice.period_end <= DEMO_DATE:
                    billing.mark_paid(
                        invoice.id, invoice.issued_at + timedelta(days=rng.randint(0, 3))
                    )
                    paid += 1
        return invoices, paid

    def seed_statement(self, tenant: Tenant) -> int:
        """A bank statement for the last week: every payment in the ledger, plus three
        deliberate exceptions. Reconciled on the spot so the exceptions are visible."""
        week = DEMO_DATE - timedelta(days=7)
        payments = (
            JournalEntryRow.objects.filter(
                tenant=tenant,
                source_type="payment",
                occurred_at__gte=week,
                occurred_at__lte=DEMO_DATE,
            )
            .prefetch_related("lines__account")
            .order_by("occurred_at", "id")
        )
        rows = ["Date,Description,Reference,Amount"]
        last: JournalEntryRow | None = None
        for entry in payments:
            cash = next(line for line in entry.lines.all() if line.account.code == "1000")
            rows.append(
                f"{entry.occurred_at:%Y-%m-%d},Card settlement,{entry.source_id},{cash.amount:.2f}"
            )
            last = entry
        assert last is not None, "the billing seed left no payments in the last week"
        day = f"{DEMO_DATE:%Y-%m-%d}"
        # 1. a fee the ledger never saw; 2. a deposit with no counterpart; 3. the last
        # payment one cent off instead of exact, so its reference matches but the amount does not
        exact = rows.pop()
        off_by_one = Decimal(exact.rsplit(",", 1)[1]) + Decimal("0.01")
        rows += [
            f"{day},Monthly account fee,FEE-{DEMO_DATE:%Y%m},-12.50",
            f"{day},Unidentified deposit,,777.77",
            f"{last.occurred_at:%Y-%m-%d},Card settlement,{last.source_id},{off_by_one:.2f}",
        ]
        statement = reconciliation.import_statement(tenant.id, "\n".join(rows) + "\n")
        reconciliation.reconcile(statement, DEMO_DATE)
        return statement.exceptions.count()
