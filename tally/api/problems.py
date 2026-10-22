"""RFC 9457 problem details: one exception type, one handler, one media type."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler

from tally.domain.journal import PostingError, UnbalancedEntry

MEDIA_TYPE = "application/problem+json"
TYPE_BASE = "https://tally.dev/problems/"


def slug(title: str) -> str:
    return title.lower().replace(" ", "-")


class Problem(Exception):
    """Raise anywhere under a DRF view; the handler renders it as problem+json.

    Title defaults to the HTTP reason phrase and type to its slug, so
    `Problem(404, "entry 7 not found")` is a complete problem on its own.
    """

    def __init__(
        self,
        status: int,
        detail: str = "",
        *,
        title: str | None = None,
        type: str | None = None,
        **extensions: Any,
    ) -> None:
        self.status = status
        self.title = title or HTTPStatus(status).phrase
        self.type = type or slug(self.title)
        self.detail = detail or self.title
        self.extensions = extensions
        super().__init__(self.detail)

    def body(self) -> dict[str, Any]:
        return {
            "type": TYPE_BASE + self.type,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            **self.extensions,
        }

    def to_response(self) -> Response:
        return Response(self.body(), status=self.status, content_type=MEDIA_TYPE)


def from_posting_error(exc: PostingError) -> Problem:
    extensions: dict[str, Any] = {}
    if isinstance(exc, UnbalancedEntry):
        extensions = {"currency": exc.currency.value, "difference": str(exc.difference.amount)}
    return Problem(
        422, str(exc), title="Entry rejected", type="posting/" + type(exc).__name__, **extensions
    )


def handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, Problem):
        return exc.to_response()
    if isinstance(exc, PostingError):
        return from_posting_error(exc).to_response()
    response = drf_handler(exc, context)
    if response is None:
        return None  # not an API error; let Django produce a 500
    # DRF already chose the status and headers (WWW-Authenticate, Retry-After, Allow);
    # only the body changes shape.
    if isinstance(exc, exceptions.ValidationError):
        problem = Problem(
            response.status_code, "Request body failed validation", errors=response.data
        )
    else:
        phrase = HTTPStatus(response.status_code).phrase
        problem = Problem(response.status_code, str(response.data.get("detail", phrase)))
    response.data = problem.body()
    response.content_type = MEDIA_TYPE
    return response
