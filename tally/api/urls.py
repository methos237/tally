from datetime import date

from django.urls import path, register_converter
from django_prometheus.exports import ExportToDjangoView
from drf_spectacular.views import SpectacularJSONAPIView, SpectacularRedocView

from tally.api import console, internal, reconciliation, report_views, views, webhooks


class DateConverter:
    regex = r"\d{4}-\d{2}-\d{2}"

    def to_python(self, value: str) -> date:
        return date.fromisoformat(value)

    def to_url(self, value: date) -> str:
        return value.isoformat()


register_converter(DateConverter, "date")

urlpatterns = [
    path("health", views.health, name="health"),
    path("openapi.json", SpectacularJSONAPIView.as_view(), name="openapi"),
    path("docs", SpectacularRedocView.as_view(url_name="openapi"), name="docs"),
    path("console/session", console.session, name="console-session"),
    path("console/login", console.login_view, name="console-login"),
    path("console/logout", console.logout_view, name="console-logout"),
    path("api/me", views.me, name="me"),
    path("api/entries", views.EntryList.as_view(), name="entries"),
    path("api/entries/<int:entry_id>", views.EntryDetail.as_view(), name="entry"),
    path("api/entries/<int:entry_id>/reverse", views.EntryReverse.as_view(), name="entry-reverse"),
    path("api/accounts", views.AccountList.as_view(), name="accounts"),
    path("api/rates", views.RateList.as_view(), name="rates"),
    path("api/accounts/<str:code>/balance", views.AccountBalanceView.as_view(), name="balance"),
    path("api/subscriptions", views.SubscriptionList.as_view(), name="subscriptions"),
    path("api/invoices", views.InvoiceList.as_view(), name="invoices"),
    path("api/reports", report_views.ReportList.as_view(), name="reports"),
    path("api/reports/<date:day>", report_views.ReportDownload.as_view(), name="report-download"),
    path("api/webhook-endpoints", views.WebhookEndpointList.as_view(), name="webhook-endpoints"),
    path(
        "api/webhook-endpoints/<int:endpoint_id>/dead-letters",
        views.DeadLetterList.as_view(),
        name="dead-letters",
    ),
    path(
        "api/webhook-endpoints/<int:endpoint_id>/dead-letters/<int:message_id>/redeliver",
        views.DeadLetterRedeliver.as_view(),
        name="dead-letter-redeliver",
    ),
    path("api/statements", reconciliation.StatementList.as_view(), name="statements"),
    path(
        "api/statements/<int:statement_id>",
        reconciliation.StatementDetail.as_view(),
        name="statement",
    ),
    path(
        "api/statements/<int:statement_id>/reconcile",
        reconciliation.StatementReconcile.as_view(),
        name="statement-reconcile",
    ),
    path(
        "api/reconciliation-exceptions",
        reconciliation.ExceptionList.as_view(),
        name="reconciliation-exceptions",
    ),
    path(
        "api/reconciliation-exceptions/<int:exception_id>/resolve",
        reconciliation.ExceptionResolve.as_view(),
        name="reconciliation-exception-resolve",
    ),
    path("webhooks/stripe", webhooks.stripe_webhook, name="stripe-webhook"),
    path("internal/metrics", internal.internal(ExportToDjangoView), name="metrics"),
    path("internal/settlement/<date:day>", internal.settlement, name="internal-settlement"),
    path("internal/reports/<date:day>", internal.run_report, name="internal-report"),
    path("internal/reports/<date:day>/ready", internal.report_ready, name="internal-report-ready"),
]
