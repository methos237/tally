from django.db import connection
from django.http import HttpRequest, JsonResponse
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from tally.api.auth import principal


def health(_request: HttpRequest) -> JsonResponse:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


@api_view(["GET"])
def me(request: Request) -> Response:
    """Who am I: lets an integrator confirm a key before posting anything."""
    who = principal(request)
    return Response({"tenant_id": who.tenant_id, "tenant": who.tenant_name})
