from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given

from tally.domain.journal import (
    Account,
    AccountType,
    JournalEntry,
    Line,
    SingleLineEntry,
    UnbalancedEntry,
    UnknownAccount,
    ZeroLine,
    post,
    reversal_of,
)
from tally.domain.money import Currency, CurrencyMismatch, Money
from tests.domain import strategies
from tests.domain.strategies import TENANT, chart

USD = Currency.USD
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def entry(*lines: tuple[int, str], currency: Currency = USD) -> JournalEntry:
    return JournalEntry(
        TENANT,
        NOW,
        "test",
        "1",
        tuple(Line(i, Money(Decimal(a), currency)) for i, a in lines),
    )


@given(strategies.balanced_entry())
def test_every_balanced_entry_posts(e: JournalEntry) -> None:
    assert post(e, chart(e.lines[0].amount.currency)) is e


@given(strategies.unbalanced_entry())
def test_every_unbalanced_entry_is_rejected_with_the_difference(
    case: tuple[JournalEntry, Decimal],
) -> None:
    e, delta = case
    with pytest.raises(UnbalancedEntry) as exc:
        post(e, chart(e.lines[0].amount.currency))
    assert exc.value.currency is e.lines[0].amount.currency
    assert exc.value.difference.amount == delta


def test_single_line_is_rejected_before_anything_else() -> None:
    with pytest.raises(SingleLineEntry):
        post(entry((1, "10")), chart(USD))


def test_zero_line_is_rejected() -> None:
    with pytest.raises(ZeroLine) as exc:
        post(entry((1, "10"), (2, "0"), (3, "-10")), chart(USD))
    assert exc.value.index == 1


def test_unknown_or_foreign_tenant_account_is_rejected() -> None:
    accounts = chart(USD)
    accounts[2] = Account(2, TENANT + 1, "1002", AccountType.ASSET, USD)
    with pytest.raises(UnknownAccount):
        post(entry((1, "10"), (2, "-10")), accounts)
    with pytest.raises(UnknownAccount):
        post(entry((1, "10"), (99, "-10")), accounts)


def test_line_currency_must_match_account_currency() -> None:
    with pytest.raises(CurrencyMismatch):
        post(entry((1, "10"), (2, "-10"), currency=Currency.EUR), chart(USD))


def test_multi_currency_entry_balances_per_currency() -> None:
    accounts = chart(USD) | {
        7: Account(7, TENANT, "1007", AccountType.ASSET, Currency.EUR),
        8: Account(8, TENANT, "1008", AccountType.ASSET, Currency.EUR),
    }
    lines = (
        Line(1, Money(Decimal("5"), USD)),
        Line(2, Money(Decimal("-5"), USD)),
        Line(7, Money(Decimal("3"), Currency.EUR)),
        Line(8, Money(Decimal("-3"), Currency.EUR)),
    )
    e = JournalEntry(TENANT, NOW, "test", "1", lines)
    assert post(e, accounts) is e
    bad = JournalEntry(TENANT, NOW, "test", "1", lines[:3])
    with pytest.raises(UnbalancedEntry) as exc:
        post(bad, accounts)
    assert exc.value.currency is Currency.EUR


@given(strategies.balanced_entry())
def test_reversal_negates_every_line_and_links_back(e: JournalEntry) -> None:
    original = _with_id(e, 42)
    reversed_ = reversal_of(original, NOW)
    assert reversed_.reverses_id == 42
    assert reversed_.source_type == "reversal"
    assert [line.amount for line in reversed_.lines] == [-line.amount for line in e.lines]
    assert post(reversed_, chart(e.lines[0].amount.currency)) is reversed_


def _with_id(e: JournalEntry, id_: int) -> JournalEntry:
    return JournalEntry(e.tenant_id, e.occurred_at, e.source_type, e.source_id, e.lines, id=id_)


def test_unsaved_entry_cannot_be_reversed() -> None:
    with pytest.raises(ValueError):
        reversal_of(entry((1, "1"), (2, "-1")), NOW)
