from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._transaction_connection = ContextVar("finwise_transaction", default=None)
        self.settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.storage_path.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        active = self._transaction_connection.get()
        if active is not None:
            yield active
            return
        connection = sqlite3.connect(self.settings.database_path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        """One write transaction covers effects, versions, command receipt and audit."""
        if self._transaction_connection.get() is not None:
            yield
            return
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            token = self._transaction_connection.set(connection)
            try:
                yield
            finally:
                self._transaction_connection.reset(token)

    def initialize(self) -> None:
        with self.connect() as connection:
            for migration_path in sorted((self.settings.root / "migrations").glob("[0-9]*.sql")):
                connection.executescript(migration_path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (int(migration_path.name.split("_", 1)[0]), utcnow()),
                )

    def reset(self) -> None:
        with self.connect() as connection:
            for table in (
                "external_receipts",
                "reconciliation_checks",
                "processing_runs",
                "audit_events",
                "commands",
                "relations",
                "ontology_objects",
            ):
                connection.execute(f"DELETE FROM {table}")
