"""The three calls Airflow makes, plus the token guard."""

from datetime import date

import pytest
from django.test import Client
from freezegun import freeze_time

from tally.adapters.models import OutboxMessage, SettlementMarker, Tenant, WebhookEndpoint
from tally.adapters.tasks import settle_yesterday

TOKEN = {"X-Internal-Token": "dev-internal-token"}


@pytest.mark.django_db
def test_token_guard() -> None:
    assert Client().get("/internal/settlement/2026-02-01").status_code == 401
    assert (
        Client()
        .get("/internal/settlement/2026-02-01", headers={"X-Internal-Token": "x"})
        .status_code
        == 401
    )
    assert Client().get("/internal/settlement/2026-02-01", headers=TOKEN).status_code == 404


@pytest.mark.django_db
def test_settlement_is_404_until_marked() -> None:
    client = Client()
    assert client.get("/internal/settlement/2026-02-01", headers=TOKEN).status_code == 404
    assert client.post("/internal/settlement/2026-02-01", headers=TOKEN).status_code == 200
    assert (
        client.post("/internal/settlement/2026-02-01", headers=TOKEN).status_code == 200
    )  # idempotent
    assert client.get("/internal/settlement/2026-02-01", headers=TOKEN).json()["settled"] is True
    assert SettlementMarker.objects.count() == 1


@pytest.mark.django_db
def test_beat_settles_the_previous_utc_day() -> None:
    with freeze_time("2026-02-02 00:05:00"):
        assert settle_yesterday() == "2026-02-01"
        assert settle_yesterday() == "2026-02-01"
    assert list(SettlementMarker.objects.values_list("day", flat=True)) == [date(2026, 2, 1)]


@pytest.mark.django_db
def test_report_then_ready(tenant: Tenant, bucket: str) -> None:
    WebhookEndpoint.objects.create(tenant=tenant, url="http://x.test", secret="s")
    client = Client()
    body = client.post("/internal/reports/2026-02-01", headers=TOKEN).json()
    assert body == {"day": "2026-02-01", "bucket": bucket, "keys": [f"{tenant.id}/2026-02-01.csv"]}
    ready = client.post("/internal/reports/2026-02-01/ready", headers=TOKEN).json()
    assert ready["notified"] == [tenant.id]
    assert OutboxMessage.objects.get(event_type="report.ready").payload["key"] == body["keys"][0]
    assert client.get("/internal/reports/2026-02-01", headers=TOKEN).status_code == 405
