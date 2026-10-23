"""Subscriptions, billing periods and the two invoice postings.

The state machine is a transition table: (status, event) -> status. Anything not
in the table is an InvalidTransition, so every allowed path is visible in one place.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from enum import StrEnum

from tally.domain.journal import JournalEntry, Line
from tally.domain.money import Money


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class InvoiceStatus(StrEnum):
    OPEN = "open"
    PAID = "paid"


class Interval(StrEnum):
    MONTH = "month"
    YEAR = "year"


class Event(StrEnum):
    PAYMENT_SUCCEEDED = "payment_succeeded"
    PAYMENT_FAILED = "payment_failed"
    CANCEL = "cancel"


TRANSITIONS: dict[tuple[SubscriptionStatus, Event], SubscriptionStatus] = {
    (SubscriptionStatus.ACTIVE, Event.PAYMENT_SUCCEEDED): SubscriptionStatus.ACTIVE,
    (SubscriptionStatus.ACTIVE, Event.PAYMENT_FAILED): SubscriptionStatus.PAST_DUE,
    (SubscriptionStatus.ACTIVE, Event.CANCEL): SubscriptionStatus.CANCELED,
    (SubscriptionStatus.PAST_DUE, Event.PAYMENT_SUCCEEDED): SubscriptionStatus.ACTIVE,
    (SubscriptionStatus.PAST_DUE, Event.PAYMENT_FAILED): SubscriptionStatus.PAST_DUE,
    (SubscriptionStatus.PAST_DUE, Event.CANCEL): SubscriptionStatus.CANCELED,
    # Money on a canceled subscription is still booked by the caller; the status stays put.
    (SubscriptionStatus.CANCELED, Event.PAYMENT_SUCCEEDED): SubscriptionStatus.CANCELED,
    (SubscriptionStatus.CANCELED, Event.PAYMENT_FAILED): SubscriptionStatus.CANCELED,
}


class InvalidTransition(ValueError):
    pass


def transition(status: SubscriptionStatus, event: Event) -> SubscriptionStatus:
    try:
        return TRANSITIONS[(status, event)]
    except KeyError:
        raise InvalidTransition(f"a {status} subscription cannot take {event}") from None


def add_interval(start: datetime, interval: Interval) -> datetime:
    """`start` plus one billing interval, clamping the day to the target month's length
    so the 31st bills on the 28th/29th/30th and never skips a month."""
    months = 12 if interval is Interval.YEAR else 1
    year, month = divmod(start.month - 1 + months, 12)
    year, month = start.year + year, month + 1
    day = min(start.day, monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def invoice_issued(
    tenant_id: int,
    invoice_id: int,
    occurred_at: datetime,
    amount: Money,
    receivable_account_id: int,
    revenue_account_id: int,
) -> JournalEntry:
    """Issuing an invoice: debit accounts receivable, credit revenue."""
    return JournalEntry(
        tenant_id,
        occurred_at,
        "invoice",
        str(invoice_id),
        (Line(receivable_account_id, amount), Line(revenue_account_id, -amount)),
    )


def invoice_paid(
    tenant_id: int,
    invoice_id: int,
    occurred_at: datetime,
    amount: Money,
    cash_account_id: int,
    receivable_account_id: int,
) -> JournalEntry:
    """Collecting an invoice: debit cash, credit accounts receivable."""
    return JournalEntry(
        tenant_id,
        occurred_at,
        "payment",
        str(invoice_id),
        (Line(cash_account_id, amount), Line(receivable_account_id, -amount)),
    )
