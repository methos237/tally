"""Money: a Decimal amount bound to a currency.

Amounts are quantized to six decimal places with ROUND_HALF_EVEN on
construction; that is the only rounding in the domain. Display rounds
to the currency's exponent. Floats never touch money.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

STORED_PLACES = Decimal("0.000001")


class Currency(StrEnum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"

    @property
    def exponent(self) -> int:
        return 0 if self is Currency.JPY else 2


class CurrencyMismatch(ValueError):
    def __init__(self, left: Currency, right: Currency) -> None:
        super().__init__(f"cannot combine {left} with {right}")
        self.left, self.right = left, right


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if isinstance(self.amount, float):
            raise TypeError("Money amount must be Decimal, not float")
        quantized = Decimal(self.amount).quantize(STORED_PLACES, rounding=ROUND_HALF_EVEN)
        object.__setattr__(self, "amount", quantized)

    @classmethod
    def zero(cls, currency: Currency) -> Money:
        return cls(Decimal(0), currency)

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def _same(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise CurrencyMismatch(self.currency, other.currency)

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        return Money(self.amount * factor, self.currency)

    def display(self) -> str:
        places = Decimal(1).scaleb(-self.currency.exponent)
        return f"{self.amount.quantize(places, rounding=ROUND_HALF_EVEN)} {self.currency}"
