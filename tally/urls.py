from django.urls import include, path

urlpatterns = [path("", include("tally.api.urls"))]
