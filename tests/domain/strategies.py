from decimal import Decimal

from hypothesis import strategies as st

from tally.domain.money import Currency, Money

currencies = st.sampled_from(list(Currency))
amounts = st.decimals(
    min_value=Decimal("-1000000000"),
    max_value=Decimal("1000000000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)


def money(currency: Currency | None = None) -> st.SearchStrategy[Money]:
    cur = st.just(currency) if currency else currencies
    return st.builds(Money, amounts, cur)
