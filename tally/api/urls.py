from django.urls import path
from drf_spectacular.views import SpectacularJSONAPIView, SpectacularRedocView

from tally.api import views

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
]
