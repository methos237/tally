"""Row-level security: a second tenancy wall beneath the repositories.

Every tenant table carries `tenant_id`; the repositories filter by it (first wall). Postgres
policies on the same tables (second wall) only let a connection see and write rows of the
tenant it is bound to. Binding is a session setting, `tally.tenant_id`, set by the API
authentication classes once the tenant is known and reset by the middleware when the
request ends. A connection with no binding (Celery, management commands, the internal
endpoints) sees every tenant, as those callers must.

Superusers and, without FORCE, table owners bypass RLS; in compose and CI the app connects
as the superuser that owns everything. Binding therefore also switches to `tally_app`, a
plain role the migration creates and grants, so the policies apply whoever connected.
"""

from collections.abc import Callable

from django.db import connection
from django.http import HttpRequest, HttpResponse

SETTING = "tally.tenant_id"
ROLE = "tally_app"

TABLES = [
    "accounts",
    "account_balances",
    "api_keys",
    "customers",
    "exchange_rates",
    "idempotency_records",
    "invoices",
    "journal_entries",
    "journal_lines",
    "operators",
    "plans",
    "reconciliation_exceptions",
    "statement_lines",
    "statements",
    "subscriptions",
    "webhook_endpoints",
    "webhook_outbox",
]

FUNCTION = f"""
CREATE OR REPLACE FUNCTION tally_bound_tenant() RETURNS bigint STABLE LANGUAGE sql AS $$
  SELECT nullif(current_setting('{SETTING}', true), '')::bigint
$$;
"""


ROLE_SQL = f"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
    CREATE ROLE {ROLE} NOLOGIN;
  END IF;
END $$;
GRANT {ROLE} TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO {ROLE};
GRANT ALL ON ALL TABLES IN SCHEMA public TO {ROLE};
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {ROLE};
"""


def enable_sql() -> str:
    rule = "(tally_bound_tenant() IS NULL OR tenant_id = tally_bound_tenant())"
    statements = [ROLE_SQL, FUNCTION]
    for table in TABLES:
        statements.append(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n"
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;\n"
            f"CREATE POLICY tenant_wall ON {table} USING {rule} WITH CHECK {rule};"
        )
    return "\n".join(statements)


def disable_sql() -> str:
    statements = [
        f"DROP POLICY IF EXISTS tenant_wall ON {table};\n"
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;"
        for table in TABLES
    ]
    statements.append("DROP FUNCTION IF EXISTS tally_bound_tenant();")
    return "\n".join(statements)


def bind(tenant_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {ROLE}")
        cursor.execute("SELECT set_config(%s, %s, false)", [SETTING, str(tenant_id)])


def unbind() -> None:
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
        cursor.execute("SELECT set_config(%s, '', false)", [SETTING])


def bound_tenant() -> int | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT tally_bound_tenant()")
        value = cursor.fetchone()[0]
        return int(value) if value is not None else None


class RowLevelSecurityMiddleware:
    """Whatever the request bound, the connection gives back before it is reused."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            return self.get_response(request)
        finally:
            if connection.connection is not None and not connection.needs_rollback:
                unbind()
