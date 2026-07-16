"""Metrics and tracing for the library app.

Wired up by `create_app()`. The three pillars land in the stack under
`observability/`: Prometheus scrapes `/metrics`, spans are exported to Tempo
over OTLP/HTTP, and structured logging (shipped to Loki by Promtail) lives in
app/logging.py.
"""

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_flask_exporter import PrometheusMetrics

from app.logging import init_logging

SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "flask-app")

# Prometheus scrapes /metrics every 10s. Without these exclusions the scrape
# itself generates a span and a log line, drowning real traffic.
EXCLUDED_PATHS = ["/metrics", "/health"]


def _configure_tracing(app):
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))

    # No endpoint configured (plain `python run.py`) means spans are still
    # created — so log lines keep their trace_id — but nothing is exported.
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    FlaskInstrumentor().instrument_app(app, excluded_urls=",".join(EXCLUDED_PATHS))
    SQLite3Instrumentor().instrument()


def init_observability(app):
    """Must be called after blueprints are registered.

    PrometheusMetrics derives its `endpoint` label from the registered views.
    """
    init_logging(app, SERVICE_NAME, EXCLUDED_PATHS)
    _configure_tracing(app)
    PrometheusMetrics(app, group_by="endpoint", excluded_paths=EXCLUDED_PATHS)
