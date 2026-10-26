"""Multi-currency entries: balanced in the declared base after conversion, or rejected with
the converted difference; a currency without a rate is its own error."""

from decimal import Decimal

import pytest
from hypothesis import given

from tally.domain.journal import (
    Conversion,
    JournalEntry,
    Line,
    MissingRate,
    UnbalancedEntry,
    post,
    reversal_of,
)
from tally.domain.money import Currency, Money
from tests.domain import strategies
from tests.domain.strategies import NOW, TENANT, mixed_chart

EUR_TO_USD = Conversion(Currency.USD, {Currency.EUR: Decimal("1.08")})


def invoice(eur: str, usd: str, conversion: Conversion | None = EUR_TO_USD) -> JournalEntry:
    lines = (Line(4, Money(Decimal(eur), Currency.EUR)), Line(1, Money(Decimal(usd), Currency.USD)))
    return JournalEntry(TENANT, NOW, "invoice", "eu-1", lines, conversion=conversion)


@given(strategies.converted_entry())
def test_every_converted_entry_posts(case: tuple[JournalEntry, dict]) -> None:
    entry, accounts = case
    assert post(entry, accounts) is entry


def test_an_eur_receivable_against_usd_revenue_balances_at_the_declared_rate() -> None:
    accounts = mixed_chart(Currency.USD, Currency.EUR)
    assert post(invoice("100", "-108"), accounts)  # 100 EUR * 1.08 = 108 USD
    with pytest.raises(UnbalancedEntry) as exc:
        post(invoice("100", "-107"), accounts)
    assert (exc.value.currency, exc.value.difference.amount) == (Currency.USD, Decimal("1"))


def test_rounding_is_half_up_to_six_places_like_the_database() -> None:
    conversion = Conversion(Currency.USD, {Currency.EUR: Decimal("1.0000005")})
    # 1 EUR -> 1.0000005 USD rounds up to 1.000001 (half even would give 1.000000)
    assert conversion.to_base(Money(Decimal("1"), Currency.EUR)).amount == Decimal("1.000001")


def test_missing_rate_is_its_own_error() -> None:
    accounts = mixed_chart(Currency.USD, Currency.EUR)
    with pytest.raises(MissingRate) as exc:
        post(invoice("100", "-108", Conversion(Currency.USD, {})), accounts)
    assert (exc.value.currency, exc.value.base) == (Currency.EUR, Currency.USD)


def test_without_a_conversion_each_currency_must_balance_alone() -> None:
    with pytest.raises(UnbalancedEntry):
        post(invoice("100", "-108", None), mixed_chart(Currency.USD, Currency.EUR))


def test_reversal_keeps_the_conversion() -> None:
    original = JournalEntry(
        TENANT, NOW, "invoice", "1", invoice("100", "-108").lines, id=7, conversion=EUR_TO_USD
    )
    reversal = reversal_of(original, NOW)
    assert reversal.conversion == EUR_TO_USD
    assert post(reversal, mixed_chart(Currency.USD, Currency.EUR))
