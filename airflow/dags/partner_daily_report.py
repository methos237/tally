"""partner_daily_report: wait for the day to settle, write the CSVs, announce them.

Three HTTP calls against Tally's /internal endpoints (connection `tally`, token in
Variable `tally_internal_token`), so this image stays stock and the job itself is a
Django management command that runs and tests without Airflow.

The day reported is the run's logical date (scheduled, backfilled, or
`airflow dags trigger -l 2026-10-01`); a manual trigger without one reports yesterday.
30 minutes end to end is the SLA, enforced as dagrun_timeout (Airflow 3 dropped task SLAs).

Backfill:  airflow backfill create --dag-id partner_daily_report \
               --from-date 2026-10-01 --to-date 2026-10-07
"""

from datetime import datetime, timedelta
from typing import Any

from airflow.providers.http.operators.http import HttpOperator
from airflow.providers.http.sensors.http import HttpSensor
from airflow.sdk import DAG

HEADERS = {"X-Internal-Token": "{{ var.value.tally_internal_token }}"}


def report_day(dag_run: Any) -> str:
    when = dag_run.logical_date or (dag_run.run_after - timedelta(days=1))
    return when.date().isoformat()


with DAG(
    dag_id="partner_daily_report",
    description="Nightly partner CSV per tenant, after the day's entries settle",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=30),
    default_args={"retries": 3, "retry_delay": timedelta(minutes=5)},
    user_defined_macros={"report_day": report_day},
    tags=["tally", "reports"],
) as dag:
    wait_for_settlement = HttpSensor(
        task_id="wait_for_settlement",
        http_conn_id="tally",
        endpoint="internal/settlement/{{ report_day(dag_run) }}",
        headers=HEADERS,
        response_check=lambda response: response.status_code == 200,
        poke_interval=60,
        mode="reschedule",
    )
    partner_report = HttpOperator(
        task_id="partner_report",
        http_conn_id="tally",
        method="POST",
        endpoint="internal/reports/{{ report_day(dag_run) }}",
        headers=HEADERS,
        log_response=True,
    )
    report_ready = HttpOperator(
        task_id="report_ready",
        http_conn_id="tally",
        method="POST",
        endpoint="internal/reports/{{ report_day(dag_run) }}/ready",
        headers=HEADERS,
        log_response=True,
    )
    wait_for_settlement >> partner_report >> report_ready
