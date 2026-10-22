"""Per-API-key rate limiting: a DRF throttle that records its decision on the
request so RateLimitHeadersMiddleware can put RateLimit-* headers on the response."""

import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from rest_framework.request import Request
from rest_framework.throttling import BaseThrottle

from tally.adapters import ratelimit
from tally.adapters.models import ApiKey


def now_ms() -> int:
    return int(time.time() * 1000)


class ApiKeyTokenBucket(BaseThrottle):
    def allow_request(self, request: Request, view: Any) -> bool:
        key = request.auth
        if not isinstance(key, ApiKey):
            return True  # unauthenticated routes (openapi, docs) are not limited here
        limit = key.tenant.rate_limit_per_minute or settings.RATE_LIMIT_PER_MINUTE
        decision = ratelimit.take(f"ratelimit:key:{key.id}", limit, now_ms())
        request._request.rate_limit = decision  # type: ignore[attr-defined]
        self.decision = decision
        return decision.allowed

    def wait(self) -> float:
        return float(self.decision.retry_after_seconds)


class RateLimitHeadersMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        decision = getattr(request, "rate_limit", None)
        if decision is not None:
            response["RateLimit-Limit"] = str(decision.limit)
            response["RateLimit-Remaining"] = str(decision.remaining)
            response["RateLimit-Reset"] = str(decision.reset_seconds)
        return response
