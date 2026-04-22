# SPDX-License-Identifier: MIT
# CI Engine - OpenTelemetry Tracing

import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor


_tracer: Optional[trace.Tracer] = None
_propagator = TraceContextTextMapPropagator()


def init_tracing(service_name: str = "ci-engine") -> trace.Tracer:
    """Initialize OpenTelemetry tracing."""
    global _tracer

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            "service.version": os.environ.get("CI_ENGINE_VERSION", "0.1.0"),
            "deployment.environment": os.environ.get("CI_ENGINE_ENV", "development"),
        }
    )

    provider = TracerProvider(resource=resource)

    if os.environ.get("CI_ENGINE_TRACE_CONSOLE", "false").lower() == "true":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    otlp_endpoint = os.environ.get("CI_ENGINE_OTLP_ENDPOINT")
    if otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(__name__)

    return _tracer


def get_tracer() -> trace.Tracer:
    """Get the global tracer."""
    global _tracer
    if _tracer is None:
        _tracer = init_tracing()
    return _tracer


def trace_asyncoperation(name: str):
    """Decorator for tracing async operations."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(name) as span:
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(trace.StatusCode.OK)
                    return result
                except Exception as e:
                    span.set_status(trace.StatusCode.ERROR, str(e))
                    span.record_exception(e)
                    raise

        return wrapper

    return decorator


def trace_syncoperation(name: str):
    """Decorator for tracing sync operations."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(name) as span:
                try:
                    result = func(*args, **kwargs)
                    span.set_status(trace.StatusCode.OK)
                    return result
                except Exception as e:
                    span.set_status(trace.StatusCode.ERROR, str(e))
                    span.record_exception(e)
                    raise

        return wrapper

    return decorator


def instrument_fastapi(app):
    """Instrument FastAPI app for tracing."""
    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()


def inject_trace_context(carrier: dict[str, str]):
    """Inject trace context into carrier for propagation."""
    _propagator.inject(carrier)


def extract_trace_context(carrier: dict[str, str]):
    """Extract trace context from carrier."""
    return _propagator.extract(carrier)


class TraceContext:
    """Context manager for manual span creation."""

    def __init__(self, name: str, attributes: Optional[dict] = None):
        self.name = name
        self.attributes = attributes or {}
        self.span = None

    def __enter__(self):
        tracer = get_tracer()
        self.span = tracer.start_span(self.name)
        for key, value in self.attributes.items():
            self.span.set_attribute(key, value)
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            if exc_type is not None:
                self.span.set_status(trace.StatusCode.ERROR, str(exc_val))
                self.span.record_exception(exc_val)
            else:
                self.span.set_status(trace.StatusCode.OK)
            self.span.end()


def create_span(name: str, attributes: Optional[dict] = None) -> trace.Span:
    """Create a new span."""
    tracer = get_tracer()
    span = tracer.start_span(name)
    if attributes:
        for key, value in attributes.items():
            span.set_attribute(key, value)
    return span
