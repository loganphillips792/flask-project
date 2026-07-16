import os

from prometheus_client import REGISTRY

from app.db_metrics import InstrumentedSqliteDatabase, SqliteStatsCollector

DB_PATH = os.environ.get("LIBRARY_DB_PATH", "library.db")

db = InstrumentedSqliteDatabase(
    DB_PATH,
    pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
    },
)

# Surfaces db_file_size_bytes and db_table_rows at scrape time.
REGISTRY.register(SqliteStatsCollector(DB_PATH))
