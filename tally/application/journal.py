"""Use cases over the journal. Pure orchestration: validation lives in the domain,
persistence in the repository."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from tally.application.ports import JournalRepository
from tally.domain.journal import JournalEntry, post, reversal_of


class EntryNotFound(LookupError):
    def __init__(self, entry_id: int) -> None:
        super().__init__(f"entry {entry_id} not found")
        self.entry_id = entry_id


class AlreadyReversed(ValueError):
    def __init__(self, entry_id: int, reversed_by_id: int) -> None:
        super().__init__(f"entry {entry_id} was already reversed by entry {reversed_by_id}")
        self.entry_id, self.reversed_by_id = entry_id, reversed_by_id


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PostEntry:
    journal: JournalRepository

    def __call__(self, entry: JournalEntry) -> JournalEntry:
        accounts = self.journal.accounts_for(
            entry.tenant_id, {line.account_id for line in entry.lines}
        )
        return self.journal.add(post(entry, accounts))


@dataclass(frozen=True, slots=True)
class ReverseEntry:
    journal: JournalRepository
    clock: Callable[[], datetime] = _utcnow

    def __call__(
        self, tenant_id: int, entry_id: int, occurred_at: datetime | None = None
    ) -> JournalEntry:
        original = self.journal.get(tenant_id, entry_id)
        if original is None:
            raise EntryNotFound(entry_id)
        if original.reversed_by_id is not None:
            raise AlreadyReversed(entry_id, original.reversed_by_id)
        reversal = reversal_of(original, occurred_at or self.clock())
        return PostEntry(self.journal)(reversal)
