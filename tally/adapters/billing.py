"""Billing over the ORM: issue an invoice, record its payment or failure.

Each step is one transaction. The unique (subscription, period_start) constraint is hit
before anything is posted, so a concurrent or repeated run of the billing task cannot
double-bill; `mark_paid` re-reads under lock and is a no-op on a paid invoice.
"""

from datetime import datetime

from django.db import transaction

from tally.adapters import models
from tally.adapters.repositories import DjangoJournalRepository
from tally.application.journal import PostEntry
from tally.domain.billing import (
    Event,
    Interval,
    InvalidTransition,
    InvoiceStatus,
    add_interval,
    invoice_issued,
    invoice_paid,
)
from tally.domain.money import Currency, Money

CASH, RECEIVABLE, REVENUE = "1000", "1200", "4000"


class MissingAccount(LookupError):
    def __init__(self, tenant_id: int, code: str) -> None:
        super().__init__(
            f"tenant {tenant_id} has no account {code}; "
            f"billing needs {CASH}, {RECEIVABLE} and {REVENUE}"
        )


def account_ids(tenant_id: int) -> dict[str, int]:
    found = dict(
        models.Account.objects.filter(
            tenant_id=tenant_id, code__in=[CASH, RECEIVABLE, REVENUE]
        ).values_list("code", "id")
    )
    for code in (CASH, RECEIVABLE, REVENUE):
        if code not in found:
            raise MissingAccount(tenant_id, code)
    return found


def issue_invoice(subscription: models.Subscription, now: datetime) -> models.Invoice:
    """Invoice the subscription's next period and post AR debit / revenue credit."""
    plan = subscription.plan
    start = subscription.billed_through or subscription.started_at
    end = add_interval(start, Interval(plan.interval))
    money = Money(plan.amount, Currency(plan.currency))
    with transaction.atomic():
        invoice = models.Invoice.objects.create(
            tenant_id=subscription.tenant_id,
            subscription=subscription,
            customer_id=subscription.customer_id,
            period_start=start,
            period_end=end,
            amount=money.amount,
            currency=money.currency.value,
            issued_at=now,
        )
        models.InvoiceLine.objects.create(
            invoice=invoice,
            description=f"{plan.name} {start:%Y-%m-%d} to {end:%Y-%m-%d}",
            amount=money.amount,
            currency=money.currency.value,
        )
        accounts = account_ids(subscription.tenant_id)
        entry = PostEntry(DjangoJournalRepository())(
            invoice_issued(
                subscription.tenant_id,
                invoice.id,
                now,
                money,
                accounts[RECEIVABLE],
                accounts[REVENUE],
            )
        )
        invoice.issue_entry_id = entry.id
        invoice.save(update_fields=["issue_entry"])
        subscription.billed_through = end
        subscription.save(update_fields=["billed_through"])
    return invoice


def mark_paid(invoice_id: int, now: datetime) -> models.Invoice:
    """Post cash debit / AR credit and reactivate the subscription. Idempotent."""
    with transaction.atomic():
        invoice = models.Invoice.objects.select_for_update().get(id=invoice_id)
        if invoice.status == InvoiceStatus.PAID:
            return invoice
        accounts = account_ids(invoice.tenant_id)
        entry = PostEntry(DjangoJournalRepository())(
            invoice_paid(
                invoice.tenant_id,
                invoice.id,
                now,
                Money(invoice.amount, Currency(invoice.currency)),
                accounts[CASH],
                accounts[RECEIVABLE],
            )
        )
        invoice.status = InvoiceStatus.PAID.value
        invoice.paid_at = now
        invoice.payment_entry_id = entry.id
        invoice.save(update_fields=["status", "paid_at", "payment_entry"])
        apply_to_subscription(invoice.subscription_id, Event.PAYMENT_SUCCEEDED)
    return invoice


def mark_failed(invoice_id: int) -> None:
    invoice = models.Invoice.objects.get(id=invoice_id)
    apply_to_subscription(invoice.subscription_id, Event.PAYMENT_FAILED)


def apply_to_subscription(subscription_id: int, event: Event) -> None:
    """Advance the subscription if the table allows it. Money is already recorded by the
    caller; a canceled subscription simply stays canceled."""
    with transaction.atomic():
        subscription = models.Subscription.objects.select_for_update().get(id=subscription_id)
        try:
            subscription.apply(event)
        except InvalidTransition:
            return
        subscription.save(update_fields=["status"])
