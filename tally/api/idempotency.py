"""Idempotency-Key for write endpoints.

The record is claimed inside the same transaction as the business write and the
rendered response is stored before commit. Same key and same body: the stored
bytes are replayed with `Idempotent-Replayed: true`. Same key and a different
body: 422. Failed attempts are rolled back with the record, so a corrected retry
under the same key is accepted. Keys expire after `adapters.tasks.IDEMPOTENCY_TTL`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from functools import wraps
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseBase
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from tally.adapters.models import IdempotencyRecord
from tally.api.auth import tenant_of
from tally.api.problems import Problem

HEADER = "Idempotency-Key"
REPLAYED = "Idempotent-Replayed"

OPENAPI_PARAMETER = OpenApiParameter(
    HEADER,
    str,
    OpenApiParameter.HEADER,
    required=True,
    description="Unique per logical request; replays return the stored response.",
)


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


def idempotent(handler: Callable[..., Response]) -> Callable[..., HttpResponseBase]:
    """Wrap a DRF write handler; also documents the header in the OpenAPI schema."""

    @wraps(handler)
    def wrapper(self: Any, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        key = request.headers.get(HEADER)
        if not key:
            raise Problem(
                400, f"{HEADER} header is required on every write", type="idempotency-key-required"
            )
        tenant_id = tenant_of(request).id
        digest = request_hash(request)
        with transaction.atomic():
            record, created = claim(tenant_id, key, digest)
            if not created:
                if record.request_hash != digest:
                    raise Problem(
                        422,
                        f"{HEADER} {key!r} was already used with a different request body",
                        idempotency_key=key,
                    )
                # The stored bytes, not a re-rendering: byte-identical by construction.
                replay = HttpResponse(
                    record.response_body,
                    status=record.response_status,
                    content_type="application/json",
                )
                replay[REPLAYED] = "true"
                return replay
            response = handler(self, request, *args, **kwargs)
            record.response_status = response.status_code
            record.response_body = JSONRenderer().render(response.data).decode()
            record.save(update_fields=["response_status", "response_body"])
        return response

    return extend_schema(parameters=[OPENAPI_PARAMETER])(wrapper)
