"""Statements over the ORM: parse the CSV, run the domain matcher against the cash
account, record matches and exceptions, resolve exceptions.

Two CSV layouts, told apart by their header:
    bank:       Date,Description,Reference,Amount          (signed amount, one currency per tenant)
    processor:  id,created,amount,currency,description     (Stripe balance-transaction style)
"""

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from django.db import transaction

from tally.adapters import billing, models, outbox
from tally.adapters.repositories import DjangoJournalRepository
from tally.application.journal import PostEntry
from tally.domain.journal import JournalEntry, Line
from tally.domain.money import Currency, Money
from tally.domain.reconciliation import WINDOW_DAYS, LedgerItem, StatementLine, match

BANK = {"Date", "Description", "Reference", "Amount"}
PROCESSOR = {"id", "created", "amount", "currency", "description"}


class BadStatement(ValueError):
    pass


class Row(NamedTuple):
    occurred_on: date
    amount: Decimal
    currency: str
    reference: str
    description: str


def parse(text: str, default_currency: str) -> tuple[str, list[Row]]:
    """(source, rows); `default_currency` applies to the bank layout, which has none."""
    reader = csv.DictReader(io.StringIO(text))
    header = set(reader.fieldnames or [])
    if header >= BANK:
        source, on, amount, reference, description, currency = (
            "bank",
            "Date",
            "Amount",
            "Reference",
            "Description",
            "",
        )
    elif header >= PROCESSOR:
        source, on, amount, reference, description, currency = (
            "processor",
            "created",
            "amount",
            "id",
            "description",
            "currency",
        )
    else:
        raise BadStatement(f"unknown CSV layout: columns {sorted(header)}")
    rows: list[Row] = []
    for n, raw in enumerate(reader, start=1):
        try:
            rows.append(
                Row(
                    date.fromisoformat(raw[on].strip()[:10]),
                    Decimal(raw[amount].strip()),
                    raw[currency].strip().upper() if currency else default_currency,
                    raw[reference].strip(),
                    raw[description].strip(),
                )
            )
        except (KeyError, ValueError, InvalidOperation, AttributeError) as exc:
            raise BadStatement(f"line {n}: {exc}") from exc
        if rows[-1].currency not in Currency.__members__:
            raise BadStatement(f"line {n}: unknown currency {rows[-1].currency}")
    if not rows:
        raise BadStatement("no lines")
    return source, rows


def import_statement(tenant_id: int, text: str) -> models.Statement:
    cash = models.Account.objects.get(tenant_id=tenant_id, code=billing.CASH)
    source, rows = parse(text, cash.currency)
    with transaction.atomic():
        statement = models.Statement.objects.create(
            tenant_id=tenant_id,
            source=source,
            period_start=min(r.occurred_on for r in rows),
            period_end=max(r.occurred_on for r in rows),
        )
        models.StatementLine.objects.bulk_create(
            models.StatementLine(
                tenant_id=tenant_id, statement=statement, line_no=n, **row._asdict()
            )
            for n, row in enumerate(rows, start=1)
        )
    return statement


def ledger_items(statement: models.Statement) -> tuple[LedgerItem, ...]:
    """Cash movements in the statement window not yet matched by any statement line.
    References: the entry's source id plus, for payments, the Stripe intent id."""
    window = timedelta(days=WINDOW_DAYS)
    lines = (
        models.JournalLine.objects.filter(
            tenant_id=statement.tenant_id,
            account__code=billing.CASH,
            entry__occurred_at__date__gte=statement.period_start - window,
            entry__occurred_at__date__lte=statement.period_end + window,
        )
        .exclude(
            entry_id__in=models.StatementLine.objects.filter(
                tenant_id=statement.tenant_id, matched_entry__isnull=False
            ).values("matched_entry_id")
        )
        .select_related("entry")
    )
    payment_ids = [line.entry.source_id for line in lines if line.entry.source_type == "payment"]
    intents: dict[str, str] = {
        str(invoice_id): str(intent)
        for invoice_id, intent in models.Invoice.objects.filter(
            tenant_id=statement.tenant_id,
            id__in=payment_ids,
            stripe_payment_intent_id__isnull=False,
        ).values_list("id", "stripe_payment_intent_id")
    }
    items = []
    for line in lines:
        refs = {line.entry.source_id}
        if line.entry.source_type == "payment" and line.entry.source_id in intents:
            refs.add(intents[line.entry.source_id])
        items.append(
            LedgerItem(
                line.entry_id,
                line.entry.occurred_at.date(),
                Money(line.amount, Currency(line.currency)),
                frozenset(refs),
            )
        )
    return tuple(items)


