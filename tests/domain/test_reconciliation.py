from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from tally.domain.money import Currency, Money
from tally.domain.reconciliation import (
    Exception_,
    LedgerItem,
    Match,
    Reason,
    Rule,
    StatementLine,
    match,
)

DAY = date(2026, 10, 1)
USD = Currency.USD


def usd(amount: str) -> Money:
    return Money(Decimal(amount), USD)


def line(id_: int, amount: str, reference: str = "", days: int = 0) -> StatementLine:
    return StatementLine(id_, DAY + timedelta(days=days), usd(amount), reference)


def item(entry_id: int, amount: str, *references: str, days: int = 0) -> LedgerItem:
    return LedgerItem(entry_id, DAY + timedelta(days=days), usd(amount), frozenset(references))


def test_reference_and_amount_wins_over_a_closer_amount_only_candidate() -> None:
    matches, exceptions = match(
        (line(1, "49.00", "inv_7"),), (item(10, "49.00"), item(11, "49.00", "inv_7", days=2))
    )
    assert matches == (Match(1, 11, Rule.REFERENCE),)
    assert exceptions == ()


def test_amount_within_three_days_matches_the_earliest_candidate() -> None:
    matches, _ = match(
        (line(1, "20.00", days=5),), (item(10, "20.00", days=9), item(11, "20.00", days=3))
    )
    assert matches == (Match(1, 11, Rule.AMOUNT_WINDOW),)


def test_amount_outside_the_window_is_unmatched() -> None:
    _, exceptions = match((line(1, "20.00"),), (item(10, "20.00", days=4),))
    assert exceptions == (Exception_(1, Reason.UNMATCHED, usd("20.00")),)


def test_reference_with_a_different_amount_reports_the_difference() -> None:
    _, exceptions = match((line(1, "50.00", "inv_7"),), (item(10, "49.00", "inv_7"),))
    assert exceptions == (Exception_(1, Reason.AMOUNT_DIFFERS, usd("1.00"), entry_id=10),)


def test_each_ledger_item_is_used_once() -> None:
    matches, exceptions = match((line(1, "9.00"), line(2, "9.00")), (item(10, "9.00"),))
    assert matches == (Match(1, 10, Rule.AMOUNT_WINDOW),)
    assert exceptions == (Exception_(2, Reason.UNMATCHED, usd("9.00")),)


amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("5000"), places=2)
refs = st.sampled_from(["", "inv_1", "inv_2", "pi_a", "pi_b"])
days = st.integers(min_value=0, max_value=10)


@st.composite
def scenario(draw: st.DrawFn) -> tuple[tuple[StatementLine, ...], tuple[LedgerItem, ...]]:
    n_lines = draw(st.integers(0, 8))
    n_items = draw(st.integers(0, 8))
    lines = tuple(
        StatementLine(i, DAY + timedelta(days=draw(days)), Money(draw(amounts), USD), draw(refs))
        for i in range(1, n_lines + 1)
    )
    items = tuple(
        LedgerItem(
            100 + i,
            DAY + timedelta(days=draw(days)),
            Money(draw(amounts), USD),
            frozenset(draw(st.lists(refs.filter(bool), max_size=2))),
        )
        for i in range(1, n_items + 1)
    )
    return lines, items


@given(scenario())
def test_every_line_ends_matched_or_excepted_exactly_once(
    data: tuple[tuple[StatementLine, ...], tuple[LedgerItem, ...]],
) -> None:
    lines, items = data
    matches, exceptions = match(lines, items)
    placed = [m.line_id for m in matches] + [e.line_id for e in exceptions]
    assert sorted(placed) == sorted(line.id for line in lines)
    used = [m.entry_id for m in matches]
    assert len(used) == len(set(used))
    assert set(used) <= {item.entry_id for item in items}


@given(scenario(), st.randoms(use_true_random=False))
def test_matching_is_deterministic_under_input_order(
    data: tuple[tuple[StatementLine, ...], tuple[LedgerItem, ...]], rng: object
) -> None:
    import random

    lines, items = data
    shuffled_lines, shuffled_items = list(lines), list(items)
    assert isinstance(rng, random.Random)
    rng.shuffle(shuffled_lines)
    rng.shuffle(shuffled_items)
    assert match(lines, items) == match(tuple(shuffled_lines), tuple(shuffled_items))
