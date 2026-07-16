"""Prometheus instrumentation for SQLite queries.

The OpenTelemetry sqlite3 instrumentation only wraps the connection-level
`execute()` shortcut, which peewee uses solely for connection-setup PRAGMAs — so
real SELECT/INSERT/UPDATE queries produced no telemetry. This wraps peewee's
`execute_sql`, the single chokepoint every query passes through, and emits
metrics on the default registry that `prometheus-flask-exporter` serves at
`/metrics`.
"""

import logging
import os
import re
import sqlite3
import time

from peewee import SqliteDatabase
from prometheus_client import Counter, Histogram
from prometheus_client.core import GaugeMetricFamily

# One line per query, shipped to Loki and surfaced by the "Recent queries" panel.
# The SQL is the parameterized template (placeholders, not values), so param
# values — e.g. password hashes — are never logged.
_query_logger = logging.getLogger("app.db")

# Captured before SQLite3Instrumentor globally patches sqlite3.connect (that
# happens later, in init_observability). The stats collector uses this original
# function so its scrape-time reads bypass both peewee and OTel — no query-metric
# inflation and no spans every 10s.
_raw_connect = sqlite3.connect

DB_QUERIES = Counter(
    "db_queries_total", "SQLite queries executed", ["operation", "status"]
)

# Default histogram buckets start at 5ms, but SQLite queries here are sub-ms —
# they'd all land in the first bucket and percentiles would be meaningless.
DB_QUERY_DURATION = Histogram(
    "db_query_duration_seconds",
    "SQLite query duration",
    ["operation"],
    buckets=(0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
)

_FIRST_WORD = re.compile(r"\s*(\w+)")


def _operation(sql):
    # First SQL keyword — SELECT/INSERT/UPDATE/DELETE/PRAGMA/BEGIN/COMMIT/CREATE.
    # Bounded set, so it's safe as a label.
    match = _FIRST_WORD.match(sql or "")
    return match.group(1).upper() if match else "OTHER"


class InstrumentedSqliteDatabase(SqliteDatabase):
    """Drop-in SqliteDatabase that records a metric per query."""

    def execute_sql(self, sql, *args, **kwargs):
        operation = _operation(sql)
        start = time.perf_counter()
        status = "ok"
        try:
            return super().execute_sql(sql, *args, **kwargs)
        except Exception:
            status = "error"
            raise
        finally:
            duration = time.perf_counter() - start
            DB_QUERY_DURATION.labels(operation).observe(duration)
            DB_QUERIES.labels(operation, status).inc()
            _query_logger.info(
                sql,
                extra={
                    "fields": {
                        "operation": operation,
                        "duration_ms": round(duration * 1000, 3),
                        "status": status,
                    }
                },
            )


class SqliteStatsCollector:
    """Exposes db_file_size_bytes and db_table_rows, sampled at scrape time.

    Uses the raw sqlite3 connection captured above so counting rows neither
    inflates db_queries_total nor emits spans. Stays silent (no samples) when
    the file or tables don't exist yet, so it never fails a scrape.
    """

    def __init__(self, db_path):
        self.db_path = db_path

    def collect(self):
        size = GaugeMetricFamily(
            "db_file_size_bytes", "SQLite file size on disk", labels=["file"]
        )
        for label, suffix in (("main", ""), ("wal", "-wal")):
            try:
                size.add_metric([label], os.path.getsize(self.db_path + suffix))
            except OSError:
                pass
        yield size

        rows = GaugeMetricFamily(
            "db_table_rows", "Row count per table", labels=["table"]
        )
        try:
            conn = _raw_connect(self.db_path)
            try:
                tables = [
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                ]
                for table in tables:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    rows.add_metric([table], count)
            finally:
                conn.close()
        except sqlite3.Error:
            pass
        yield rows
