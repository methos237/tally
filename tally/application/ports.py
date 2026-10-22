"""Ports: what the use cases need from the outside world, as Protocols."""

from collections.abc import Iterable, Mapping
from typing import Protocol

from tally.domain.journal import Account, JournalEntry


class JournalRepository(Protocol):
    def accounts_for(self, tenant_id: int, account_ids: Iterable[int]) -> Mapping[int, Account]:
        """Accounts of this tenant among `account_ids`. Foreign ids are simply absent."""
        ...

    def add(self, entry: JournalEntry) -> JournalEntry:
        """Persist a validated entry and return it with id and posted_at set."""
        ...

    def get(self, tenant_id: int, entry_id: int) -> JournalEntry | None: ...
