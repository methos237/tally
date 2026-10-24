import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection
from rest_framework.test import APIClient

from tally.adapters.models import ApiKey, Subscription, Tenant, WebhookEndpoint


class Idem(APIClient):
    """APIClient that sends a fresh Idempotency-Key on every POST unless one is given."""

    def post(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("HTTP_IDEMPOTENCY_KEY", uuid4().hex)
        return super().post(*args, **kwargs)

    def post_entry(self, *lines: tuple[str, str], key: str | None = None, **overrides: Any) -> Any:
        extra = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
        return self.post("/api/entries", entry_body(*lines, **overrides), format="json", **extra)


def client_for(api_key: str) -> Idem:
    client = Idem()
    client.credentials(HTTP_X_API_KEY=api_key)
    return client


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


def in_threads(n: int, body: Callable[[int], None]) -> None:
    """Run body(i) on n threads released together; each thread closes its DB connection."""
    barrier = threading.Barrier(n)

    def run(i: int) -> None:
        barrier.wait()
        try:
            body(i)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


@pytest.fixture
def api_key(tenant: Tenant) -> str:
    return ApiKey.issue(tenant, "test")


@pytest.fixture
def client(api_key: str) -> Idem:
    return client_for(api_key)


@pytest.fixture
def anon() -> APIClient:
    return APIClient()


@pytest.fixture
def other_tenant() -> Tenant:
    return Tenant.objects.create(name="other")


@pytest.fixture
def other_client(other_tenant: Tenant) -> Idem:
    """A second tenant's client, for the 404-not-403 tests."""
    return client_for(ApiKey.issue(other_tenant, "test"))


class Receiver:
    """A tenant's endpoint on localhost. Records every request; `status` is what it answers."""

    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, str], bytes]] = []
        self.status = 200
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                receiver.requests.append((dict(self.headers), body))
                self.send_response(receiver.status)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hooks"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    r = Receiver()
    yield r
    r.close()


@pytest.fixture
def endpoint(subscription: Subscription, receiver: Receiver) -> WebhookEndpoint:
    return WebhookEndpoint.objects.create(
        tenant=subscription.tenant, url=receiver.url, secret=WebhookEndpoint.new_secret()
    )
