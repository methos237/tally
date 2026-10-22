"""RFC 9457 problem details: one exception type, one handler, one media type."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response

from tally.domain.journal import PostingError, UnbalancedEntry

MEDIA_TYPE = "application/problem+json"
TYPE_BASE = "https://tally.dev/problems/"


class Problem(Exception):
    """Raise anywhere under a DRF view; the handler renders it as problem+json."""

    status: int = status.HTTP_400_BAD_REQUEST
    title: str = "Bad Request"
    type: str = "bad-request"

    def __init__(self, detail: str = "", **extensions: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extensions = extensions

    def to_response(self) -> Response:
        return problem_response(self.status, self.title, self.detail, self.type, **self.extensions)


class NotFound(Problem):
    status, title, type = status.HTTP_404_NOT_FOUND, "Not Found", "not-found"


class Conflict(Problem):
    status, title, type = status.HTTP_409_CONFLICT, "Conflict", "conflict"


class Unprocessable(Problem):
    status, title, type = status.HTTP_422_UNPROCESSABLE_ENTITY, "Unprocessable", "unprocessable"


def problem_response(
    status_code: int, title: str, detail: str, type_: str, **extensions: Any
) -> Response:
    body = {"type": TYPE_BASE + type_, "title": title, "status": status_code, "detail": detail}
    body.update(extensions)
    return Response(body, status=status_code, content_type=MEDIA_TYPE)


def from_posting_error(exc: PostingError) -> Response:
    extensions: dict[str, Any] = {}
    if isinstance(exc, UnbalancedEntry):
        extensions = {"currency": exc.currency.value, "difference": str(exc.difference.amount)}
    return problem_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Entry rejected",
        str(exc),
        "posting/" + type(exc).__name__,
        **extensions,
    )


def handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, Problem):
        response = exc.to_response()
    elif isinstance(exc, PostingError):
        response = from_posting_error(exc)
    else:
        # Imported here: rest_framework.views imports the settings, which import this module.
        from rest_framework.views import exception_handler as drf_handler

        drf_response = drf_handler(exc, context)
        if drf_response is None:
            return None  # not an API error; let Django produce a 500
        if isinstance(exc, Http404):
            exc = exceptions.NotFound()
        phrase = HTTPStatus(drf_response.status_code).phrase
        if isinstance(exc, exceptions.ValidationError):
            detail, extensions = "Request body failed validation", {"errors": drf_response.data}
        else:
            detail, extensions = str(getattr(exc, "detail", phrase)), {}
        response = problem_response(
            drf_response.status_code, phrase, detail, phrase.lower().replace(" ", "-"), **extensions
        )
        for key, value in drf_response.headers.items():
            if key.lower() not in ("content-type", "content-length"):
                response[key] = value
    return response
