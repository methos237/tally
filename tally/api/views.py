"""Writes go through the application use cases; reads query the adapter models directly."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import connection
from django.db.models import QuerySet, Sum
from django.http import HttpRequest, JsonResponse
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tally.adapters import models
from tally.adapters.repositories import DjangoJournalRepository
from tally.api import serializers
from tally.api.auth import principal
from tally.api.problems import Conflict, NotFound, Unprocessable
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
    who = principal(request)
    return Response({"tenant_id": who.tenant_id, "tenant": who.tenant_name})


class Cursor(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
    ordering = ("-occurred_at", "-id")


def entries_of(tenant_id: int) -> QuerySet[models.JournalEntry]:
    return (
        models.JournalEntry.objects.filter(tenant_id=tenant_id)
        .select_related("reversed_by")
        .prefetch_related("lines__account")
    )


def entry_row(tenant_id: int, entry_id: int) -> models.JournalEntry:
    row = entries_of(tenant_id).filter(id=entry_id).first()
    if row is None:
        raise NotFound(f"entry {entry_id} not found")
    return row


class EntryList(generics.ListCreateAPIView[models.JournalEntry]):
    serializer_class = serializers.EntryOut
    pagination_class = Cursor

    @extend_schema(
        parameters=[
            OpenApiParameter("source_type", str),
            OpenApiParameter("source_id", str),
            OpenApiParameter("account", str, description="account code"),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[models.JournalEntry]:
        qs = entries_of(principal(self.request).tenant_id)
        params = self.request.query_params
        for name in ("source_type", "source_id"):
            if value := params.get(name):
                qs = qs.filter(**{name: value})
        if code := params.get("account"):
            qs = qs.filter(lines__account__code=code).distinct()
        return qs

    @extend_schema(request=serializers.EntryIn, responses={201: serializers.EntryOut})
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = serializers.EntryIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        tenant_id = principal(request).tenant_id

        codes = {line["account"] for line in data["lines"]}
        accounts = {
            a.code: a.id for a in models.Account.objects.filter(tenant_id=tenant_id, code__in=codes)
        }
        for code in sorted(codes - accounts.keys()):
            raise Unprocessable(f"account {code} does not exist for this tenant", account=code)

        entry = JournalEntry(
            tenant_id=tenant_id,
            occurred_at=data["occurred_at"],
            source_type=data["source"]["type"],
            source_id=data["source"]["id"],
            lines=tuple(
                Line(accounts[line["account"]], Money(line["amount"], Currency(line["currency"])))
                for line in data["lines"]
            ),
        )
        saved = PostEntry(DjangoJournalRepository())(entry)
        assert saved.id is not None
        return Response(
            serializers.EntryOut(entry_row(tenant_id, saved.id)).data,
            status=status.HTTP_201_CREATED,
        )


class EntryDetail(APIView):
    @extend_schema(responses=serializers.EntryOut)
    def get(self, request: Request, entry_id: int) -> Response:
        return Response(
            serializers.EntryOut(entry_row(principal(request).tenant_id, entry_id)).data
        )


class EntryReverse(APIView):
    @extend_schema(request=serializers.ReverseIn, responses={201: serializers.EntryOut})
    def post(self, request: Request, entry_id: int) -> Response:
        body = serializers.ReverseIn(data=request.data)
        body.is_valid(raise_exception=True)
        tenant_id = principal(request).tenant_id
        try:
            reversal = ReverseEntry(DjangoJournalRepository())(
                tenant_id, entry_id, body.validated_data.get("occurred_at")
            )
        except EntryNotFound as exc:
            raise NotFound(str(exc)) from exc
        except AlreadyReversed as exc:
            raise Conflict(str(exc), entry=entry_id) from exc
        assert reversal.id is not None
        return Response(
            serializers.EntryOut(entry_row(tenant_id, reversal.id)).data,
            status=status.HTTP_201_CREATED,
        )


class AccountCursor(Cursor):
    ordering = ("code", "id")


class AccountList(generics.ListAPIView[models.Account]):
    serializer_class = serializers.AccountOut
    pagination_class = AccountCursor

    def get_queryset(self) -> QuerySet[models.Account]:
        return models.Account.objects.filter(tenant_id=principal(self.request).tenant_id)


class AccountBalanceView(APIView):
    @extend_schema(
        parameters=[OpenApiParameter("as_of", datetime, description="ISO 8601; default: now")],
        responses=serializers.BalanceOut,
    )
    def get(self, request: Request, code: str) -> Response:
        tenant_id = principal(request).tenant_id
        account = models.Account.objects.filter(tenant_id=tenant_id, code=code).first()
        if account is None:
            raise NotFound(f"account {code} not found")
        raw = request.query_params.get("as_of")
        if raw is None:
            row = models.AccountBalance.objects.filter(account=account).first()
            balance, as_of = (row.balance, row.as_of) if row else (Decimal(0), None)
        else:
            as_of = parse_datetime(raw)
            if as_of is None or as_of.tzinfo is None:
                raise Unprocessable("as_of must be an ISO 8601 datetime with timezone", as_of=raw)
            total = models.JournalLine.objects.filter(
                account=account, entry__occurred_at__lte=as_of
            ).aggregate(total=Sum("amount"))["total"]
            balance = total or Decimal(0)
        out = serializers.BalanceOut(
            {"account": code, "currency": account.currency, "balance": balance, "as_of": as_of}
        )
        return Response(out.data)
