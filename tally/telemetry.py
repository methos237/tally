"""OpenTelemetry setup: one tracer provider, OTLP/HTTP export when
OTEL_EXPORTER_OTLP_ENDPOINT is set (the SDK reads it and appends /v1/traces), and
auto-instrumentation for Django, psycopg, Redis, urllib (outbound webhooks) and Celery.

Called once per process from ApiConfig.ready(), so the Django server and the Celery worker
(which also runs django.setup()) configure themselves the same way. Tests leave the
endpoint unset and attach an in-memory exporter to the same provider.
"""

import os

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


def configure() -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": "tally"}))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        # ponytail: BatchSpanProcessor's thread does not survive a prefork; `make dev` runs the
        # worker with --pool solo. Re-create the provider on worker_process_init if that changes.
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    DjangoInstrumentor().instrument()
    PsycopgInstrumentor().instrument()
    RedisInstrumentor().instrument()
    URLLibInstrumentor().instrument()
    CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]


tracer = trace.get_tracer("tally")
