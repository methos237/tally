from django.conf import settings
from django.http import HttpRequest, HttpResponseBase
from django.urls import include, path, re_path
from django.views.static import serve


def console_index(request: HttpRequest) -> HttpResponseBase:
    """SPA fallback: any path that is not an API route gets the console's index.html, so
    a deep link like /journal loads the app and Vue Router takes it from there.
    404 until `npm run build` has run in console/."""
    return serve(request, "index.html", document_root=str(settings.CONSOLE_DIST))


urlpatterns = [
    path("", include("tally.api.urls")),
    re_path(
        r"^(?!api/|console/|internal/|webhooks/|assets/|openapi|docs|health).*$",
        console_index,
    ),
]
