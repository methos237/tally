"""console/openapi.json is what the console's typed client is generated from.
It is committed so the console CI needs no backend; this test keeps it current."""

import json
from pathlib import Path

import pytest
from rest_framework.test import APIClient

COMMITTED = Path(__file__).parents[2] / "console" / "openapi.json"


@pytest.mark.django_db
def test_committed_openapi_matches_the_served_schema(anon: APIClient) -> None:
    served = anon.get("/openapi.json").json()
    assert json.loads(COMMITTED.read_text()) == served, "run `make openapi` and commit the result"
