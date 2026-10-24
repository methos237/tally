"""Console sessions: an Operator signs in with a Django session and acts as its tenant."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from tally.adapters.models import Operator, Tenant
from tally.api.problems import MEDIA_TYPE


@pytest.fixture
def operator(tenant: Tenant) -> Operator:
    user = get_user_model().objects.create_user("ops", password="pw")
    return Operator.objects.create(user=user, tenant=tenant)


@pytest.fixture
def browser() -> APIClient:
    return APIClient(enforce_csrf_checks=True)


def sign_in(browser: APIClient, password: str = "pw") -> object:
    token = browser.get("/console/session").cookies["csrftoken"].value
    return browser.post(
        "/console/login",
        {"username": "ops", "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )


@pytest.mark.django_db
def test_session_endpoint_sets_the_csrf_cookie_and_is_401_when_signed_out(
    browser: APIClient,
) -> None:
    response = browser.get("/console/session")
    assert response.status_code == 401
    assert response["Content-Type"] == MEDIA_TYPE
    assert "csrftoken" in response.cookies


@pytest.mark.django_db
def test_login_without_csrf_token_is_403(browser: APIClient, operator: Operator) -> None:
    response = browser.post("/console/login", {"username": "ops", "password": "pw"}, format="json")
    assert response.status_code == 403
    assert response["Content-Type"] == MEDIA_TYPE


@pytest.mark.django_db
def test_login_then_session_then_api_as_the_tenant(
    browser: APIClient, operator: Operator, tenant: Tenant
) -> None:
    response = sign_in(browser)
    assert response.status_code == 200
    expected = {"username": "ops", "tenant_id": tenant.id, "tenant": tenant.name}
    assert response.json() == expected
    assert browser.get("/console/session").json() == expected
    # The session is the tenant's credential for the whole API, no X-Api-Key needed.
    assert browser.get("/api/me").json() == {"tenant_id": tenant.id, "tenant": tenant.name}
    assert "RateLimit-Limit" not in browser.get("/api/accounts")


@pytest.mark.django_db
def test_wrong_password_is_401(browser: APIClient, operator: Operator) -> None:
    response = sign_in(browser, password="nope")
    assert response.status_code == 401
    assert response.json()["detail"] == "Wrong username or password"


@pytest.mark.django_db
def test_a_django_user_without_an_operator_row_cannot_sign_in(
    browser: APIClient, tenant: Tenant
) -> None:
    get_user_model().objects.create_user("ops", password="pw")
    assert sign_in(browser).status_code == 401
    assert browser.get("/api/me").status_code == 401


@pytest.mark.django_db
def test_unsafe_api_call_from_a_session_needs_the_csrf_token(
    browser: APIClient, operator: Operator
) -> None:
    sign_in(browser)
    response = browser.post("/api/entries", {}, format="json")
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    token = browser.cookies["csrftoken"].value
    response = browser.post("/api/entries", {}, format="json", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 400  # past CSRF; the empty body fails validation


@pytest.mark.django_db
def test_logout_ends_the_session(browser: APIClient, operator: Operator) -> None:
    sign_in(browser)
    token = browser.cookies["csrftoken"].value
    assert browser.post("/console/logout", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert browser.get("/console/session").status_code == 401
    assert browser.get("/api/me").status_code == 401


@pytest.mark.django_db
def test_openapi_documents_the_session_scheme(anon: APIClient) -> None:
    doc = anon.get("/openapi.json").json()
    assert doc["components"]["securitySchemes"]["SessionAuth"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "sessionid",
    }
    assert {"/console/session", "/console/login", "/console/logout"} <= set(doc["paths"])
