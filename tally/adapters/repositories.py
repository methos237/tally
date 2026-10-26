"""Django ORM implementation of the application ports."""

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction

from tally.adapters import models, outbox, projections
from tally.application.journal import AlreadyReversed
from tally.domain.journal import Account, AccountType, Conversion, JournalEntry, Line
from tally.domain.money import Currency, Money


def to_domain_account(row: models.Account) -> Account:
    return Account(
        id=row.id,
        tenant_id=row.tenant_id,
        code=row.code,
        type=AccountType(row.type),
        currency=Currency(row.currency),
    )


def conversion_json(conversion: Conversion | None) -> dict[str, Any] | None:
    if conversion is None:
        return None
    return {
        "base": conversion.base.value,
        "rates": {c.value: str(r) for c, r in conversion.rates.items()},
    }


def conversion_from_json(data: dict[str, Any] | None) -> Conversion | None:
    if data is None:
        return None
    return Conversion(
        Currency(data["base"]), {Currency(c): Decimal(r) for c, r in data["rates"].items()}
    )


def to_domain_entry(row: models.JournalEntry, lines: Iterable[models.JournalLine]) -> JournalEntry:
    return JournalEntry(
        tenant_id=row.tenant_id,
        occurred_at=row.occurred_at,
        source_type=row.source_type,
        source_id=row.source_id,
        lines=tuple(
            Line(line.account_id, Money(line.amount, Currency(line.currency))) for line in lines
        ),
        id=row.id,
        posted_at=row.posted_at,
        idempotency_key=row.idempotency_key,
        reverses_id=row.reverses_id,
        conversion=conversion_from_json(row.conversion),
    )


def lock_accounts(account_ids: Iterable[int]) -> None:
    """SELECT ... FOR UPDATE on the touched accounts, ordered by id.

    Two postings that touch the same accounts in opposite order would deadlock if
    each locked in its own line order; sorting makes every transaction acquire
    the same locks in the same sequence. Deadlock-free by construction, no retry
    loop anywhere. The account_balances rows are updated under these locks.
    """
    ids = sorted(set(account_ids))
    list(models.Account.objects.select_for_update().filter(id__in=ids).order_by("id"))


def entry_event(row: models.JournalEntry, lines: list[models.JournalLine]) -> dict[str, object]:
    return {
        "entry_id": row.id,
        "occurred_at": row.occurred_at,
        "source": {"type": row.source_type, "id": row.source_id},
        "reverses": row.reverses_id,
        "lines": [
            {"account_id": line.account_id, "amount": line.amount, "currency": line.currency}
            for line in lines
        ],
    }


class DjangoJournalRepository:
    def accounts_for(self, tenant_id: int, account_ids: Iterable[int]) -> Mapping[int, Account]:
        rows = models.Account.objects.filter(tenant_id=tenant_id, id__in=list(account_ids))
        return {row.id: to_domain_account(row) for row in rows}

    def add(self, entry: JournalEntry) -> JournalEntry:
        try:
            with transaction.atomic():
                lock_accounts(line.account_id for line in entry.lines)
                row = models.JournalEntry.objects.create(
                    tenant_id=entry.tenant_id,
                    occurred_at=entry.occurred_at,
                    source_type=entry.source_type,
                    source_id=entry.source_id,
                    idempotency_key=entry.idempotency_key,
                    reverses_id=entry.reverses_id,
                    conversion=conversion_json(entry.conversion),
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
                projections.apply(row)
                outbox.publish(entry.tenant_id, "entry.posted", entry_event(row, lines))
        except IntegrityError as exc:
            if entry.reverses_id is not None and "reverses_id" in str(exc):
                raise AlreadyReversed(entry.reverses_id) from exc
            raise
        return to_domain_entry(row, lines)

    def get(self, tenant_id: int, entry_id: int) -> JournalEntry | None:
        row = models.JournalEntry.objects.filter(tenant_id=tenant_id, id=entry_id).first()
        if row is None:
            return None
        return to_domain_entry(row, row.lines.order_by("id"))