def reconcile(statement: models.Statement, now: datetime) -> models.Statement:
    """Match every unplaced line; one exception row per failure; publish each exception.
    Re-running only touches lines that are still unplaced."""
    with transaction.atomic():
        pending = statement.lines.filter(matched_entry__isnull=True, exception__isnull=True)
        domain_lines = tuple(
            StatementLine(
                row.id, row.occurred_on, Money(row.amount, Currency(row.currency)), row.reference
            )
            for row in pending
        )
        matches, exceptions = match(domain_lines, ledger_items(statement))
        for m in matches:
            models.StatementLine.objects.filter(id=m.line_id).update(
                matched_entry_id=m.entry_id, match_rule=m.rule.value
            )
        for e in exceptions:
            row = models.ReconciliationException.objects.create(
                tenant_id=statement.tenant_id,
                statement=statement,
                line_id=e.line_id,
                reason=e.reason.value,
                difference=e.difference.amount,
                currency=e.difference.currency.value,
                entry_id=e.entry_id,
            )
            outbox.publish(
                statement.tenant_id,
                "reconciliation.exception",
                {
                    "exception_id": row.id,
                    "statement_id": statement.id,
                    "line_id": e.line_id,
                    "reason": row.reason,
                    "difference": row.difference,
                    "currency": row.currency,
                },
            )
        settle(statement, now)
    return statement


def settle(statement: models.Statement, now: datetime) -> None:
    """Stamp reconciled_at once no line is unplaced and no exception is open."""
    open_lines = statement.lines.filter(matched_entry__isnull=True, exception__isnull=True)
    open_exceptions = statement.exceptions.filter(resolved_at__isnull=True)
    statement.reconciled_at = now if not (open_lines.exists() or open_exceptions.exists()) else None
    statement.save(update_fields=["reconciled_at"])


def adjust(exception: models.ReconciliationException, account_code: str, now: datetime) -> None:
    """Resolve by posting the difference: cash against `account_code`."""
    with transaction.atomic():
        accounts = dict(
            models.Account.objects.filter(
                tenant_id=exception.tenant_id, code__in=[billing.CASH, account_code]
            ).values_list("code", "id")
        )
        if account_code not in accounts:
            raise billing.MissingAccount(exception.tenant_id, account_code)
        money = Money(exception.difference, Currency(exception.currency))
        entry = PostEntry(DjangoJournalRepository())(
            JournalEntry(
                exception.tenant_id,
                now,
                "adjustment",
                str(exception.id),
                (Line(accounts[billing.CASH], money), Line(accounts[account_code], -money)),
            )
        )
        exception.resolution, exception.adjusting_entry_id = "adjusted", entry.id
        exception.resolved_at = now
        exception.save(update_fields=["resolution", "adjusting_entry", "resolved_at"])
        settle(exception.statement, now)


def explain(exception: models.ReconciliationException, explanation: str, now: datetime) -> None:
    with transaction.atomic():
        exception.resolution, exception.explanation = "explained", explanation
        exception.resolved_at = now
        exception.save(update_fields=["resolution", "explanation", "resolved_at"])
        settle(exception.statement, now)
