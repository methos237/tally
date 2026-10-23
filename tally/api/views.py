"""Writes go through the application use cases; reads query the adapter models directly."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import connection
from django.db.models import QuerySet, Sum
from django.http import HttpRequest, JsonResponse
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tally.adapters import models, outbox
from tally.adapters.repositories import DjangoJournalRepository
from tally.api import serializers
from tally.api.auth import tenant_of
from tally.api.idempotency import HEADER as IDEMPOTENCY_KEY
from tally.api.idempotency import idempotent
from tally.api.problems import Problem
from tally.application.journal import AlreadyReversed, EntryNotFound, PostEntry, ReverseEntry
from tally.domain.journal import JournalEntry, Line
from tally.domain.money import Currency, Money


def health(_request: HttpRequest) -> JsonResponse:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


@api_view(["GET"])
def me(request: Request) -> Response:
    """Who am I: lets an integrator confirm a key before posting anything."""
    tenant = tenant_of(request)
    return Response({"tenant_id": tenant.id, "tenant": tenant.name})


class Cursor(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
    ordering = ("-occurred_at", "-id")


class AccountCursor(Cursor):
    ordering = ("code", "id")


def entries_of(tenant_id: int) -> QuerySet[models.JournalEntry]:
    return (
        models.JournalEntry.objects.filter(tenant_id=tenant_id)
        .select_related("reversed_by")
        .prefetch_related("lines__account")
    )


def entry_row(tenant_id: int, entry_id: int) -> models.JournalEntry:
    row = entries_of(tenant_id).filter(id=entry_id).first()
    if row is None:
        raise Problem(404, f"entry {entry_id} not found")
    return row


def created(tenant_id: int, entry: JournalEntry) -> Response:
    """201 with the stored entry. One re-read; the response shape is defined once."""
    assert entry.id is not None
    return Response(
        serializers.EntryOut(entry_row(tenant_id, entry.id)).data, status=status.HTTP_201_CREATED
    )


@extend_schema_view(
    get=extend_schema(
        parameters=[
            OpenApiParameter("source_type", str),
            OpenApiParameter("source_id", str),
            OpenApiParameter("account", str, description="account code"),
        ]
    )
)
class EntryList(generics.ListAPIView[models.JournalEntry]):
    serializer_class = serializers.EntryOut
    pagination_class = Cursor

    def get_queryset(self) -> QuerySet[models.JournalEntry]:
        tenant_id = tenant_of(self.request).id
        qs = entries_of(tenant_id)
        params = self.request.query_params
        for name in ("source_type", "source_id"):
            if value := params.get(name):
                qs = qs.filter(**{name: value})
        if code := params.get("account"):
            touching = models.JournalLine.objects.filter(tenant_id=tenant_id, account__code=code)
            qs = qs.filter(id__in=touching.values("entry_id"))
        return qs

    @extend_schema(request=serializers.EntryIn, responses={201: serializers.EntryOut})
    @idempotent
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = serializers.EntryIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        tenant_id = tenant_of(request).id

        codes = {line["account"] for line in data["lines"]}
        accounts = {
            a.code: a.id for a in models.Account.objects.filter(tenant_id=tenant_id, code__in=codes)
        }
        if missing := sorted(codes - accounts.keys()):
            raise Problem(
                422,
                f"accounts {missing} do not exist for this tenant",
                title="Entry rejected",
                type="posting/UnknownAccount",
                accounts=missing,
            )

        entry = JournalEntry(
            tenant_id=tenant_id,
            occurred_at=data["occurred_at"],
            source_type=data["source"]["type"],
            source_id=data["source"]["id"],
            idempotency_key=request.headers[IDEMPOTENCY_KEY],
            lines=tuple(
                Line(accounts[line["account"]], Money(line["amount"], Currency(line["currency"])))
                for line in data["lines"]
            ),
        )
        return created(tenant_id, PostEntry(DjangoJournalRepository())(entry))


class EntryDetail(APIView):
    @extend_schema(responses=serializers.EntryOut)
    def get(self, request: Request, entry_id: int) -> Response:
        return Response(serializers.EntryOut(entry_row(tenant_of(request).id, entry_id)).data)


class EntryReverse(APIView):
    @extend_schema(request=serializers.ReverseIn, responses={201: serializers.EntryOut})
    @idempotent
    def post(self, request: Request, entry_id: int) -> Response:
        body = serializers.ReverseIn(data=request.data)
        body.is_valid(raise_exception=True)
        tenant_id = tenant_of(request).id
        try:
            reversal = ReverseEntry(DjangoJournalRepository())(
                tenant_id,
                entry_id,
                body.validated_data.get("occurred_at"),
                idempotency_key=request.headers[IDEMPOTENCY_KEY],
            )
        except EntryNotFound as exc:
            raise Problem(404, str(exc)) from exc
        except AlreadyReversed as exc:
            raise Problem(409, str(exc), entry=entry_id) from exc
        return created(tenant_id, reversal)


class AccountList(generics.ListAPIView[models.Account]):
    serializer_class = serializers.AccountOut
    pagination_class = AccountCursor

    def get_queryset(self) -> QuerySet[models.Account]:
        return models.Account.objects.filter(tenant_id=tenant_of(self.request).id)


class AccountBalanceView(APIView):
    @extend_schema(
        parameters=[OpenApiParameter("as_of", datetime, description="ISO 8601; default: now")],
        responses=serializers.BalanceOut,
    )
    def get(self, request: Request, code: str) -> Response:
        account = (
            models.Account.objects.filter(tenant_id=tenant_of(request).id, code=code)
            .select_related("balance")
            .first()
        )
        if account is None:
            raise Problem(404, f"account {code} not found")
        raw = request.query_params.get("as_of")
        if raw is None:
            row = getattr(account, "balance", None)
            balance, as_of = (row.balance, row.as_of) if row else (Decimal(0), None)
        else:
            as_of = parse_datetime(raw)
            if as_of is None or as_of.tzinfo is None:
                raise Problem(422, "as_of must be an ISO 8601 datetime with timezone", as_of=raw)
            total = models.JournalLine.objects.filter(
                account=account, entry__occurred_at__lte=as_of
            ).aggregate(total=Sum("amount"))["total"]
            balance = total or Decimal(0)
        out = serializers.BalanceOut(
            {"account": code, "currency": account.currency, "balance": balance, "as_of": as_of}
        )
        return Response(out.data)


class WebhookEndpointList(generics.ListAPIView[models.WebhookEndpoint]):
    serializer_class = serializers.WebhookEndpointOut
    pagination_class = None

    def get_queryset(self) -> QuerySet[models.WebhookEndpoint]:
        return models.WebhookEndpoint.objects.filter(tenant_id=tenant_of(self.request).id).order_by(
            "id"
        )

    @extend_schema(
        request=serializers.WebhookEndpointIn, responses={201: serializers.WebhookEndpointCreated}
    )
    @idempotent
    def post(self, request: Request) -> Response:
        body = serializers.WebhookEndpointIn(data=request.data)
        body.is_valid(raise_exception=True)
        endpoint = models.WebhookEndpoint.objects.create(
            tenant_id=tenant_of(request).id,
            url=body.validated_data["url"],
            secret=models.WebhookEndpoint.new_secret(),
        )
        return Response(
            serializers.WebhookEndpointCreated(endpoint).data, status=status.HTTP_201_CREATED
        )


def endpoint_row(tenant_id: int, endpoint_id: int) -> models.WebhookEndpoint:
    row = models.WebhookEndpoint.objects.filter(tenant_id=tenant_id, id=endpoint_id).first()
    if row is None:
        raise Problem(404, f"webhook endpoint {endpoint_id} not found")
    return row


class DeadLetterList(generics.ListAPIView[models.OutboxMessage]):
    serializer_class = serializers.DeadLetterOut
    pagination_class = None

    def get_queryset(self) -> QuerySet[models.OutboxMessage]:
        endpoint = endpoint_row(tenant_of(self.request).id, self.kwargs["endpoint_id"])
        return endpoint.outbox.filter(dead_at__isnull=False).order_by("dead_at")


class DeadLetterRedeliver(APIView):
    @extend_schema(request=None, responses={202: serializers.DeadLetterOut})
    @idempotent
    def post(self, request: Request, endpoint_id: int, message_id: int) -> Response:
        endpoint = endpoint_row(tenant_of(request).id, endpoint_id)
        message = endpoint.outbox.filter(id=message_id, dead_at__isnull=False).first()
        if message is None:
            raise Problem(404, f"dead letter {message_id} not found on endpoint {endpoint_id}")
        outbox.redeliver(message)
        return Response(serializers.DeadLetterOut(message).data, status=status.HTTP_202_ACCEPTED)
