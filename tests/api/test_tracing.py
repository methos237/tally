"""One trace from POST /api/entries through the outbox write and the Celery delivery to
the tenant's endpoint. The delivery is picked up by a sweep, not enqueued from the request,
so the outbox row carries the W3C traceparent and the delivery span continues it."""

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from tally.adapters.models import ApiKey, OutboxMessage, Subscription, WebhookEndpoint
from tally.adapters.tasks import deliver_due_webhooks
from tests.api.conftest import Idem, Receiver, client_for


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)  # configured by ApiConfig.ready()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.shutdown()


def named(spans: list[ReadableSpan], name: str) -> ReadableSpan:
    return next(s for s in spans if s.name == name)


@pytest.mark.django_db(transaction=True)
def test_entry_post_outbox_and_delivery_share_one_trace(
    subscription: Subscription,
    endpoint: WebhookEndpoint,
    receiver: Receiver,
    spans: InMemorySpanExporter,
) -> None:
    client: Idem = client_for(ApiKey.issue(subscription.tenant, "trace"))
    response = client.post_entry(("1200", "5.000000"), ("4000", "-5.000000"))
    assert response.status_code == 201
    message = OutboxMessage.objects.get(event_type="entry.posted")
    assert message.traceparent.startswith("00-")

    assert deliver_due_webhooks() == 1
    headers, _ = receiver.requests[0]
    assert headers["Traceparent"].split("-")[1] == message.traceparent.split("-")[1]

    finished = spans.get_finished_spans()
    request = next(s for s in finished if s.kind is SpanKind.SERVER)
    publish = named(finished, "outbox.publish")
    deliver = named(finished, "webhook.deliver")
    http = next(s for s in finished if s.kind is SpanKind.CLIENT and "/hooks" in str(s.attributes))
    trace_ids = {s.context.trace_id for s in (request, publish, deliver, http)}
    assert len(trace_ids) == 1, "one trace end to end"
    assert publish.parent is not None and publish.parent.span_id == request.context.span_id
    assert deliver.parent is not None and deliver.parent.span_id == publish.context.span_id
    assert any(s.name.startswith("SELECT") or "postgresql" in str(s.attributes) for s in finished)
