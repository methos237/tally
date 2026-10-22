import threading
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from tally.adapters.models import Account, IdempotencyRecord, JournalEntry, Tenant
from tally.adapters.tasks import expire_idempotency
from tests.api.conftest import entry_body

Ledger = tuple[Tenant, Account, Account]
BODY = entry_body(("1200", "149.00"), ("4000", "-149.00"))


def post(client: APIClient, key: str, body: dict[str, object] = BODY) -> Any:
    return client.post("/api/entries", body, format="json", HTTP_IDEMPOTENCY_KEY=key)


@pytest.mark.django_db
def test_write_without_key_is_400(client: APIClient, ledger: Ledger) -> None:
    response = client.post("/api/entries", BODY, format="json", HTTP_IDEMPOTENCY_KEY="")
    assert response.status_code == 400
    assert response.json()["type"].endswith("/idempotency-key-required")
    assert JournalEntry.objects.count() == 0


@pytest.mark.django_db
def test_same_key_same_body_replays_the_stored_response(client: APIClient, ledger: Ledger) -> None:
    first = post(client, "k1")
    second = post(client, "k1")
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert "Idempotent-Replayed" not in first
    assert second["Idempotent-Replayed"] == "true"
    assert JournalEntry.objects.count() == 1


@pytest.mark.django_db
def test_same_key_different_body_is_422(client: APIClient, ledger: Ledger) -> None:
    post(client, "k1")
    response = post(client, "k1", entry_body(("1200", "1"), ("4000", "-1")))
    assert response.status_code == 422
    assert response.json()["idempotency_key"] == "k1"
    assert JournalEntry.objects.count() == 1


@pytest.mark.django_db
def test_failed_attempt_is_not_stored_so_a_corrected_retry_succeeds(
    client: APIClient, ledger: Ledger
) -> None:
    bad = post(client, "k1", entry_body(("1200", "1"), ("4000", "-2")))
    assert bad.status_code == 422
    assert IdempotencyRecord.objects.count() == 0
    assert post(client, "k1").status_code == 201


@pytest.mark.django_db
def test_keys_are_scoped_per_tenant(
    client: APIClient, other_client: APIClient, ledger: Ledger
) -> None:
    other_tenant = Tenant.objects.get(name="other")
    Account.objects.create(
        tenant=other_tenant, code="1200", name="AR", type="asset", currency="USD"
    )
    Account.objects.create(
        tenant=other_tenant, code="4000", name="Rev", type="revenue", currency="USD"
    )
    assert post(client, "shared").status_code == 201
    response = post(other_client, "shared")
    assert response.status_code == 201 and "Idempotent-Replayed" not in response
    assert JournalEntry.objects.count() == 2


@pytest.mark.django_db
def test_reverse_is_idempotent_too(client: APIClient, ledger: Ledger) -> None:
    entry_id = post(client, "k1").json()["id"]
    url = f"/api/entries/{entry_id}/reverse"
    first = client.post(url, {}, format="json", HTTP_IDEMPOTENCY_KEY="r1")
    second = client.post(url, {}, format="json", HTTP_IDEMPOTENCY_KEY="r1")
    assert first.status_code == 201
    assert second.status_code == 201 and second["Idempotent-Replayed"] == "true"
    assert first.json() == second.json()
    assert JournalEntry.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_with_one_key_post_exactly_once(api_key: str, ledger: Ledger) -> None:
    results: list[Any] = []
    barrier = threading.Barrier(8)

    def fire() -> None:
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=api_key)
        barrier.wait()
        try:
            results.append(post(client, "race"))
        finally:
            connection.close()

    threads = [threading.Thread(target=fire) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert [r.status_code for r in results] == [201] * 8
    assert all(r.json() == results[0].json() for r in results)
    assert sum(r.get("Idempotent-Replayed") == "true" for r in results) == 7
    assert JournalEntry.objects.count() == 1


@pytest.mark.django_db
def test_expire_task_deletes_records_older_than_24_hours(client: APIClient, ledger: Ledger) -> None:
    post(client, "old")
    post(client, "fresh")
    IdempotencyRecord.objects.filter(key="old").update(
        created_at=timezone.now() - timedelta(hours=25)
    )
    assert expire_idempotency() == 1
    assert list(IdempotencyRecord.objects.values_list("key", flat=True)) == ["fresh"]
    assert post(client, "old").status_code == 201  # key free again
