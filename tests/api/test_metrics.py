"""/metrics: django-prometheus request latency plus the business gauges computed from the DB."""

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone
from prometheus_client.parser import text_string_to_metric_families

from tally.adapters.metrics import projection_lag_seconds
from tally.adapters.models import AccountBalance, OutboxMessage, Subscription, WebhookEndpoint
from tests.api.conftest import Idem
from tests.api.test_internal import TOKEN


def scrape() -> dict[str, dict[tuple[tuple[str, str], ...], float]]:
    response = Client().get("/metrics", headers=TOKEN)
    assert response.status_code == 200
    families = text_string_to_metric_families(response.content.decode())
    return {f.name: {tuple(sorted(s.labels.items())): s.value for s in f.samples} for f in families}


@pytest.mark.django_db
def test_metrics_need_the_internal_token() -> None:
    assert Client().get("/metrics").status_code == 401


@pytest.mark.django_db
def test_business_metrics_track_the_database(client: Idem, subscription: Subscription) -> None:
    before = scrape()
    assert before["tally_journal_entries"][()] == 0
    assert before["tally_projection_lag_seconds"][()] == 0
    assert before["tally_celery_queue_depth"][()] >= 0

    assert client.post_entry(("1200", "5.000000"), ("4000", "-5.000000")).status_code == 201
    endpoint = WebhookEndpoint.objects.create(
        tenant=subscription.tenant, url="http://localhost:9/x", secret="s"
    )
    now = timezone.now()
    for kwargs in ({"delivered_at": now}, {"dead_at": now}, {}):
        OutboxMessage.objects.create(
            tenant=subscription.tenant,
            endpoint=endpoint,
            event_type="t",
            payload={},
            next_attempt_at=now,
            **kwargs,
        )

    after = scrape()
    assert after["tally_journal_entries"][()] == 1
    deliveries = after["tally_webhook_deliveries"]
    assert {k[0][1]: v for k, v in deliveries.items()} == {
        "delivered": 1,
        "dead": 1,
        "pending": 1,
    }
    latency = after["django_http_requests_latency_seconds_by_view_method"]
    assert any(dict(labels).get("view") == "entries" for labels in latency)


@pytest.mark.django_db
def test_projection_lag_is_the_gap_between_journal_and_balance(
    client: Idem, ledger: object
) -> None:
    assert client.post_entry(("1200", "5.000000"), ("4000", "-5.000000")).status_code == 201
    assert projection_lag_seconds() == 0
    # Simulate a fold that fell behind: the balance row is older than the entry it should hold.
    AccountBalance.objects.update(as_of=timezone.now() - timedelta(seconds=90))
    assert 85 <= projection_lag_seconds() <= 95  # posted_at is a little before "now"
