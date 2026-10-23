"""The partner daily report: one CSV per tenant per day, written to the S3 bucket.

Plain management-command work so it runs and tests without Airflow; Airflow only
schedules it. Sections in one file: account balances as of the day, invoice status
counts, open reconciliation exceptions.
"""

import csv
import io
from datetime import date, datetime, time
from typing import Any

import boto3
from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from tally.adapters import models, outbox

COLUMNS = ["section", "key", "label", "count", "amount", "currency"]


def build(tenant: models.Tenant, day: date) -> str:
    """CSV text for `tenant` as of the end of `day`."""
    end = datetime.combine(day, time.max, tzinfo=timezone.get_current_timezone())
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    accounts = models.Account.objects.filter(tenant=tenant).order_by("code")
    for account in accounts:
        agg = models.JournalLine.objects.filter(
            account=account, entry__occurred_at__lte=end
        ).aggregate(n=Count("id"), total=Sum("amount"))
        writer.writerow(
            ["account", account.code, account.name, agg["n"], agg["total"] or 0, account.currency]
        )
    invoices = (
        models.Invoice.objects.filter(tenant=tenant, issued_at__lte=end)
        .values("status", "currency")
        .annotate(n=Count("id"), total=Sum("amount"))
        .order_by("status", "currency")
    )
    for row in invoices:
        writer.writerow(["invoice", row["status"], "", row["n"], row["total"], row["currency"]])
    exceptions = models.ReconciliationException.objects.filter(
        tenant=tenant, line__occurred_on__lte=day, resolved_at__isnull=True
    ).order_by("id")
    for exc in exceptions:
        writer.writerow(["exception", exc.id, exc.reason, 1, exc.difference, exc.currency])
    return out.getvalue()


def key_for(tenant: models.Tenant, day: date) -> str:
    return f"{tenant.id}/{day.isoformat()}.csv"


def s3() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name="us-east-1",
    )


def write(tenant: models.Tenant, day: date) -> str:
    """Build and upload; returns the object key. Overwrites: a rerun for the same day
    replaces the file, which is what a backfill wants."""
    key = key_for(tenant, day)
    s3().put_object(
        Bucket=settings.S3_BUCKET, Key=key, Body=build(tenant, day).encode(), ContentType="text/csv"
    )
    return key


def notify_ready(tenant: models.Tenant, day: date) -> None:
    """`report.ready` to the tenant's webhook endpoints, naming where the file landed."""
    outbox.publish(
        tenant.id,
        "report.ready",
        {"date": day, "bucket": settings.S3_BUCKET, "key": key_for(tenant, day)},
    )
