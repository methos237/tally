from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tally.domain.money import Currency, CurrencyMismatch, Money
from tests.domain import strategies

usd = Currency.USD


@given(strategies.currencies, strategies.amounts, strategies.amounts, strategies.amounts)
def test_addition_is_associative_and_commutative(
    currency: Currency, a: Decimal, b: Decimal, c: Decimal
) -> None:
    x, y, z = Money(a, currency), Money(b, currency), Money(c, currency)
    assert (x + y) + z == x + (y + z)
    assert x + y == y + x


@given(strategies.money())
def test_zero_is_identity_and_self_difference_is_zero(m: Money) -> None:
    zero = Money.zero(m.currency)
    assert m + zero == m
    assert m - m == zero
    assert (m + (-m)).is_zero


@given(strategies.money(), strategies.money())
def test_mixed_currencies_refuse_arithmetic(a: Money, b: Money) -> None:
    if a.currency is b.currency:
        a + b
    else:
        with pytest.raises(CurrencyMismatch):
            a + b
        with pytest.raises(CurrencyMismatch):
            a - b


@given(st.decimals(allow_nan=False, allow_infinity=False, places=12))
def test_construction_quantizes_to_six_places_half_even(amount: Decimal) -> None:
    assert Money(amount, usd).amount == amount.quantize(
        Decimal("0.000001"), rounding="ROUND_HALF_EVEN"
    )


def test_half_even_rounding_at_the_stored_boundary() -> None:
    assert Money(Decimal("1.0000005"), usd).amount == Decimal("1.000000")
    assert Money(Decimal("1.0000015"), usd).amount == Decimal("1.000002")


def test_display_uses_currency_exponent() -> None:
    assert Money(Decimal("149.005"), usd).display() == "149.00 USD"
    assert Money(Decimal("149.015"), usd).display() == "149.02 USD"
    assert Money(Decimal("1200.5"), Currency.JPY).display() == "1200 JPY"


def test_floats_are_refused() -> None:
    with pytest.raises(TypeError):
        Money(1.5, usd)  # type: ignore[arg-type]
