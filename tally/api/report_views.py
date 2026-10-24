"""The partner daily reports a tenant can download: CSV objects in the S3 bucket under
`<tenant_id>/<day>.csv`, listed and streamed through the API so the bucket stays private."""

from datetime import date

from botocore.exceptions import ClientError
from django.conf import settings
from django.http import HttpResponse, StreamingHttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tally.adapters import reports
from tally.api import serializers
from tally.api.auth import tenant_of
from tally.api.problems import Problem


class ReportList(APIView):
    @extend_schema(responses=serializers.ReportOut(many=True))
    def get(self, request: Request) -> Response:
        prefix = reports.prefix_for(tenant_of(request))
        try:
            listing = reports.s3().list_objects_v2(Bucket=settings.S3_BUCKET, Prefix=prefix)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "NoSuchBucket":
                raise
            listing = {}
        rows = [
            {
                "day": reports.day_of(obj["Key"]),
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"],
            }
            for obj in listing.get("Contents", [])
            if obj["Key"].endswith(".csv")
        ]
        rows.sort(key=lambda r: r["day"], reverse=True)
        return Response(serializers.ReportOut(rows, many=True).data)


class ReportDownload(APIView):
    @extend_schema(responses={200: OpenApiResponse(description="text/csv")})
    def get(self, request: Request, day: date) -> HttpResponse | StreamingHttpResponse:
        key = reports.key_for(tenant_of(request), day)
        try:
            obj = reports.s3().get_object(Bucket=settings.S3_BUCKET, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "NoSuchBucket"):
                raise Problem(404, f"no report for {day.isoformat()}") from exc
            raise
        response = StreamingHttpResponse(obj["Body"].iter_chunks(), content_type="text/csv")
        response["Content-Length"] = str(obj["ContentLength"])
        response["Content-Disposition"] = f'attachment; filename="{day.isoformat()}.csv"'
        return response
