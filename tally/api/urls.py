from django.urls import path
from drf_spectacular.views import SpectacularJSONAPIView, SpectacularRedocView

from tally.api import reconciliation, views, webhooks

urlpatterns = [
    path("health", views.health, name="health"),
    path("openapi.json", SpectacularJSONAPIView.as_view(), name="openapi"),
    path("docs", SpectacularRedocView.as_view(url_name="openapi"), name="docs"),
    path("api/me", views.me, name="me"),
    path("api/entries", views.EntryList.as_view(), name="entries"),
    path("api/entries/<int:entry_id>", views.EntryDetail.as_view(), name="entry"),
    path("api/entries/<int:entry_id>/reverse", views.EntryReverse.as_view(), name="entry-reverse"),
    path("api/accounts", views.AccountList.as_view(), name="accounts"),
    path("api/accounts/<str:code>/balance", views.AccountBalanceView.as_view(), name="balance"),
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
]
