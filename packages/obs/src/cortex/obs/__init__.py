"""Shared OpenTelemetry tracing setup (docs/ARCHITECTURE.md §9).

`init_tracing()` configures a global tracer provider that exports OTLP spans to the
collector (OTEL_EXPORTER_OTLP_ENDPOINT). It is a **no-op when the endpoint is
unset** — so tests and local runs without the collector stay silent — and it is
idempotent. One trace id flows API -> retrieve and connector -> worker -> store.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from cortex.obs.llm import complete as complete  # re-export the LLM gateway

__all__ = ["complete", "get_tracer", "init_tracing"]

_initialized = False


def init_tracing(service_name: str) -> bool:
    """Set up OTLP tracing if OTEL_EXPORTER_OTLP_ENDPOINT is set. Returns enabled?."""
    global _initialized
    if _initialized:
        return True
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)
    _initialized = True
    return True


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer; spans are dropped silently if tracing wasn't initialized."""
    return trace.get_tracer(name)
