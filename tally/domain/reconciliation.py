"""Statement matching. Pure: lines in, matches and exceptions out.

Rules run in order for each statement line, lowest line id first, and every ledger
item is used at most once:

1. `reference`: a ledger item carries the line's reference and the same amount.
2. `amount_window`: same amount, dated within WINDOW_DAYS; the earliest such item wins.
3. otherwise an exception: `amount_differs` when the reference matched but the amount
   did not (the difference is carried), `unmatched` when nothing fits.

Deterministic by construction: sorted inputs, first-fit, no randomness; a line order
permutation yields the same result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from tally.domain.money import Money

WINDOW_DAYS = 3


@dataclass(frozen=True, slots=True)
class StatementLine:
    id: int
    occurred_on: date
    amount: Money
    reference: str


@dataclass(frozen=True, slots=True)
class LedgerItem:
    """A cash movement already in the journal, as the statement should see it."""

    entry_id: int
    occurred_on: date
    amount: Money
    references: frozenset[str]


class Rule(StrEnum):
    REFERENCE = "reference"
    AMOUNT_WINDOW = "amount_window"


class Reason(StrEnum):
    AMOUNT_DIFFERS = "amount_differs"
    UNMATCHED = "unmatched"


@dataclass(frozen=True, slots=True)
class Match:
    line_id: int
    entry_id: int
    rule: Rule


@dataclass(frozen=True, slots=True)
class Exception_:
    """A line the rules could not place. `difference` is statement minus ledger when a
    reference matched with another amount, else the full line amount."""

    line_id: int
    reason: Reason
    difference: Money
    entry_id: int | None = None


def match(
    lines: tuple[StatementLine, ...], items: tuple[LedgerItem, ...], window_days: int = WINDOW_DAYS
) -> tuple[tuple[Match, ...], tuple[Exception_, ...]]:
    free = sorted(items, key=lambda item: (item.occurred_on, item.entry_id))
    matches: list[Match] = []
    exceptions: list[Exception_] = []
    for line in sorted(lines, key=lambda line: line.id):
        by_reference = [
            item
            for item in free
            if line.reference
            and line.reference in item.references
            and item.amount.currency is line.amount.currency
        ]
        exact = [item for item in by_reference if item.amount == line.amount]
        if exact:
            chosen, rule = exact[0], Rule.REFERENCE
        else:
            near = [
                item
                for item in free
                if item.amount == line.amount
                and abs((item.occurred_on - line.occurred_on).days) <= window_days
            ]
            if near:
                chosen, rule = near[0], Rule.AMOUNT_WINDOW
            elif by_reference:
                item = by_reference[0]
                exceptions.append(
                    Exception_(
                        line.id, Reason.AMOUNT_DIFFERS, line.amount - item.amount, item.entry_id
                    )
                )
                continue
            else:
                exceptions.append(Exception_(line.id, Reason.UNMATCHED, line.amount))
                continue
        free.remove(chosen)
        matches.append(Match(line.id, chosen.entry_id, rule))
    return tuple(matches), tuple(exceptions)
