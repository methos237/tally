"""Business metrics for /metrics, computed from the database at scrape time.

Reading state instead of counting events in process means the numbers are right no
matter how many Django or Celery processes exist; the Celery worker never has to
report anything. django-prometheus adds the HTTP request latency histograms.
"""

from collections.abc import Iterator

from django.db import connection
from django.db.models import Count, Q
from django_redis import get_redis_connection
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from tally.adapters.models import JournalEntry, OutboxMessage

# One index probe per account (ix_lines_tenant_account), not a scan of every line per scrape.
PROJECTION_LAG_SQL = """
SELECT COALESCE(MAX(GREATEST(EXTRACT(EPOCH FROM (latest.posted_at - b.as_of)), 0)), 0)
FROM account_balances b
JOIN LATERAL (
    SELECT max(e.posted_at) AS posted_at
    FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
    WHERE l.tenant_id = b.tenant_id AND l.account_id = b.account_id
) latest ON true
"""


def projection_lag_seconds() -> float:
    """max(journal_entries.posted_at) - account_balances.as_of over every account; see
    docs/consistency.md. Zero while the fold runs inside the posting transaction."""
    with connection.cursor() as cursor:
        cursor.execute(PROJECTION_LAG_SQL)
        return float(cursor.fetchone()[0])


class TallyCollector(Collector):
    def describe(self) -> list[Metric]:
        return []  # any describe() keeps REGISTRY.register from running collect() at startup

    def collect(self) -> Iterator[Metric]:
        yield CounterMetricFamily(
            "tally_journal_entries",
            "Entries posted (rate() gives the posting rate)",
            value=JournalEntry.objects.count(),
        )
        yield GaugeMetricFamily(
            "tally_projection_lag_seconds",
            "Balance projection lag behind the journal",
            value=projection_lag_seconds(),
        )
        deliveries = GaugeMetricFamily(
            "tally_webhook_deliveries", "Outbox messages by state", labels=["state"]
        )
        counts = OutboxMessage.objects.aggregate(
            delivered=Count("id", filter=Q(delivered_at__isnull=False)),
            dead=Count("id", filter=Q(dead_at__isnull=False)),
            pending=Count("id", filter=Q(delivered_at__isnull=True, dead_at__isnull=True)),
        )
        for state, value in counts.items():
            deliveries.add_metric([state], value)
        yield deliveries
        yield GaugeMetricFamily(
            "tally_celery_queue_depth",
            "Tasks waiting in the default Celery queue",
            value=get_redis_connection("default").llen("celery"),
        )
