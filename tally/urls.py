from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest
from django.urls import include, path, re_path


def console_index(request: HttpRequest) -> FileResponse:
    """SPA fallback: any path that is not an API route gets the console's index.html, so
    a deep link like /journal loads the app and Vue Router takes it from there."""
    index = settings.CONSOLE_DIST / "index.html"
    if not index.is_file():
        raise Http404("console not built; run `npm run build` in console/")
    return FileResponse(index.open("rb"), content_type="text/html")


urlpatterns = [
    path("", include("tally.api.urls")),
    re_path(
        r"^(?!api/|console/|internal/|webhooks/|assets/|openapi|docs|health).*$", console_index
    ),
]
