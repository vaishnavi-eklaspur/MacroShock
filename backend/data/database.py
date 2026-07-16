"""Repository layer: parameterized SQL over the (mock Snowflake) warehouse.

Every read the analytics/API layers need goes through here, returning pandas DataFrames
or plain dicts. This is the only module that knows SQL, keeping a clean separation between
storage and computation.
"""
from __future__ import annotations

import datetime as _dt
import json as _json

import pandas as pd

from . import snowflake_mock
from .reference import ASSET_ORDER, FACTOR_ORDER


def _conn(db_path: str | None = None) -> snowflake_mock.MockSnowflakeConnection:
    return snowflake_mock.connect(database=db_path)


def get_assets(db_path: str | None = None) -> pd.DataFrame:
    """Asset reference data incl. factor sensitivities, ordered for display."""
    sql = """
        SELECT ticker, name, asset_class, equity_beta, eff_duration,
               spread_duration, commodity_beta, liquidity_beta, fx_beta, convexity
        FROM assets
        ORDER BY display_order
    """
    with _conn(db_path) as c:
        df = c.cursor().execute(sql).fetch_pandas_all()
    return df


def get_factors(db_path: str | None = None) -> pd.DataFrame:
    sql = "SELECT name, description, unit, annual_vol FROM factors"
    with _conn(db_path) as c:
        df = c.cursor().execute(sql).fetch_pandas_all()
    # keep canonical factor order
    df["__order"] = df["name"].map({f: i for i, f in enumerate(FACTOR_ORDER)})
    return df.sort_values("__order").drop(columns="__order").reset_index(drop=True)


def get_asset_returns(db_path: str | None = None) -> pd.DataFrame:
    """Wide DataFrame of weekly asset returns: index = date, columns = tickers (canonical order)."""
    sql = "SELECT ticker, obs_date, weekly_return FROM asset_returns ORDER BY obs_date"
    with _conn(db_path) as c:
        long = c.cursor().execute(sql).fetch_pandas_all()
    wide = long.pivot(index="obs_date", columns="ticker", values="weekly_return")
    return wide[[t for t in ASSET_ORDER if t in wide.columns]]


def get_factor_returns(db_path: str | None = None) -> pd.DataFrame:
    """Wide DataFrame of weekly factor returns: index = date, columns = factors (canonical order)."""
    sql = "SELECT factor_name, obs_date, weekly_return FROM factor_returns ORDER BY obs_date"
    with _conn(db_path) as c:
        long = c.cursor().execute(sql).fetch_pandas_all()
    wide = long.pivot(index="obs_date", columns="factor_name", values="weekly_return")
    return wide[[f for f in FACTOR_ORDER if f in wide.columns]]


def get_scenarios(db_path: str | None = None) -> list[dict]:
    """List of scenarios, each with its factor-shock vector keyed by factor name."""
    with _conn(db_path) as c:
        cur = c.cursor()
        scen = cur.execute(
            "SELECT scenario_id, name, description, is_historical "
            "FROM scenarios ORDER BY display_order"
        ).fetchall()
        shocks = cur.execute(
            "SELECT scenario_id, factor_name, shock FROM scenario_shocks"
        ).fetchall()

    shock_map: dict[str, dict[str, float]] = {}
    for scenario_id, factor_name, shock in shocks:
        shock_map.setdefault(scenario_id, {})[factor_name] = shock

    out = []
    for scenario_id, name, description, is_historical in scen:
        out.append(
            {
                "scenario_id": scenario_id,
                "name": name,
                "description": description,
                "is_historical": bool(is_historical),
                "shocks": {f: shock_map.get(scenario_id, {}).get(f, 0.0) for f in FACTOR_ORDER},
            }
        )
    return out


def save_portfolio(name: str, weights: dict[str, float], db_path: str | None = None) -> None:
    """Upsert a named portfolio (server-side persistence)."""
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    with _conn(db_path) as c:
        c.cursor().execute(
            "INSERT INTO saved_portfolios (name, weights_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET weights_json=excluded.weights_json, "
            "updated_at=excluded.updated_at",
            (name, _json.dumps(weights), now),
        )


def list_portfolios(db_path: str | None = None) -> list[dict]:
    """All saved portfolios, newest first."""
    with _conn(db_path) as c:
        try:
            rows = c.cursor().execute(
                "SELECT name, weights_json, updated_at FROM saved_portfolios "
                "ORDER BY updated_at DESC").fetchall()
        except Exception:
            return []
    return [{"name": n, "weights": _json.loads(w), "updated_at": u} for n, w, u in rows]


def delete_portfolio(name: str, db_path: str | None = None) -> bool:
    """Delete a saved portfolio; returns True if a row was removed."""
    with _conn(db_path) as c:
        cur = c.cursor()
        cur.execute("DELETE FROM saved_portfolios WHERE name = ?", (name,))
        return cur._cur.rowcount > 0  # noqa: SLF001 - mock cursor wraps sqlite3


def get_dataset_meta(db_path: str | None = None) -> dict[str, str]:
    """Provenance of the loaded return history (source, window, model version)."""
    with _conn(db_path) as c:
        try:
            rows = c.cursor().execute("SELECT key, value FROM dataset_meta").fetchall()
        except Exception:
            return {"source": "unknown"}
    return {k: v for k, v in rows}


def get_realized_crisis_returns(db_path: str | None = None) -> dict[str, dict[str, float]]:
    """Realized crisis returns keyed {scenario_id: {ticker: realized_return}} for backtesting."""
    sql = "SELECT scenario_id, ticker, realized_return FROM realized_crisis_returns"
    with _conn(db_path) as c:
        rows = c.cursor().execute(sql).fetchall()
    out: dict[str, dict[str, float]] = {}
    for scenario_id, ticker, realized in rows:
        out.setdefault(scenario_id, {})[ticker] = float(realized)
    return out
