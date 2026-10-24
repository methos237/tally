"""Business metrics for /metrics, computed from the database at scrape time.

Reading state instead of counting events in process means the numbers are right no
matter how many Django or Celery processes exist; the Celery worker never has to
report anything. django-prometheus adds the HTTP request latency histograms.
"""

from collections.abc import Iterator

from django.db import connection
from django_redis import get_redis_connection
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from tally.adapters.models import JournalEntry, OutboxMessage

PROJECTION_LAG_SQL = """
SELECT COALESCE(MAX(GREATEST(EXTRACT(EPOCH FROM (e.posted_at - b.as_of)), 0)), 0)
FROM account_balances b
JOIN journal_lines l ON l.account_id = b.account_id
JOIN journal_entries e ON e.id = l.entry_id
"""


def projection_lag_seconds() -> float:
    """max(journal_entries.posted_at) - account_balances.as_of over every account; see
    docs/consistency.md. Zero while the fold runs inside the posting transaction."""
    with connection.cursor() as cursor:
        cursor.execute(PROJECTION_LAG_SQL)
        return float(cursor.fetchone()[0])


class TallyCollector(Collector):
    def describe(self) -> Iterator[Metric]:
        """Names only, so registering at app start does not touch the database."""
        for name in (
            "tally_journal_entries",
            "tally_projection_lag_seconds",
            "tally_webhook_deliveries",
            "tally_celery_queue_depth",
        ):
            yield GaugeMetricFamily(name, "")

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
        outbox = OutboxMessage.objects
        deliveries.add_metric(["delivered"], outbox.filter(delivered_at__isnull=False).count())
        deliveries.add_metric(["dead"], outbox.filter(dead_at__isnull=False).count())
        deliveries.add_metric(
            ["pending"], outbox.filter(delivered_at__isnull=True, dead_at__isnull=True).count()
        )
        yield deliveries
        yield GaugeMetricFamily(
            "tally_celery_queue_depth",
            "Tasks waiting in the default Celery queue",
            value=get_redis_connection("default").llen("celery"),
        )
