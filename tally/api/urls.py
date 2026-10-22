from django.urls import path

from tally.api.views import health, me

urlpatterns = [
    path("health", health, name="health"),
    path("api/me", me, name="me"),
]
