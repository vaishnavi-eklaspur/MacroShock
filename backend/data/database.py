"""Repository layer: parameterized SQL over the (mock Snowflake) warehouse.

Every read the analytics/API layers need goes through here, returning pandas DataFrames
or plain dicts. This is the only module that knows SQL, keeping a clean separation between
storage and computation.
"""
from __future__ import annotations

import pandas as pd

from . import snowflake_mock
from .reference import ASSET_ORDER, FACTOR_ORDER


def _conn(db_path: str | None = None) -> snowflake_mock.MockSnowflakeConnection:
    return snowflake_mock.connect(database=db_path)


def get_assets(db_path: str | None = None) -> pd.DataFrame:
    """Asset reference data incl. factor sensitivities, ordered for display."""
    sql = """
        SELECT ticker, name, asset_class, equity_beta, eff_duration,
               spread_duration, commodity_beta, convexity
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


def get_scenario(scenario_id: str, db_path: str | None = None) -> dict | None:
    for s in get_scenarios(db_path):
        if s["scenario_id"] == scenario_id:
            return s
    return None
