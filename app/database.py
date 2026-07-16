from peewee import SqliteDatabase

db = SqliteDatabase(
    "library.db",
    pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
    },
)
