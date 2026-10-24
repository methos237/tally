"""OpenTelemetry setup: one tracer provider, OTLP/HTTP to Jaeger when an endpoint is set,
auto-instrumentation for Django, psycopg, Redis, urllib (outbound webhooks) and Celery.

Called once from ApiConfig.ready(), so the Django server and the Celery worker (which
also runs django.setup()) configure themselves the same way. Tests leave the endpoint
empty and attach an in-memory exporter to the same provider.
"""

from django.conf import settings
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

configured = False


def configure() -> TracerProvider:
    global configured
    provider = TracerProvider(resource=Resource.create({"service.name": "tally"}))
    if endpoint := settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        # ponytail: BatchSpanProcessor's thread does not survive a prefork; `make dev` runs the
        # worker with --pool solo. Re-create the provider on worker_process_init if that changes.
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
    trace.set_tracer_provider(provider)
    if not configured:  # instrumentors patch libraries once per process
        DjangoInstrumentor().instrument()
        PsycopgInstrumentor().instrument()
        RedisInstrumentor().instrument()
        URLLibInstrumentor().instrument()
        CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
        configured = True
    return provider


tracer = trace.get_tracer("tally")
