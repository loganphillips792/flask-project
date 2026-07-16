"""Structured JSON logging for the library app.

`init_logging()` installs a stdout handler that emits one JSON object per line
and registers a per-request access log. Promtail ships these lines to Loki, and
each carries the active span's trace_id so Grafana can jump from a Tempo span
straight to its logs.

Named `logging` but this does not shadow the stdlib: inside the `app` package,
a bare `import logging` still resolves to the top-level stdlib module.
"""

import json
import logging
import os
import sys

from flask import has_request_context, request
from opentelemetry import trace


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line on stdout.

    The `level`, `msg`, and `uri` keys are required verbatim: Promtail's
    pipeline in observability/promtail-config.yaml extracts them by name.
    """

    def __init__(self, service_name):
        super().__init__()
        self.service_name = service_name

    def format(self, record):
        payload = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "msg": record.getMessage(),
            "uri": request.path if has_request_context() else "",
            "logger": record.name,
            "service": self.service_name,
        }

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            # Lets Grafana jump from a Tempo span to the matching log lines.
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")

        # Structured extras: `logger.info(msg, extra={"fields": {...}})` merges
        # those keys into the JSON line so Loki can parse them out.
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload)


def init_logging(app, service_name, excluded_paths):
    """Install the JSON stdout handler and per-request access logging.

    Called by `init_observability()`. `service_name` tags every line;
    `excluded_paths` are skipped by the request log to keep scrape traffic
    (/metrics, /health) out of Loki.
    """
    _configure_handler(service_name)
    _log_requests(app, excluded_paths)


def _configure_handler(service_name):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))

    # Configure the root logger so every `logging.getLogger(__name__)` in the
    # app inherits this handler and level with no per-module setup.
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def _log_requests(app, excluded_paths):
    """One log line per request.

    Gunicorn's own access log is plain text, not JSON, so Promtail could not
    parse it — and the dev server's Werkzeug logging doesn't run under gunicorn
    at all. Without this the Loki panel would sit essentially empty.
    """
    logger = logging.getLogger("app.request")

    @app.after_request
    def log_request(response):
        if request.path not in excluded_paths:
            logger.info(f"{request.method} {request.path} {response.status_code}")
        return response
