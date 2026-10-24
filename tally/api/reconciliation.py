"""Statements and reconciliation exceptions. Upload is the raw CSV body (text/csv)."""

from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, parsers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tally.adapters import models, reconciliation
from tally.api import serializers
from tally.api.auth import tenant_of
from tally.api.idempotency import idempotent
from tally.api.problems import Problem


class CsvParser(parsers.BaseParser):
    media_type = "text/csv"

    def parse(self, stream, media_type=None, parser_context=None):  # type: ignore[no-untyped-def]
        return stream.read().decode("utf-8-sig")


def statement_row(tenant_id: int, statement_id: int) -> models.Statement:
    row = models.Statement.objects.filter(tenant_id=tenant_id, id=statement_id).first()
    if row is None:
        raise Problem(404, f"statement {statement_id} not found")
    return row


def detail(tenant_id: int, statement_id: int, code: int = 200) -> Response:
    row = statement_row(tenant_id, statement_id)
    full = models.Statement.objects.prefetch_related("lines", "exceptions__line").get(id=row.id)
    return Response(serializers.StatementOut(full).data, status=code)


class StatementList(APIView):
    parser_classes = [CsvParser]

    @extend_schema(responses=serializers.StatementSummaryOut(many=True))
    def get(self, request: Request) -> Response:
        rows = models.Statement.objects.filter(tenant_id=tenant_of(request).id).order_by(
            "-uploaded_at", "-id"
        )
        return Response(serializers.StatementSummaryOut(rows, many=True).data)

    @extend_schema(
        request={"text/csv": {"type": "string"}}, responses={201: serializers.StatementOut}
    )
    @idempotent
    def post(self, request: Request) -> Response:
        tenant_id = tenant_of(request).id
        try:
            statement = reconciliation.import_statement(tenant_id, str(request.data))
        except reconciliation.BadStatement as exc:
            raise Problem(422, str(exc), title="Statement rejected") from exc
        except models.Account.DoesNotExist:
            raise Problem(
                422, "tenant has no cash account 1000", title="Statement rejected"
            ) from None
        return detail(tenant_id, statement.id, status.HTTP_201_CREATED)


class StatementDetail(APIView):
    @extend_schema(responses=serializers.StatementOut)
    def get(self, request: Request, statement_id: int) -> Response:
        return detail(tenant_of(request).id, statement_id)


class StatementReconcile(APIView):
    @extend_schema(request=None, responses=serializers.StatementOut)
    @idempotent
    def post(self, request: Request, statement_id: int) -> Response:
        tenant_id = tenant_of(request).id
        reconciliation.reconcile(statement_row(tenant_id, statement_id), timezone.now())
        return detail(tenant_id, statement_id)


@extend_schema(
    parameters=[
        OpenApiParameter("status", str, enum=["open", "resolved"]),
        OpenApiParameter("statement", int),
    ]
)
class ExceptionList(generics.ListAPIView[models.ReconciliationException]):
    serializer_class = serializers.ExceptionOut
    pagination_class = None

    def get_queryset(self) -> QuerySet[models.ReconciliationException]:
        qs = models.ReconciliationException.objects.filter(
            tenant_id=tenant_of(self.request).id
        ).select_related("line")
        params = self.request.query_params
        if params.get("status") == "open":
            qs = qs.filter(resolved_at__isnull=True)
        elif params.get("status") == "resolved":
            qs = qs.filter(resolved_at__isnull=False)
        if statement := params.get("statement"):
            qs = qs.filter(statement_id=statement)
        return qs.order_by("id")


class ExceptionResolve(APIView):
    @extend_schema(request=serializers.ResolveIn, responses=serializers.ExceptionOut)
    @idempotent
    def post(self, request: Request, exception_id: int) -> Response:
        body = serializers.ResolveIn(data=request.data)
        body.is_valid(raise_exception=True)
        row = (
            models.ReconciliationException.objects.filter(
                tenant_id=tenant_of(request).id, id=exception_id
            )
            .select_related("line", "statement")
            .first()
        )
        if row is None:
            raise Problem(404, f"reconciliation exception {exception_id} not found")
        if row.resolved_at is not None:
            raise Problem(409, f"exception {exception_id} is already {row.resolution}")
        now = timezone.now()
        if body.validated_data["action"] == "adjust":
            account = body.validated_data["account"]
            try:
                reconciliation.adjust(row, account, now)
            except LookupError:
                raise Problem(
                    422,
                    f"accounts ['{account}'] do not exist for this tenant",
                    title="Entry rejected",
                    type="posting/UnknownAccount",
                    accounts=[account],
                ) from None
        else:
            reconciliation.explain(row, body.validated_data["explanation"], now)
        return Response(serializers.ExceptionOut(row).data)
