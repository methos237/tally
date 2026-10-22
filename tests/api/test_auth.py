from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from tally.adapters.models import ApiKey, Tenant

PROBLEM = "application/problem+json"


@pytest.mark.django_db
def test_valid_key_resolves_the_tenant(client: APIClient, tenant: Tenant) -> None:
    response = client.get("/api/me")
    assert response.status_code == 200
    assert response.json() == {"tenant_id": tenant.id, "tenant": "acme"}


@pytest.mark.django_db
def test_missing_key_is_401_problem_details(anon: APIClient) -> None:
    response = anon.get("/api/me")
    assert response.status_code == 401
    assert response["Content-Type"] == PROBLEM
    assert response["WWW-Authenticate"] == "X-Api-Key"
    assert response.json() == {
        "type": "https://tally.dev/problems/unauthorized",
        "title": "Unauthorized",
        "status": 401,
        "detail": "Missing X-Api-Key header",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("bad", ["", "nope", "tk_", "tk_wrongprefix000000", "sk_test_123"])
def test_unknown_key_is_401(anon: APIClient, api_key: str, bad: str) -> None:
    anon.credentials(HTTP_X_API_KEY=bad or api_key[:-1] + ("a" if api_key[-1] != "a" else "b"))
    response = anon.get("/api/me")
    assert response.status_code == 401
    assert response.json()["detail"] in ("Unknown or revoked API key", "Missing X-Api-Key header")


@pytest.mark.django_db
def test_revoked_key_is_401(client: APIClient, tenant: Tenant) -> None:
    ApiKey.objects.filter(tenant=tenant).update(revoked_at=timezone.now())
    assert client.get("/api/me").status_code == 401


@pytest.mark.django_db
def test_secret_is_hashed_with_argon2_and_only_the_prefix_is_stored(
    api_key: str, tenant: Tenant
) -> None:
    row = ApiKey.objects.get(tenant=tenant)
    assert row.key_hash.startswith("argon2")
    assert api_key not in row.key_hash
    assert api_key.startswith("tk_" + row.prefix)
    assert len(row.prefix) == 8


@pytest.mark.django_db
def test_issue_api_key_command_prints_the_key_once(tenant: Tenant) -> None:
    out = StringIO()
    call_command("issue_api_key", "--tenant", "acme", "--name", "ci", stdout=out)
    plaintext = out.getvalue().strip()
    key = ApiKey.authenticate(plaintext)
    assert key is not None and key.tenant == tenant and key.name == "ci"


@pytest.mark.django_db
def test_wrong_method_is_problem_details_too(client: APIClient) -> None:
    response = client.post("/api/me", {}, format="json")
    assert response.status_code == 405
    assert response["Content-Type"] == PROBLEM
    assert response.json()["status"] == 405
    assert "GET" in response["Allow"]
    assert response.json()["title"] == "Method Not Allowed"
