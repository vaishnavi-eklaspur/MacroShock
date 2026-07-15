"""A mock Snowflake connector backed by SQLite.

Demonstrates the data-warehouse access pattern used in production (BlackRock IPS uses
Snowflake) without requiring a live warehouse or credentials. The public surface mirrors
the parts of `snowflake-connector-python` the app uses:

    conn = connect(database=...)      # snowflake.connector.connect(...)
    cur = conn.cursor()
    cur.execute("SELECT ...", params)
    rows = cur.fetchall()
    df = cur.fetch_pandas_all()       # Snowflake's pandas fast-path
    conn.close()

Swapping this for the real `snowflake.connector` is a one-import change because the
call sites only use this common subset.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path(__file__).with_name("macroshock.db")


class MockCursor:
    """Thin wrapper over a sqlite3 cursor exposing a Snowflake-like API."""

    def __init__(self, sqlite_cursor: sqlite3.Cursor):
        self._cur = sqlite_cursor

    def execute(self, sql: str, params: tuple | list | dict | None = None) -> "MockCursor":
        # sqlite3 uses '?' placeholders; keep call sites parameterized to avoid SQL injection.
        self._cur.execute(sql, params or [])
        return self

    def fetchall(self) -> list[tuple]:
        return self._cur.fetchall()

    def fetchone(self):
        return self._cur.fetchone()

    def fetch_pandas_all(self) -> pd.DataFrame:
        """Mirrors Snowflake's `cursor.fetch_pandas_all()` fast-path."""
        rows = self._cur.fetchall()
        cols = [d[0] for d in self._cur.description] if self._cur.description else []
        return pd.DataFrame(rows, columns=cols)

    def close(self) -> None:
        self._cur.close()


class MockSnowflakeConnection:
    """Context-manager-friendly connection object."""

    def __init__(self, db_path: str | os.PathLike | None = None):
        self._db_path = str(db_path or os.getenv("MACROSHOCK_DB", DEFAULT_DB_PATH))
        self._conn = sqlite3.connect(self._db_path, timeout=5.0)
        self._conn.execute("PRAGMA foreign_keys = ON;")
        # WAL + busy timeout: concurrent readers don't block the writer, and writers wait
        # briefly for a lock instead of failing - matters with multiple gunicorn workers.
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA busy_timeout = 5000;")

    def cursor(self) -> MockCursor:
        return MockCursor(self._conn.cursor())

    def commit(self) -> None:
        self._conn.commit()

    def executescript(self, script: str) -> None:
        self._conn.executescript(script)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MockSnowflakeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.commit()
        self.close()


def connect(database: str | os.PathLike | None = None, **_ignored) -> MockSnowflakeConnection:
    """Entry point mirroring `snowflake.connector.connect(...)`.

    Extra kwargs (account, user, warehouse, ...) are accepted and ignored so call sites
    can be written exactly as they would be for real Snowflake.
    """
    return MockSnowflakeConnection(db_path=database)
