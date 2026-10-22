"""Idempotency-Key for write endpoints.

The record is claimed inside the same transaction as the business write and the
response is stored before commit. Same key and same body: the stored response is
replayed with `Idempotent-Replayed: true`. Same key and a different body: 422.
Failed attempts are rolled back with the record, so a corrected retry under the
same key is accepted. Keys expire after 24 hours (adapters.tasks.expire_idempotency).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from functools import wraps
from typing import Any

from django.db import IntegrityError, transaction
from drf_spectacular.utils import OpenApiParameter
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from tally.adapters.models import IdempotencyRecord
from tally.api.auth import principal
from tally.api.problems import Problem, Unprocessable

HEADER = "Idempotency-Key"
REPLAYED = "Idempotent-Replayed"
TTL_HOURS = 24

OPENAPI_PARAMETER = OpenApiParameter(
    HEADER,
    str,
    OpenApiParameter.HEADER,
    required=True,
    description="Unique per logical request; replays return the stored response.",
)


class IdempotencyKeyRequired(Problem):
    status, title, type = status.HTTP_400_BAD_REQUEST, "Bad Request", "idempotency-key-required"


def request_hash(request: Request) -> str:
    canonical = json.dumps(
        [request.method, request.path, request.data], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def claim(tenant_id: int, key: str, digest: str) -> tuple[IdempotencyRecord, bool]:
    """Insert the record or, if the key exists, lock and return it.

    A concurrent request with the same key blocks on the unique index until the
    first transaction commits, then lands in the except branch and replays.
    """
    try:
        with transaction.atomic():
            return IdempotencyRecord.objects.create(
                tenant_id=tenant_id, key=key, request_hash=digest
            ), True
    except IntegrityError:
        return IdempotencyRecord.objects.select_for_update().get(
            tenant_id=tenant_id, key=key
        ), False


Handler = Callable[..., Response]


def idempotent(handler: Handler) -> Handler:
    """Wrap a DRF write handler. Must run inside authentication (after `initial`)."""

    @wraps(handler)
    def wrapper(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
        key = request.headers.get(HEADER)
        if not key:
            raise IdempotencyKeyRequired(f"{HEADER} header is required on every write")
        tenant_id = principal(request).tenant_id
        digest = request_hash(request)
        with transaction.atomic():
            record, created = claim(tenant_id, key, digest)
            if not created:
                if record.request_hash != digest:
                    raise Unprocessable(
                        f"{HEADER} {key!r} was already used with a different request body",
                        idempotency_key=key,
                    )
                replay = Response(record.response_body, status=record.response_status)
                replay[REPLAYED] = "true"
                return replay
            response = handler(self, request, *args, **kwargs)
            record.response_status = response.status_code
            record.response_body = response.data
            record.save(update_fields=["response_status", "response_body"])
        return response

    return wrapper
