from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError

from tally.adapters import billing
from tally.adapters.models import Account, Invoice, JournalEntry, Subscription
from tests.conftest import fold_from_journal

NOW = datetime(2026, 2, 1, 9, tzinfo=UTC)


def balance(tenant_id: int, code: str) -> Decimal:
    account = Account.objects.get(tenant_id=tenant_id, code=code)
    return fold_from_journal(account.tenant).get(account.id, Decimal(0))


@pytest.mark.django_db
def test_issue_invoice_posts_receivable_against_revenue_and_advances_the_period(
    subscription: Subscription,
) -> None:
    invoice = billing.issue_invoice(subscription, NOW)

    assert invoice.status == "open"
    assert (invoice.period_start, invoice.period_end) == (
        datetime(2026, 1, 31, tzinfo=UTC),
        datetime(2026, 2, 28, tzinfo=UTC),
    )
    assert invoice.lines.count() == 1
    assert invoice.issue_entry is not None
    assert (invoice.issue_entry.source_type, invoice.issue_entry.source_id) == (
        "invoice",
        str(invoice.id),
    )
    assert balance(subscription.tenant_id, "1200") == Decimal("49")
    assert balance(subscription.tenant_id, "4000") == Decimal("-49")
    subscription.refresh_from_db()
    assert subscription.billed_through == invoice.period_end


@pytest.mark.django_db(transaction=True)
def test_same_period_cannot_be_invoiced_twice(subscription: Subscription) -> None:
    billing.issue_invoice(subscription, NOW)
    subscription.billed_through = None  # pretend the advance was lost: a rerun of the same period
    with pytest.raises(IntegrityError):
        billing.issue_invoice(subscription, NOW)
    assert Invoice.objects.count() == 1
    assert JournalEntry.objects.count() == 1  # the constraint fires before anything is posted


@pytest.mark.django_db
def test_mark_paid_posts_cash_against_receivable_once_and_reactivates(
    subscription: Subscription,
) -> None:
    invoice = billing.issue_invoice(subscription, NOW)
    billing.mark_failed(invoice.id)
    subscription.refresh_from_db()
    assert subscription.status == "past_due"

    paid = billing.mark_paid(invoice.id, NOW)
    again = billing.mark_paid(invoice.id, NOW)

    assert paid.status == again.status == "paid"
    assert paid.paid_at == NOW
    assert JournalEntry.objects.filter(source_type="payment").count() == 1
    assert balance(subscription.tenant_id, "1200") == Decimal(0)
    assert balance(subscription.tenant_id, "1000") == Decimal("49")
    subscription.refresh_from_db()
    assert subscription.status == "active"


@pytest.mark.django_db
def test_payment_on_a_canceled_subscription_is_recorded_but_does_not_revive_it(
    subscription: Subscription,
) -> None:
    invoice = billing.issue_invoice(subscription, NOW)
    subscription.status = "canceled"
    subscription.save()
    billing.mark_paid(invoice.id, NOW)
    subscription.refresh_from_db()
    assert subscription.status == "canceled"
    assert balance(subscription.tenant_id, "1000") == Decimal("49")


@pytest.mark.django_db
def test_tenant_without_billing_accounts_is_refused_before_anything_is_written(
    subscription: Subscription,
) -> None:
    Account.objects.filter(code="4000").delete()
    with pytest.raises(billing.MissingAccount):
        billing.issue_invoice(subscription, NOW)
    assert Invoice.objects.count() == 0
