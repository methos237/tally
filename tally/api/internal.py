"""Endpoints for the orchestrator, not for tenants. Guarded by X-Internal-Token.

Airflow's DAG is three HTTP calls: wait for the settlement marker, run the report,
announce it. Everything it needs lives here so the Airflow image stays stock.
"""

import hmac
from collections.abc import Callable
from datetime import date
from functools import wraps
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from tally.adapters import reports
from tally.adapters.models import SettlementMarker

HEADER = "X-Internal-Token"


def internal(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @csrf_exempt
    @wraps(view)
    def guarded(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        presented = request.headers.get(HEADER, "")
        if not hmac.compare_digest(presented, settings.INTERNAL_TOKEN):
            return JsonResponse({"error": f"{HEADER} missing or wrong"}, status=401)
        return view(request, *args, **kwargs)

    return guarded


@internal
@require_http_methods(["GET", "POST"])
def settlement(request: HttpRequest, day: date) -> HttpResponse:
    """GET: 200 when the day is settled, 404 until then. POST: settle it by hand."""
    if request.method == "POST":
        marker, _ = SettlementMarker.objects.get_or_create(day=day)
        return JsonResponse({"day": day, "settled_at": marker.settled_at})
    existing = SettlementMarker.objects.filter(day=day).first()
    if existing is None:
        return JsonResponse({"day": day, "settled": False}, status=404)
    return JsonResponse({"day": day, "settled": True, "settled_at": existing.settled_at})


@internal
@require_http_methods(["POST"])
def run_report(request: HttpRequest, day: date) -> HttpResponse:
    """Write the day's CSV for every tenant; returns the object keys."""
    keys = reports.write_all(day)
    return JsonResponse({"day": day, "bucket": settings.S3_BUCKET, "keys": keys})


@internal
@require_http_methods(["POST"])
def report_ready(request: HttpRequest, day: date) -> HttpResponse:
    """Queue report.ready for every tenant's webhook endpoints."""
    return JsonResponse({"day": day, "notified": reports.notify_all(day)})
