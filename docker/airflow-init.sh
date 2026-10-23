#!/usr/bin/env bash
# Create the `airflow` metadata database on the shared Postgres if missing, then hand
# over to `airflow standalone`, which migrates it and runs every Airflow component.
set -euo pipefail
python - <<'PY'
import os, psycopg2
conn = psycopg2.connect(os.environ["TALLY_DATABASE_URL"])
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = 'airflow'")
if cur.fetchone() is None:
    cur.execute("CREATE DATABASE airflow")
    print("created database airflow")
PY
exec airflow standalone
