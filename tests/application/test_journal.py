from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given

from tally.application.journal import AlreadyReversed, EntryNotFound, PostEntry, ReverseEntry
from tally.domain.journal import Account, JournalEntry, Line, UnbalancedEntry, UnknownAccount
from tally.domain.money import Currency, Money
from tests.domain import strategies
from tests.domain.strategies import TENANT, chart

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeJournal:
    """In-memory repository: a list of entries and a chart of accounts."""

    def __init__(self, accounts: Mapping[int, Account]) -> None:
        self.accounts = dict(accounts)
        self.entries: dict[int, JournalEntry] = {}

    def accounts_for(self, tenant_id: int, account_ids: Iterable[int]) -> Mapping[int, Account]:
        return {
            i: a for i, a in self.accounts.items() if a.tenant_id == tenant_id and i in account_ids
        }

    def add(self, entry: JournalEntry) -> JournalEntry:
        new_id = len(self.entries) + 1
        saved = JournalEntry(**{**vars_of(entry), "id": new_id, "posted_at": NOW})
        self.entries[new_id] = saved
        if saved.reverses_id is not None:
            original = self.entries[saved.reverses_id]
            self.entries[saved.reverses_id] = JournalEntry(
                **{**vars_of(original), "reversed_by_id": new_id}
            )
        return saved

    def get(self, tenant_id: int, entry_id: int) -> JournalEntry | None:
        entry = self.entries.get(entry_id)
        return entry if entry and entry.tenant_id == tenant_id else None


def vars_of(entry: JournalEntry) -> dict[str, object]:
    return {name: getattr(entry, name) for name in JournalEntry.__slots__}


def entry(*lines: tuple[int, str]) -> JournalEntry:
    return JournalEntry(
        TENANT,
        NOW,
        "invoice",
        "inv_1",
        tuple(Line(i, Money(Decimal(a), Currency.USD)) for i, a in lines),
    )


@given(strategies.balanced_entry())
def test_post_entry_persists_any_balanced_entry(e: JournalEntry) -> None:
    journal = FakeJournal(chart(e.lines[0].amount.currency))
    saved = PostEntry(journal)(e)
    assert saved.id == 1 and saved.posted_at == NOW
    assert saved.lines == e.lines


def test_post_entry_rejects_unbalanced_and_persists_nothing() -> None:
    journal = FakeJournal(chart(Currency.USD))
    with pytest.raises(UnbalancedEntry):
        PostEntry(journal)(entry((1, "10"), (2, "-9")))
    assert journal.entries == {}


def test_post_entry_cannot_touch_another_tenants_account() -> None:
    journal = FakeJournal(chart(Currency.USD))
    journal.accounts[9] = Account(9, TENANT + 1, "1009", journal.accounts[1].type, Currency.USD)
    with pytest.raises(UnknownAccount):
        PostEntry(journal)(entry((1, "10"), (9, "-10")))


def test_reverse_entry_posts_negated_lines_linked_to_original() -> None:
    journal = FakeJournal(chart(Currency.USD))
    original = PostEntry(journal)(entry((1, "10"), (2, "-10")))
    assert original.id is not None

    reversal = ReverseEntry(journal, clock=lambda: NOW)(TENANT, original.id)

    assert reversal.reverses_id == original.id
    assert [line.amount.amount for line in reversal.lines] == [Decimal("-10"), Decimal("10")]
    assert journal.entries[original.id].reversed_by_id == reversal.id


def test_reverse_entry_refuses_twice_and_unknown_ids() -> None:
    journal = FakeJournal(chart(Currency.USD))
    original = PostEntry(journal)(entry((1, "10"), (2, "-10")))
    assert original.id is not None
    reverse = ReverseEntry(journal, clock=lambda: NOW)
    reverse(TENANT, original.id)

    with pytest.raises(AlreadyReversed):
        reverse(TENANT, original.id)
    with pytest.raises(EntryNotFound):
        reverse(TENANT, 999)
    with pytest.raises(EntryNotFound):
        reverse(TENANT + 1, original.id)
