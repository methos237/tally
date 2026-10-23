"""Inbound Stripe webhook. No API key: Stripe authenticates with its signature.

Verify, insert the event id, return 200, let Celery do the work. A duplicate delivery
hits the unique index and is acknowledged without being queued again.
"""

import json

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tally.adapters import stripe_gateway
from tally.adapters.models import StripeEvent
from tally.adapters.tasks import process_stripe_event


@csrf_exempt
@require_POST
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    try:
        event = stripe_gateway.verify(request.body, request.headers.get("Stripe-Signature"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    try:
        with transaction.atomic():
            row = StripeEvent.objects.create(
                event_id=event.id, type=event.type, payload=json.loads(request.body)
            )
    except IntegrityError:
        return JsonResponse({"received": True, "duplicate": True})
    process_stripe_event.delay(row.id)
    return JsonResponse({"received": True})
