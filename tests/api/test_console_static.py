"""The built console is served by Django: whitenoise for the files, an index.html fallback
for the SPA's routes, and API routes untouched."""

from pathlib import Path

import pytest
from django.test import Client


@pytest.fixture
def dist(settings, tmp_path: Path) -> Path:  # type: ignore[no-untyped-def]
    (tmp_path / "index.html").write_text("<!doctype html><title>Tally</title>")
    settings.CONSOLE_DIST = tmp_path
    return tmp_path


@pytest.mark.django_db
def test_deep_links_get_the_index(dist: Path) -> None:
    for route in ("/journal", "/reconciliation"):
        response = Client().get(route)
        assert response.status_code == 200, route
        assert b"<title>Tally</title>" in b"".join(response.streaming_content)
    root = Client().get("/")  # whitenoise's index file when built, the fallback otherwise
    assert root.status_code == 200 and root["Content-Type"].startswith("text/html")


@pytest.mark.django_db
def test_api_and_console_routes_are_not_swallowed(dist: Path) -> None:
    assert Client().get("/api/nope").status_code == 404
    assert Client().get("/api/me").status_code == 401
    assert Client().get("/console/session").status_code == 401
    assert Client().get("/health").status_code == 200


@pytest.mark.django_db
def test_without_a_build_the_fallback_is_404(settings, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings.CONSOLE_DIST = tmp_path / "missing"
    assert Client().get("/journal").status_code == 404
