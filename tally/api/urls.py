from django.urls import path

from tally.api.views import health

urlpatterns = [path("health", health, name="health")]
