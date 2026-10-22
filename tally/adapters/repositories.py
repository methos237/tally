"""Django ORM implementation of the application ports."""

from collections.abc import Iterable, Mapping
from decimal import Decimal

from django.db import transaction

from tally.adapters import models
from tally.domain.journal import Account, AccountType, JournalEntry, Line
from tally.domain.money import Currency, Money


def to_domain_account(row: models.Account) -> Account:
    return Account(
        id=row.id,
        tenant_id=row.tenant_id,
        code=row.code,
        type=AccountType(row.type),
        currency=Currency(row.currency),
    )


def to_domain_entry(row: models.JournalEntry, lines: Iterable[models.JournalLine]) -> JournalEntry:
    return JournalEntry(
        tenant_id=row.tenant_id,
        occurred_at=row.occurred_at,
        source_type=row.source_type,
        source_id=row.source_id,
        lines=tuple(
            Line(line.account_id, Money(Decimal(line.amount), Currency(line.currency)))
            for line in lines
        ),
        id=row.id,
        posted_at=row.posted_at,
        idempotency_key=row.idempotency_key,
        reverses_id=row.reverses_id,
        reversed_by_id=getattr(row, "reversed_by", None) and row.reversed_by.id,
    )


class DjangoJournalRepository:
    def accounts_for(self, tenant_id: int, account_ids: Iterable[int]) -> Mapping[int, Account]:
        rows = models.Account.objects.filter(tenant_id=tenant_id, id__in=list(account_ids))
        return {row.id: to_domain_account(row) for row in rows}

    def add(self, entry: JournalEntry) -> JournalEntry:
        with transaction.atomic():
            row = models.JournalEntry.objects.create(
                tenant_id=entry.tenant_id,
                occurred_at=entry.occurred_at,
                source_type=entry.source_type,
                source_id=entry.source_id,
                idempotency_key=entry.idempotency_key,
                reverses_id=entry.reverses_id,
            )
            lines = models.JournalLine.objects.bulk_create(
                models.JournalLine(
                    tenant_id=entry.tenant_id,
                    entry=row,
                    account_id=line.account_id,
                    amount=line.amount.amount,
                    currency=line.amount.currency.value,
                )
                for line in entry.lines
            )
        return to_domain_entry(row, lines)

    def get(self, tenant_id: int, entry_id: int) -> JournalEntry | None:
        row = (
            models.JournalEntry.objects.filter(tenant_id=tenant_id, id=entry_id)
            .select_related("reversed_by")
            .prefetch_related("lines")
            .first()
        )
        if row is None:
            return None
        return to_domain_entry(row, row.lines.order_by("id"))
