import pytest
from django_redis import get_redis_connection
from rest_framework.test import APIClient

from tally.adapters import ratelimit
from tally.adapters.models import Tenant
from tally.api import throttle
from tally.api.problems import MEDIA_TYPE

T0 = 1_700_000_000_000


@pytest.fixture(autouse=True)
def flush_buckets() -> None:
    get_redis_connection("default").flushdb()


def test_bucket_allows_the_limit_then_denies_until_refill() -> None:
    decisions = [ratelimit.take("b", 100, T0) for _ in range(101)]
    assert all(d.allowed for d in decisions[:100])
    assert [d.remaining for d in decisions[:3]] == [99, 98, 97]
    denied = decisions[100]
    assert not denied.allowed and denied.remaining == 0
    assert denied.limit == 100 and denied.retry_after_seconds == 1 and denied.reset_seconds == 60

    # 600 ms later one token has refilled (100 per minute = 1 per 600 ms).
    assert ratelimit.take("b", 100, T0 + 600).allowed
    assert not ratelimit.take("b", 100, T0 + 600).allowed
    # Idle for a full minute: back to capacity, never above it.
    full = ratelimit.take("b", 100, T0 + 120_000)
    assert full.allowed and full.remaining == 99 and full.reset_seconds == 1


def test_buckets_are_independent_and_clock_is_an_input() -> None:
    assert ratelimit.take("x", 1, T0).allowed
    assert not ratelimit.take("x", 1, T0).allowed
    assert ratelimit.take("y", 1, T0).allowed
    # A clock that goes backwards never mints tokens.
    assert not ratelimit.take("x", 1, T0 - 10_000).allowed


@pytest.mark.django_db
def test_headers_on_success_and_429_problem_when_exhausted(
    client: APIClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant.rate_limit_per_minute = 2
    tenant.save()
    monkeypatch.setattr(throttle, "now_ms", lambda: T0)

    first = client.get("/api/me")
    assert first.status_code == 200
    assert (first["RateLimit-Limit"], first["RateLimit-Remaining"]) == ("2", "1")
    assert client.get("/api/me")["RateLimit-Remaining"] == "0"

    third = client.get("/api/me")
    assert third.status_code == 429
    assert third["Content-Type"] == MEDIA_TYPE
    assert third.json()["title"] == "Too Many Requests"
    assert third["Retry-After"] == "30"
    assert (third["RateLimit-Remaining"], third["RateLimit-Reset"]) == ("0", "60")

    monkeypatch.setattr(throttle, "now_ms", lambda: T0 + 30_000)
    assert client.get("/api/me").status_code == 200


@pytest.mark.django_db
def test_default_limit_comes_from_settings(client: APIClient, settings: object) -> None:
    settings.RATE_LIMIT_PER_MINUTE = 100  # type: ignore[attr-defined]
    assert client.get("/api/me")["RateLimit-Limit"] == "100"


@pytest.mark.django_db
def test_unauthenticated_routes_are_not_limited(anon: APIClient) -> None:
    response = anon.get("/openapi.json")
    assert response.status_code == 200 and "RateLimit-Limit" not in response
