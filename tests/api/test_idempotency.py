from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from tally.adapters.models import IdempotencyRecord, JournalEntry, Tenant
from tally.adapters.tasks import expire_idempotency
from tests.api.conftest import Idem, client_for, in_threads
from tests.conftest import Ledger, chart_for

LINES = (("1200", "149.00"), ("4000", "-149.00"))


@pytest.mark.django_db
def test_write_without_key_is_400(client: Idem, ledger: Ledger) -> None:
    response = client.post_entry(*LINES, key="")
    assert response.status_code == 400
    assert response.json()["type"].endswith("/idempotency-key-required")
    assert JournalEntry.objects.count() == 0


@pytest.mark.django_db
def test_same_key_same_body_replays_the_stored_response(client: Idem, ledger: Ledger) -> None:
    first = client.post_entry(*LINES, key="k1")
    second = client.post_entry(*LINES, key="k1")
    assert first.status_code == second.status_code == 201
    assert first.content == second.content  # byte-identical, not just equal
    assert "Idempotent-Replayed" not in first
    assert second["Idempotent-Replayed"] == "true"
    assert second["Content-Type"] == "application/json"
    assert JournalEntry.objects.count() == 1


@pytest.mark.django_db
def test_same_key_different_body_is_422(client: Idem, ledger: Ledger) -> None:
    client.post_entry(*LINES, key="k1")
    response = client.post_entry(("1200", "1"), ("4000", "-1"), key="k1")
    assert response.status_code == 422
    assert response.json()["idempotency_key"] == "k1"
    assert JournalEntry.objects.count() == 1


@pytest.mark.django_db
def test_failed_attempt_is_not_stored_so_a_corrected_retry_succeeds(
    client: Idem, ledger: Ledger
) -> None:
    bad = client.post_entry(("1200", "1"), ("4000", "-2"), key="k1")
    assert bad.status_code == 422
    assert IdempotencyRecord.objects.count() == 0
    assert client.post_entry(*LINES, key="k1").status_code == 201


@pytest.mark.django_db
def test_keys_are_scoped_per_tenant(
    client: Idem, other_client: Idem, other_tenant: Tenant, ledger: Ledger
) -> None:
    chart_for(other_tenant)
    assert client.post_entry(*LINES, key="shared").status_code == 201
    response = other_client.post_entry(*LINES, key="shared")
    assert response.status_code == 201 and "Idempotent-Replayed" not in response
    assert JournalEntry.objects.count() == 2


@pytest.mark.django_db
def test_reverse_is_idempotent_too(client: Idem, ledger: Ledger) -> None:
    entry_id = client.post_entry(*LINES).json()["id"]
    url = f"/api/entries/{entry_id}/reverse"
    first = client.post(url, {}, format="json", HTTP_IDEMPOTENCY_KEY="r1")
    second = client.post(url, {}, format="json", HTTP_IDEMPOTENCY_KEY="r1")
    assert first.status_code == 201
    assert second.status_code == 201 and second["Idempotent-Replayed"] == "true"
    assert first.content == second.content
    assert JournalEntry.objects.count() == 2
    assert JournalEntry.objects.get(reverses_id=entry_id).idempotency_key == "r1"


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_with_one_key_post_exactly_once(api_key: str, ledger: Ledger) -> None:
    results: list[Any] = []
    in_threads(8, lambda _: results.append(client_for(api_key).post_entry(*LINES, key="race")))

    assert [r.status_code for r in results] == [201] * 8
    assert len({r.content for r in results}) == 1
    assert sum(r.get("Idempotent-Replayed") == "true" for r in results) == 7
    assert JournalEntry.objects.count() == 1


@pytest.mark.django_db
def test_expire_task_deletes_records_older_than_24_hours(client: Idem, ledger: Ledger) -> None:
    client.post_entry(*LINES, key="old")
    client.post_entry(*LINES, key="fresh")
    IdempotencyRecord.objects.filter(key="old").update(
        created_at=timezone.now() - timedelta(hours=25)
    )
    assert expire_idempotency() == 1
    assert list(IdempotencyRecord.objects.values_list("key", flat=True)) == ["fresh"]
    assert client.post_entry(*LINES, key="old").status_code == 201  # key free again
