"""OpenTelemetry setup: one tracer provider, OTLP/HTTP export when
OTEL_EXPORTER_OTLP_ENDPOINT is set (the SDK reads it and appends /v1/traces), and
auto-instrumentation for Django, psycopg, Redis, urllib (outbound webhooks) and Celery.

Called once per process from ApiConfig.ready(), so the Django server and the Celery worker
(which also runs django.setup()) configure themselves the same way. Tests leave the
endpoint unset and attach an in-memory exporter to the same provider.
"""

import os
import sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def exports_spans(argv: list[str]) -> bool:
    """Only the processes that produce spans export them: the Django server and the Celery
    worker. One-shot management commands and Beat would otherwise each start an exporter
    thread and block at exit flushing to a collector that may be down."""
    if argv[0].endswith("manage.py"):
        return argv[1:2] == ["runserver"]
    if argv[0].endswith("celery"):
        return "worker" in argv
    return True  # wsgi/asgi servers


def configure() -> None:
    # Sampling comes from the SDK's own env: OTEL_TRACES_SAMPLER=parentbased_traceidratio and
    # OTEL_TRACES_SAMPLER_ARG=0.1 keep one request in ten once volume matters; default is all.
    provider = TracerProvider(resource=Resource.create({"service.name": "tally"}))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") and exports_spans(sys.argv):
        # ponytail: BatchSpanProcessor's thread does not survive a prefork; `make dev` runs the
        # worker with --pool solo. Re-create the provider on worker_process_init if that changes.
        # timeout=2 bounds every export, and so the exit flush when the collector is down.
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(timeout=2)))
    trace.set_tracer_provider(provider)
    DjangoInstrumentor().instrument()
    PsycopgInstrumentor().instrument()
    RedisInstrumentor().instrument()
    URLLibInstrumentor().instrument()
    CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]


tracer = trace.get_tracer("tally")
