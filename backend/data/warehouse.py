"""Warehouse connection dispatcher — the single swap point between mock and real Snowflake.

Default: the SQLite-backed mock (reproducible, zero-config). Set MACROSHOCK_WAREHOUSE=snowflake
with the SNOWFLAKE_* env vars to route reads at a real Snowflake account instead. Call sites
(`database.py`) never change.
"""
from __future__ import annotations

import os


def connect(database=None, **kwargs):
    if os.getenv("MACROSHOCK_WAREHOUSE", "mock").lower() == "snowflake":
        from . import snowflake_real
        return snowflake_real.connect(database=database, **kwargs)
    from . import snowflake_mock
    return snowflake_mock.connect(database=database, **kwargs)
