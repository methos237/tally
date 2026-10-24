"""Console session endpoints. Browser operators sign in with a Django session; every other
view then authenticates them through ConsoleSessionAuthentication as their tenant."""

from typing import Any

from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from tally.adapters.models import Operator
from tally.api.auth import ConsoleSessionAuthentication
from tally.api.problems import Problem
from tally.api.serializers import LoginIn, ProblemOut, SessionOut


@extend_schema(
    responses={200: SessionOut, 401: ProblemOut}, auth=[], description="Also sets the CSRF cookie."
)
@api_view(["GET"])
@authentication_classes([ConsoleSessionAuthentication])
@permission_classes([AllowAny])
def session(request: Request) -> Response:
    if request.auth is None:
        raise Problem(401, "Not signed in")
    return Response(SessionOut(request.auth).data)


session = ensure_csrf_cookie(session)  # the login form needs the token before any POST


@extend_schema(request=LoginIn, responses={200: SessionOut, 401: ProblemOut}, auth=[])
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def login_view(request: Request) -> Response:
    SessionAuthentication().enforce_csrf(request)  # login CSRF: the form must carry the token
    body = LoginIn(data=request.data)
    body.is_valid(raise_exception=True)
    user: Any = authenticate(request._request, **body.validated_data)
    operator = Operator.for_user(user) if user is not None else None
    if operator is None:
        raise Problem(401, "Wrong username or password")
    login(request._request, user)
    return Response(SessionOut(operator).data)


@extend_schema(request=None, responses={204: None})
@api_view(["POST"])
def logout_view(request: Request) -> Response:
    logout(request._request)
    return Response(status=status.HTTP_204_NO_CONTENT)
