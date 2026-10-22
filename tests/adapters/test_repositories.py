import pytest

from tally.adapters.models import Account, JournalLine, Tenant
from tally.adapters.repositories import DjangoJournalRepository
from tally.application.journal import AlreadyReversed, PostEntry, ReverseEntry
from tally.domain.journal import JournalEntry, UnknownAccount
from tests.adapters.conftest import fold_from_journal
from tests.domain.strategies import NOW, entry


def ledger_entry(tenant: Tenant, *lines: tuple[Account, str]) -> JournalEntry:
    return entry(*((a.id, amt) for a, amt in lines), tenant_id=tenant.id)


@pytest.mark.django_db(transaction=True)
def test_post_and_reverse_through_the_database(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, rev = ledger
    repo = DjangoJournalRepository()

    posted = PostEntry(repo)(ledger_entry(tenant, (ar, "149.00"), (rev, "-149.00")))
    assert posted.id is not None and posted.posted_at is not None
    assert repo.get(tenant.id, posted.id) == posted

    reversal = ReverseEntry(repo)(tenant.id, posted.id, occurred_at=NOW)
    assert reversal.reverses_id == posted.id
    assert JournalLine.objects.filter(tenant=tenant).count() == 4
    assert sum(fold_from_journal(tenant).values()) == 0


@pytest.mark.django_db(transaction=True)
def test_reversing_twice_is_refused_by_the_one_to_one_link(
    ledger: tuple[Tenant, Account, Account],
) -> None:
    tenant, ar, rev = ledger
    repo = DjangoJournalRepository()
    posted = PostEntry(repo)(ledger_entry(tenant, (ar, "1"), (rev, "-1")))
    assert posted.id is not None
    ReverseEntry(repo)(tenant.id, posted.id)
    with pytest.raises(AlreadyReversed):
        ReverseEntry(repo)(tenant.id, posted.id)
    assert JournalLine.objects.filter(tenant=tenant).count() == 4


@pytest.mark.django_db
def test_other_tenants_accounts_are_invisible(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, _ = ledger
    other = Tenant.objects.create(name="other")
    foreign = Account.objects.create(
        tenant=other, code="4000", name="Revenue", type="revenue", currency="USD"
    )
    with pytest.raises(UnknownAccount):
        PostEntry(DjangoJournalRepository())(ledger_entry(tenant, (ar, "1"), (foreign, "-1")))


@pytest.mark.django_db
def test_get_filters_by_tenant(ledger: tuple[Tenant, Account, Account]) -> None:
    tenant, ar, rev = ledger
    repo = DjangoJournalRepository()
    posted = PostEntry(repo)(ledger_entry(tenant, (ar, "1"), (rev, "-1")))
    assert posted.id is not None
    assert repo.get(tenant.id + 1, posted.id) is None
