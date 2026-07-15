"""Real Snowflake adapter (import-guarded) — mirrors the mock's surface exactly.

Enabled by `MACROSHOCK_WAREHOUSE=snowflake` with the SNOWFLAKE_* env vars set. The call
sites in `database.py` are unchanged; only the connection factory differs. This is the honest
version of the "Snowflake-ready" claim: real `snowflake-connector-python` code.

Portability notes (I know the dialect differs, so I state it rather than pretend):
  * `paramstyle` is set to 'qmark' so the repo's `?` placeholders work on Snowflake.
  * The read queries are standard `SELECT`s and run as-is.
  * The DDL in schema.sql is SQLite-flavoured (`PRAGMA`, `AUTOINCREMENT`-free, `ON CONFLICT`
    upsert). Seeding a real Snowflake needs the standard-SQL equivalent (no PRAGMA, `MERGE`
    for upsert). Reads are the portable path; that is what this adapter targets.
"""
from __future__ import annotations

import os

try:  # import-guarded so the default build never needs the Snowflake package
    import snowflake.connector as _sfc  # type: ignore
    _sfc.paramstyle = "qmark"           # honour the repo's '?' placeholders
except Exception:  # pragma: no cover - optional dependency
    _sfc = None  # type: ignore


class SnowflakeConnection:
    """Thin wrapper giving the same surface as the SQLite mock (cursor/commit/close/context)."""

    def __init__(self, **_ignored):
        if _sfc is None:
            raise RuntimeError("snowflake-connector-python not installed. "
                               "`pip install snowflake-connector-python`.")
        self._conn = _sfc.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
            database=os.getenv("SNOWFLAKE_DATABASE", "MACROSHOCK"),
            schema=os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
        )

    def cursor(self):
        # The real Snowflake cursor already exposes execute/fetchall/fetch_pandas_all.
        return self._conn.cursor()

    def commit(self) -> None:
        self._conn.commit()

    def executescript(self, script: str) -> None:
        cur = self._conn.cursor()
        for stmt in (s.strip() for s in script.split(";")):
            if stmt:
                cur.execute(stmt)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SnowflakeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.commit()
        self.close()


def connect(database=None, **kwargs) -> SnowflakeConnection:
    """Entry point mirroring `snowflake.connector.connect(...)` (and the SQLite mock)."""
    return SnowflakeConnection(database=database, **kwargs)
