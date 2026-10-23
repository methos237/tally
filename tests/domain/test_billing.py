from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tally.domain.billing import (
    TRANSITIONS,
    Event,
    Interval,
    InvalidTransition,
    SubscriptionStatus,
    add_interval,
    invoice_issued,
    invoice_paid,
    transition,
)
from tally.domain.journal import post
from tally.domain.money import Currency, Money
from tests.domain.strategies import NOW, TENANT, chart

statuses = st.sampled_from(list(SubscriptionStatus))
events = st.sampled_from(list(Event))


@given(statuses, events)
def test_every_transition_is_in_the_table_or_rejected(
    status: SubscriptionStatus, event: Event
) -> None:
    if (status, event) in TRANSITIONS:
        assert transition(status, event) is TRANSITIONS[(status, event)]
    else:
        with pytest.raises(InvalidTransition):
            transition(status, event)


def test_canceled_is_terminal() -> None:
    assert not any(status is SubscriptionStatus.CANCELED for status, _ in TRANSITIONS)


def test_failed_payment_moves_active_to_past_due_and_success_restores_it() -> None:
    past_due = transition(SubscriptionStatus.ACTIVE, Event.PAYMENT_FAILED)
    assert past_due is SubscriptionStatus.PAST_DUE
    assert transition(past_due, Event.PAYMENT_SUCCEEDED) is SubscriptionStatus.ACTIVE


@pytest.mark.parametrize(
    ("start", "interval", "expected"),
    [
        ("2026-01-31", Interval.MONTH, "2026-02-28"),
        ("2028-01-31", Interval.MONTH, "2028-02-29"),
        ("2026-12-15", Interval.MONTH, "2027-01-15"),
        ("2028-02-29", Interval.YEAR, "2029-02-28"),
        ("2026-10-23", Interval.YEAR, "2027-10-23"),
    ],
)
def test_add_interval_clamps_to_month_end(start: str, interval: Interval, expected: str) -> None:
    got = add_interval(datetime.fromisoformat(start).replace(tzinfo=UTC), interval)
    assert got.date().isoformat() == expected


@given(
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2099, 1, 1)),
    st.sampled_from(list(Interval)),
)
def test_add_interval_always_moves_forward_by_one_period(
    start: datetime, interval: Interval
) -> None:
    end = add_interval(start, interval)
    months = 12 if interval is Interval.YEAR else 1
    assert (end.year * 12 + end.month) - (start.year * 12 + start.month) == months
    assert end.day <= start.day


@given(
    st.decimals(min_value=Decimal("0.01"), max_value=Decimal("1e9"), places=2),
    st.sampled_from(list(Currency)),
)
def test_both_invoice_postings_balance(amount: Decimal, currency: Currency) -> None:
    accounts = chart(currency, size=3)
    ids = list(accounts)
    money = Money(amount, currency)
    issued = invoice_issued(TENANT, 7, NOW, money, ids[0], ids[1])
    paid = invoice_paid(TENANT, 7, NOW, money, ids[2], ids[0])
    assert post(issued, accounts) is issued
    assert post(paid, accounts) is paid
    assert (issued.source_type, issued.source_id) == ("invoice", "7")
    assert (paid.source_type, paid.source_id) == ("payment", "7")
    # receivable goes up on issue and back down on payment
    assert issued.lines[0].amount + paid.lines[1].amount == Money.zero(currency)
