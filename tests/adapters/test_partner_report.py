"""Against the compose RustFS (CI: a service container). The bucket is created on demand."""

import csv
import io
from datetime import UTC, date, datetime
from io import StringIO

import pytest
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management import call_command

from tally.adapters import billing, reconciliation, reports
from tally.adapters.models import OutboxMessage, Subscription, Tenant, WebhookEndpoint

DAY = date(2026, 2, 1)


@pytest.fixture(scope="module")
def bucket() -> str:
    client = reports.s3()
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET)
    except ClientError:
        client.create_bucket(Bucket=settings.S3_BUCKET)
    return str(settings.S3_BUCKET)


@pytest.fixture
def reported_tenant(subscription: Subscription) -> Tenant:
    invoice = billing.issue_invoice(subscription, datetime(2026, 2, 1, 9, tzinfo=UTC))
    billing.mark_paid(invoice.id, datetime(2026, 2, 1, 10, tzinfo=UTC))
    billing.issue_invoice(subscription, datetime(2026, 2, 2, 9, tzinfo=UTC))  # after DAY
    statement = reconciliation.import_statement(
        subscription.tenant_id, "Date,Description,Reference,Amount\n2026-02-01,fee,F1,-3.00\n"
    )
    reconciliation.reconcile(statement, datetime(2026, 2, 1, 23, tzinfo=UTC))
    return subscription.tenant


@pytest.mark.django_db
def test_report_sections_as_of_the_day(reported_tenant: Tenant) -> None:
    rows = list(csv.DictReader(io.StringIO(reports.build(reported_tenant, DAY))))
    by = {(r["section"], r["key"]): r for r in rows}
    assert by[("account", "1000")]["amount"] == "49.000000"
    assert by[("account", "1200")]["amount"] == "0"  # issued and paid the same day
    assert by[("account", "4000")]["amount"] == "-49.000000"
    assert by[("invoice", "paid")]["count"] == "1"
    assert ("invoice", "open") not in by  # the second invoice is issued after DAY
    exception = next(r for r in rows if r["section"] == "exception")
    assert (exception["label"], exception["amount"]) == ("unmatched", "-3.000000")


@pytest.mark.django_db
def test_command_writes_one_csv_per_tenant_and_notifies(
    reported_tenant: Tenant, bucket: str
) -> None:
    other_tenant = Tenant.objects.create(name="other")
    WebhookEndpoint.objects.create(tenant=reported_tenant, url="http://x.test", secret="s")
    out = StringIO()
    call_command("partner_report", "--date", "2026-02-01", "--notify", stdout=out)
    keys = out.getvalue().split()
    assert keys == [f"{reported_tenant.id}/2026-02-01.csv", f"{other_tenant.id}/2026-02-01.csv"]

    body = reports.s3().get_object(Bucket=bucket, Key=keys[0])["Body"].read().decode()
    assert body.splitlines()[0] == ",".join(reports.COLUMNS)
    assert "account,1000,Cash,1,49.000000,USD" in body

    message = OutboxMessage.objects.get(event_type="report.ready")
    assert message.payload == {"date": "2026-02-01", "bucket": bucket, "key": keys[0]}

    out = StringIO()
    call_command(
        "partner_report", "--date", "2026-02-01", "--tenant", str(other_tenant.id), stdout=out
    )
    assert out.getvalue().split() == [keys[1]]  # rerun overwrites, no error
