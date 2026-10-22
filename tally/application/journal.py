"""Use cases over the journal. Pure orchestration: validation lives in the domain,
persistence in the repository."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from tally.application.ports import JournalRepository
from tally.domain.journal import JournalEntry, post, reversal_of


class EntryNotFound(LookupError):
    def __init__(self, entry_id: int) -> None:
        super().__init__(f"entry {entry_id} not found")
        self.entry_id = entry_id


class AlreadyReversed(ValueError):
    """Raised by the repository: the one-to-one `reverses` link already exists."""

    def __init__(self, entry_id: int) -> None:
        super().__init__(f"entry {entry_id} was already reversed")
        self.entry_id = entry_id


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

    def __call__(
        self,
        tenant_id: int,
        entry_id: int,
        occurred_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> JournalEntry:
        original = self.journal.get(tenant_id, entry_id)
        if original is None:
            raise EntryNotFound(entry_id)
        reversal = reversal_of(original, occurred_at or datetime.now(UTC))
        return PostEntry(self.journal)(replace(reversal, idempotency_key=idempotency_key))
