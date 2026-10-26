"""Accounts, journal entries and the posting rule.

`post()` is the balancing invariant: at least two lines, no zero line, every
line in its account's currency, and lines summing to zero per currency. An entry
that declares a Conversion balances in its base currency instead: each other
currency's total is converted at the declared rate and the converted totals sum to
zero. It raises a typed error naming exactly what is wrong.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from tally.domain.money import STORED_PLACES, Currency, CurrencyMismatch, Money

MAX_LINE_ABS = Decimal("1e12")  # journal_lines.amount is numeric(18,6): 12 integer digits


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


@dataclass(frozen=True, slots=True)
class Account:
    id: int
    tenant_id: int
    code: str
    type: AccountType
    currency: Currency


@dataclass(frozen=True, slots=True)
class Line:
    account_id: int
    amount: Money


@dataclass(frozen=True, slots=True)
class Conversion:
    """The declared rule for a multi-currency entry: `rates[c]` is how many units of `base`
    one unit of `c` is worth. Converted totals round half up to the stored places, the same
    rounding Postgres' round() uses, so the domain and the database trigger agree."""

    base: Currency
    rates: Mapping[Currency, Decimal]

    def to_base(self, total: Money) -> Money:
        if total.currency is self.base:
            return total
        rate = self.rates.get(total.currency)
        if rate is None:
            raise MissingRate(total.currency, self.base)
        converted = (total.amount * rate).quantize(STORED_PLACES, rounding=ROUND_HALF_UP)
        return Money(converted, self.base)


@dataclass(frozen=True, slots=True)
class JournalEntry:
    tenant_id: int
    occurred_at: datetime
    source_type: str
    source_id: str
    lines: tuple[Line, ...]
    id: int | None = None
    posted_at: datetime | None = None
    idempotency_key: str | None = None
    reverses_id: int | None = None
    conversion: Conversion | None = None


class PostingError(ValueError):
    """Base class: the entry violates the posting rule."""


class SingleLineEntry(PostingError):
    def __init__(self, count: int) -> None:
        super().__init__(f"an entry needs at least two lines, got {count}")
        self.count = count


class ZeroLine(PostingError):
    def __init__(self, index: int) -> None:
        super().__init__(f"line {index} has a zero amount")
        self.index = index


class AmountOutOfRange(PostingError):
    def __init__(self, index: int, amount: Money) -> None:
        super().__init__(f"line {index} amount {amount.amount} does not fit numeric(18,6)")
        self.index, self.amount = index, amount


class UnbalancedEntry(PostingError):
    def __init__(self, currency: Currency, difference: Money) -> None:
        super().__init__(f"lines in {currency} sum to {difference.amount}, not zero")
        self.currency = currency
        self.difference = difference


class MissingRate(PostingError):
    def __init__(self, currency: Currency, base: Currency) -> None:
        super().__init__(f"no rate declared from {currency} to {base}")
        self.currency, self.base = currency, base


class UnknownAccount(PostingError):
    def __init__(self, account_id: int) -> None:
        super().__init__(f"account {account_id} does not exist for this tenant")
        self.account_id = account_id


def post(entry: JournalEntry, accounts: Mapping[int, Account]) -> JournalEntry:
    """Validate the entry against the posting rule and return it unchanged.

    Checks run in a fixed order so a failure is reproducible from its input:
    line count, zero or oversized lines, account existence and currency, then balance.
    """
    if len(entry.lines) < 2:
        raise SingleLineEntry(len(entry.lines))
    for index, line in enumerate(entry.lines):
        if line.amount.is_zero:
            raise ZeroLine(index)
        if abs(line.amount.amount) >= MAX_LINE_ABS:
            raise AmountOutOfRange(index, line.amount)
    totals: dict[Currency, Money] = {}
    for line in entry.lines:
        account = accounts.get(line.account_id)
        if account is None or account.tenant_id != entry.tenant_id:
            raise UnknownAccount(line.account_id)
        if account.currency is not line.amount.currency:
            raise CurrencyMismatch(account.currency, line.amount.currency)
        cur = line.amount.currency
        totals[cur] = totals.get(cur, Money.zero(cur)) + line.amount
    if entry.conversion is None:
        for currency, total in totals.items():
            if not total.is_zero:
                raise UnbalancedEntry(currency, total)
        return entry
    base = entry.conversion.base
    converted = Money.zero(base)
    for total in totals.values():
        if not total.is_zero:
            converted += entry.conversion.to_base(total)
    if not converted.is_zero:
        raise UnbalancedEntry(base, converted)
    return entry


def reversal_of(original: JournalEntry, occurred_at: datetime) -> JournalEntry:
    """Build the entry that undoes `original`: same lines, negated, linked back."""
    if original.id is None:
        raise ValueError("only a persisted entry can be reversed")
    return JournalEntry(
        tenant_id=original.tenant_id,
        occurred_at=occurred_at,
        source_type="reversal",
        source_id=str(original.id),
        lines=tuple(Line(line.account_id, -line.amount) for line in original.lines),
        reverses_id=original.id,
        conversion=original.conversion,
    )
