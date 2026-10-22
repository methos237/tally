from typing import Any

import pytest
from rest_framework.test import APIClient

from tally.adapters.models import Account, ApiKey, Tenant


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="acme")


@pytest.fixture
def api_key(tenant: Tenant) -> str:
    _, plaintext = ApiKey.issue(tenant, "test")
    return plaintext


@pytest.fixture
def client(api_key: str) -> APIClient:
    """An APIClient already carrying the tenant's X-Api-Key."""
    return Idem(api_key)


class Idem(APIClient):
    """APIClient carrying the key and a fresh Idempotency-Key per POST unless one is given."""

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self.credentials(HTTP_X_API_KEY=api_key)
        self.counter = 0

    def post(self, *args: Any, **kwargs: Any) -> Any:
        if "HTTP_IDEMPOTENCY_KEY" not in kwargs and "headers" not in kwargs:
            self.counter += 1
            kwargs["HTTP_IDEMPOTENCY_KEY"] = f"auto-{self.counter}"
        return super().post(*args, **kwargs)


@pytest.fixture
def anon() -> APIClient:
    return APIClient()


@pytest.fixture
def ledger(tenant: Tenant) -> tuple[Tenant, Account, Account]:
    ar = Account.objects.create(tenant=tenant, code="1200", name="AR", type="asset", currency="USD")
    rev = Account.objects.create(
        tenant=tenant, code="4000", name="Revenue", type="revenue", currency="USD"
    )
    return tenant, ar, rev


@pytest.fixture
def other_client() -> APIClient:
    """A second tenant's client, for the 404-not-403 tests."""
    other = Tenant.objects.create(name="other")
    _, plaintext = ApiKey.issue(other, "test")
    return Idem(plaintext)


def entry_body(
    *lines: tuple[str, str], currency: str = "USD", **overrides: object
) -> dict[str, object]:
    body: dict[str, object] = {
        "occurred_at": "2026-11-03T14:02:00Z",
        "source": {"type": "invoice", "id": "inv_1042"},
        "lines": [
            {"account": code, "amount": amount, "currency": currency} for code, amount in lines
        ],
    }
    body.update(overrides)
    return body
