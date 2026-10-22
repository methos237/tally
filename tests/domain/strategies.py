from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import assume
from hypothesis import strategies as st

from tally.domain.journal import Account, AccountType, JournalEntry, Line
from tally.domain.money import Currency, Money

TENANT = 1
NOW = datetime(2026, 1, 1, tzinfo=UTC)

currencies = st.sampled_from(list(Currency))
amounts = st.decimals(
    min_value=Decimal("-100000000000"),
    max_value=Decimal("100000000000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)
nonzero_amounts = amounts.filter(lambda d: d != 0)


def money(currency: Currency | None = None) -> st.SearchStrategy[Money]:
    cur = st.just(currency) if currency else currencies
    return st.builds(Money, amounts, cur)


def chart(currency: Currency, size: int = 6) -> dict[int, Account]:
    return {
        i: Account(i, TENANT, f"{1000 + i}", AccountType.ASSET, currency)
        for i in range(1, size + 1)
    }


def entry(
    *lines: tuple[int, str], tenant_id: int = TENANT, currency: Currency = Currency.USD
) -> JournalEntry:
    """Hand-built entry: `entry((account_id, "10"), (other_id, "-10"))`."""
    return JournalEntry(
        tenant_id,
        NOW,
        "test",
        "1",
        tuple(Line(i, Money(Decimal(a), currency)) for i, a in lines),
    )


@st.composite
def balanced_entry(draw: st.DrawFn, currency: Currency | None = None) -> JournalEntry:
    cur = draw(st.just(currency) if currency else currencies)
    accounts = chart(cur)
    amounts_ = draw(st.lists(nonzero_amounts, min_size=1, max_size=8))
    total = sum(amounts_, Decimal(0))
    if total != 0:
        amounts_.append(-total)
    assume(len(amounts_) >= 2)
    ids = draw(
        st.lists(st.sampled_from(sorted(accounts)), min_size=len(amounts_), max_size=len(amounts_))
    )
    lines = tuple(Line(i, Money(a, cur)) for i, a in zip(ids, amounts_, strict=True))
    return JournalEntry(TENANT, NOW, "test", "1", lines)


@st.composite
def unbalanced_entry(draw: st.DrawFn) -> tuple[JournalEntry, Decimal]:
    """A balanced entry with one line nudged by a nonzero delta. Returns (entry, delta)."""
    entry = draw(balanced_entry())
    index = draw(st.integers(0, len(entry.lines) - 1))
    delta = draw(nonzero_amounts)
    line = entry.lines[index]
    assume(line.amount.amount + delta != 0)
    lines = list(entry.lines)
    lines[index] = Line(line.account_id, Money(line.amount.amount + delta, line.amount.currency))
    return JournalEntry(TENANT, entry.occurred_at, "test", "1", tuple(lines)), delta
